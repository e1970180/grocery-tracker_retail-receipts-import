import contextlib
import dataclasses
import logging
import threading
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from retail_receipts_import.adapters.files.store import FileStore
from retail_receipts_import.adapters.postgres.chains import ChainReference
from retail_receipts_import.adapters.postgres.receipts import WriteKind, WriteResult
from retail_receipts_import.adapters.queue.sqlite import Queue
from retail_receipts_import.adapters.telegram.client import (
    TelegramAPIError,
    TelegramClient,
    TelegramRetryExhaustedError,
)
from retail_receipts_import.adapters.telegram.download import (
    FileTooLarge,
    FileUnavailable,
    download_file,
)
from retail_receipts_import.app import jobs, loop
from retail_receipts_import.app.alerts import Alerts
from retail_receipts_import.app.jobs import JobPorts
from retail_receipts_import.app.notify import Notifier
from retail_receipts_import.app.pipeline import Ports
from retail_receipts_import.domain.chains import KnownChain
from retail_receipts_import.domain.chains.spar.schema import SparPass2
from retail_receipts_import.domain.extraction import GeminiCallError, classify
from retail_receipts_import.domain.intake import MAX_FILE_BYTES, Accepted, FileKind
from retail_receipts_import.domain.jobs import Job, JobState
from retail_receipts_import.domain.outcomes import AlertKind, FailureReason
from retail_receipts_import.domain.receipt import (
    PAYLOAD_VERSION,
    NormalizedReceipt,
    ReceiptSource,
    telegram_source,
)
from tests.spar_samples import pass1_response, response
from tests.test_notify import ADMIN, TEXTS, RecordingTelegram
from tests.test_queue import write_v1_queue

FIXTURES = Path(__file__).parent / "fixtures"
ALLOWED = 12345
EXISTING_ID = uuid.UUID(int=7)
SETTINGS = loop.LoopSettings(
    allowed_user_ids=frozenset({ALLOWED}),
    poll_timeout_s=30,
    retry_delay=timedelta(seconds=600),
    max_attempts=3,
)
PDF_BYTES = b"%PDF-1.7 receipt"
SPAR = KnownChain("spar", "Spar", ("SPAR", "Spar", "INTERSPAR"), ("46108893754",))
SPAR_ONLY = ChainReference(chains=(SPAR,), inactive_ids=(), rejected=())
SPAR_WITHDRAWN = ChainReference(chains=(), inactive_ids=("spar",), rejected=())
# Answers that make a receipt stored: pass 1 finds Spar, pass 2 adds up.
STORED_ANSWERS = (pass1_response(), response())
# Raised by a fake to stop the job mid-way, as a crash or an unexpected error would.
STOP = RuntimeError("stopped here")
UNAVAILABLE = GeminiCallError(code=429, status="RESOURCE_EXHAUSTED", retry_delay_s=37)
BLOCKED = GeminiCallError(code=404, status="NOT_FOUND", detail="models/gone is not found")


def pdf_update(
    update_id: int, message_id: int, sender: int = ALLOWED, chat_type: str = "private"
) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "chat": {"id": sender, "type": chat_type},
            "from": {"id": sender, "first_name": "Ana"},
            "document": {
                "file_id": f"f{message_id}",
                "file_size": 16,
                "mime_type": "application/pdf",
            },
        },
    }


@dataclass
class FakeTelegram:
    batches: list[list[dict[str, Any]]]
    offsets: list[int | None] = field(default_factory=list)
    timeouts: list[int] = field(default_factory=list)

    def get_updates(
        self, *, offset: int | None, timeout: int, allowed_updates: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        assert allowed_updates == ("message",)
        self.offsets.append(offset)
        self.timeouts.append(timeout)
        return self.batches.pop(0) if self.batches else []


@dataclass
class Fakes:
    queue: Queue
    files: FileStore
    # Gemini's answers in call order; an exception is raised instead of answered.
    answers: list[str | Exception] = field(default_factory=lambda: list(STORED_ANSWERS))
    write_result: WriteKind | Exception = WriteKind.STORED
    # The receipt another source already stored under the key pass 1 names; None for a new one.
    stored_id: uuid.UUID | None = None
    reference: ChainReference = SPAR_ONLY
    download_error: Exception | None = None
    telegram: RecordingTelegram = field(default_factory=RecordingTelegram)
    now: datetime = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    downloads: list[str] = field(default_factory=list)
    generated: list[type[BaseModel]] = field(default_factory=list)
    step_starts_seen: list[int] = field(default_factory=list)
    written: list[tuple[uuid.UUID, NormalizedReceipt, ReceiptSource]] = field(default_factory=list)
    lookups: list[tuple[str, datetime, ReceiptSource]] = field(default_factory=list)
    pipelines_opened: int = 0
    alerts: Alerts = field(init=False)

    def __post_init__(self) -> None:
        self.telegram.observe = self.snapshot
        self.alerts = Alerts(Notifier(self.telegram, TEXTS, ADMIN), TEXTS)

    def snapshot(self) -> tuple[JobState | None, bool, int | None]:
        """The job's state, whether its file exists, and the committed offset, at a send."""
        rows = self.queue._conn.execute("SELECT state FROM jobs WHERE job_id = 1").fetchall()
        state = JobState(rows[0][0]) if rows else None
        return state, self.file().exists(), self.queue.read_offset()

    def file(self) -> Path:
        return self.files.path_for(ALLOWED, 3, "application/pdf")

    def download(self, file_id: str, declared_size: int) -> bytes:
        self.downloads.append(file_id)
        if self.download_error is not None:
            raise self.download_error
        return PDF_BYTES

    def generate(self, data: bytes, mime: str, prompt: str, schema: type[BaseModel]) -> str:
        assert data == PDF_BYTES
        self.generated.append(schema)
        self.step_starts_seen.append(self.job().step_starts)
        assert self.answers, "unexpected Gemini call"
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def write(
        self, receipt_id: uuid.UUID, receipt: NormalizedReceipt, source: ReceiptSource
    ) -> WriteResult:
        self.written.append((receipt_id, receipt, source))
        if isinstance(self.write_result, Exception):
            raise self.write_result
        if self.write_result is WriteKind.DUPLICATE:
            return WriteResult(WriteKind.DUPLICATE, EXISTING_ID)
        return WriteResult(self.write_result, receipt_id)

    def find_other_source(
        self, chain_id: str, purchased_at: datetime, source: ReceiptSource
    ) -> uuid.UUID | None:
        self.lookups.append((chain_id, purchased_at, source))
        return self.stored_id

    @contextlib.contextmanager
    def open_pipeline(self) -> Iterator[Ports]:
        self.pipelines_opened += 1
        yield Ports(
            generate=self.alerts.watch_generate(self.generate),
            write=self.write,
            find_other_source=self.find_other_source,
            read_chain_reference=lambda: self.alerts.read_checked(lambda: self.reference),
            prepare=lambda data, mime: data,
            classify=lambda error, waits: classify(error, waits, initial_s=600, cap_s=1800),
        )

    def ports(self) -> JobPorts:
        return JobPorts(
            queue=self.queue,
            files=self.files,
            download=self.download,
            open_pipeline=self.open_pipeline,
            notify=Notifier(self.telegram, TEXTS, ADMIN),
            clock=lambda: self.now,
            alerts=self.alerts,
        )

    def job(self) -> Job:
        return self.queue.job(1)

    def state(self) -> JobState:
        return self.job().state

    def failure_reason(self) -> str | None:
        [row] = self.queue._conn.execute("SELECT failure_reason FROM jobs").fetchall()
        return row[0]  # type: ignore[no-any-return]

    def due_at(self) -> datetime:
        [row] = self.queue._conn.execute("SELECT due_at FROM jobs").fetchall()
        return datetime.fromtimestamp(row[0], UTC)

    def pass2_calls(self) -> int:
        return sum(1 for schema in self.generated if schema is SparPass2)


def make_fakes(tmp_path: Path, answers: Sequence[str | Exception] = STORED_ANSWERS) -> Fakes:
    return Fakes(
        Queue(tmp_path / "queue.sqlite3"), FileStore(tmp_path / "files"), answers=list(answers)
    )


@pytest.fixture
def fakes(tmp_path: Path) -> Fakes:
    return make_fakes(tmp_path)


def cycle(telegram: FakeTelegram, fakes: Fakes, settings: loop.LoopSettings = SETTINGS) -> None:
    ports = fakes.ports()
    loop.poll(telegram, ports, settings)
    loop.run_due(ports, settings, threading.Event())


def first_cycle(fakes: Fakes, settings: loop.LoopSettings = SETTINGS) -> None:
    cycle(FakeTelegram([[pdf_update(100, 3)]]), fakes, settings)


def rerun(fakes: Fakes) -> None:
    loop.run_due(fakes.ports(), SETTINGS, threading.Event())


def restarted(fakes: Fakes, tmp_path: Path, answers: Sequence[str | Exception]) -> Fakes:
    fakes.queue.close()
    again = make_fakes(tmp_path, answers)
    again.now = fakes.now + timedelta(seconds=600)
    return again


DUPLICATE_SENDS = [
    ("reaction", ALLOWED, 3, "🤝"),
    ("message", ALLOWED, "Данный чек уже внесен в систему", 3),
]


def test_stored_receipt_gets_the_success_reaction_then_loses_its_file(fakes: Fakes) -> None:
    first_cycle(fakes)
    assert fakes.state() is JobState.STORED
    assert fakes.telegram.calls == [("reaction", ALLOWED, 3, "👍")]
    # Sent once the state was final, while the file was still there; deleted after.
    assert fakes.telegram.seen == [(JobState.STORED, True, 101)]
    assert not fakes.file().exists()
    [(receipt_id, receipt, source)] = fakes.written
    assert receipt.chain_id == "spar"
    assert source == telegram_source(ALLOWED, 3, buyer_name="Ana")
    assert fakes.job().receipt_id == str(receipt_id)


def test_failed_reaction_is_only_logged(fakes: Fakes, caplog: pytest.LogCaptureFixture) -> None:
    fakes.telegram.fail = True
    first_cycle(fakes)
    assert fakes.state() is JobState.STORED
    assert "job 1: reaction failed" in caplog.text
    assert not fakes.file().exists()


def test_duplicate_from_the_writer_gets_its_reaction_and_message(fakes: Fakes) -> None:
    fakes.write_result = WriteKind.DUPLICATE
    first_cycle(fakes)
    assert fakes.state() is JobState.DUPLICATE
    assert fakes.job().receipt_id == str(EXISTING_ID)
    assert fakes.telegram.calls == DUPLICATE_SENDS
    assert {seen[0] for seen in fakes.telegram.seen} == {JobState.DUPLICATE}
    assert not fakes.file().exists()


def test_own_earlier_write_is_stored(fakes: Fakes) -> None:
    fakes.write_result = WriteKind.OWN_WRITE
    first_cycle(fakes)
    assert fakes.state() is JobState.STORED


def test_resend_from_another_source_ends_after_pass1_without_pass2(
    fakes: Fakes, caplog: pytest.LogCaptureFixture
) -> None:
    fakes.stored_id = EXISTING_ID
    fakes.answers = [pass1_response(purchase_date="01.02.2030")]
    caplog.set_level(logging.INFO)
    first_cycle(fakes)
    job = fakes.job()
    assert (job.state, job.receipt_id) == (JobState.DUPLICATE, str(EXISTING_ID))
    # No attempt, nothing kept for pass 2, and no write.
    assert (job.attempts, job.pass1_json) == (0, None)
    assert fakes.generated != [] and fakes.pass2_calls() == 0
    assert fakes.written == []
    assert fakes.telegram.calls == DUPLICATE_SENDS
    assert not fakes.file().exists()
    # The printed 09:05 in Zagreb winter time is the key's 08:05 UTC.
    assert fakes.lookups == [
        ("spar", datetime(2030, 2, 1, 8, 5, tzinfo=UTC), telegram_source(ALLOWED, 3, "Ana"))
    ]
    assert "pre-check" in caplog.text


def test_new_purchase_passes_the_precheck_and_is_stored(fakes: Fakes) -> None:
    first_cycle(fakes)
    assert fakes.state() is JobState.STORED
    assert len(fakes.lookups) == 1 and fakes.pass2_calls() == 1


def test_precheck_miss_leads_to_the_writers_own_write_and_stored(fakes: Fakes) -> None:
    # Only the miss path: the own-source filter is the adapter's, covered by
    # tests/test_dedup.py::test_find_other_source_ignores_the_own_source.
    fakes.write_result = WriteKind.OWN_WRITE
    first_cycle(fakes)
    assert fakes.state() is JobState.STORED
    assert len(fakes.lookups) == 1 and fakes.pass2_calls() == 1


@pytest.mark.parametrize(
    "overrides",
    [{"purchase_time": None}, {"purchase_date": None}, {"purchase_time": "9h"}],
    ids=["no-time", "no-date", "unreadable-time"],
)
def test_unreadable_pass1_time_skips_the_lookup_and_the_writer_decides(
    tmp_path: Path, overrides: dict[str, Any]
) -> None:
    fakes = make_fakes(tmp_path, [pass1_response(**overrides), response()])
    fakes.write_result = WriteKind.DUPLICATE
    first_cycle(fakes)
    assert fakes.lookups == []
    assert fakes.pass2_calls() == 1
    assert fakes.state() is JobState.DUPLICATE
    assert fakes.job().receipt_id == str(EXISTING_ID)


@pytest.mark.parametrize(
    "answers",
    [
        ["not json"],
        [pass1_response(chain="unreadable")],
        [pass1_response(), response(seller_oib="99999999999")],
        [pass1_response(), response(total="2,99")],
        [pass1_response(), response(payments=[{"text": "PLAĆANJE MASTERCARD", "amount": "2,50"}])],
        [GeminiCallError(code=400, status="INVALID_ARGUMENT", detail="Unable to process")],
        [pass1_response(), GeminiCallError(code=400, status="INVALID_ARGUMENT")],
    ],
    ids=[
        "schema",
        "unreadable",
        "oib",
        "total-mismatch",
        "items-mismatch",
        "gemini-4xx-pass-1",
        "gemini-4xx-pass-2",
    ],
)
def test_invalid_result_consumes_an_attempt_and_restarts_from_pass1(
    tmp_path: Path, answers: list[str | Exception]
) -> None:
    fakes = make_fakes(tmp_path, [*answers, STOP])
    first_cycle(fakes)
    job = fakes.job()
    assert (job.state, job.attempts, job.unsupported, job.pass1_json) == (
        JobState.CHAIN_PENDING,
        1,
        False,
        None,
    )
    # The retry is pass 1 again, run at once, and stopped there.
    assert fakes.generated[-1] is not SparPass2


def test_invalid_clears_the_unsupported_flag(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path, [pass1_response(chain="other"), "not json", STOP])
    first_cycle(fakes)
    job = fakes.job()
    assert (job.state, job.attempts, job.unsupported) == (JobState.CHAIN_PENDING, 2, False)


def test_invalid_on_the_last_attempt_fails_with_its_own_reason(tmp_path: Path) -> None:
    answers = ["not json", "not json", pass1_response(), response(total="2,99")]
    fakes = make_fakes(tmp_path, answers)
    first_cycle(fakes)
    assert fakes.state() is JobState.FAILED
    assert fakes.failure_reason() == "total_settlement_mismatch"
    assert fakes.answers == [] and fakes.written == []
    assert fakes.telegram.calls[0] == ("reaction", ALLOWED, 3, "👎")


def test_first_unsupported_consumes_an_attempt_and_sets_the_flag(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path, [pass1_response(chain="other"), STOP])
    first_cycle(fakes)
    job = fakes.job()
    assert (job.state, job.attempts, job.unsupported) == (JobState.CHAIN_PENDING, 1, True)


def test_second_unsupported_in_a_row_ends_the_job_and_tells_both(tmp_path: Path) -> None:
    other = pass1_response(chain="other", store_name="KONZUM")
    fakes = make_fakes(tmp_path, [other, other])
    first_cycle(fakes)
    assert fakes.state() is JobState.UNSUPPORTED_CHAIN
    assert len(fakes.generated) == 2
    assert fakes.failure_reason() is None
    assert fakes.telegram.calls == [
        ("reaction", ALLOWED, 3, None),
        ("message", ALLOWED, "Чеки этой сети пока не поддерживаются.", 3),
        ("message", ADMIN, "Чек неподдерживаемой сети.\nAna\n#1\nKONZUM", None),
    ]
    assert {seen[0] for seen in fakes.telegram.seen} == {JobState.UNSUPPORTED_CHAIN}
    assert not fakes.file().exists()


def test_unsupported_then_supported_is_not_a_run(tmp_path: Path) -> None:
    other = pass1_response(chain="other")
    fakes = make_fakes(tmp_path, [other, pass1_response(), STOP])
    first_cycle(fakes)
    job = fakes.job()
    assert (job.state, job.attempts, job.unsupported) == (JobState.EXTRACT_PENDING, 1, False)


def test_unsupported_on_the_last_attempt_is_unsupported_not_failed(tmp_path: Path) -> None:
    other = pass1_response(chain="other")
    fakes = make_fakes(tmp_path, [other, "not json", other])
    first_cycle(fakes)
    assert fakes.state() is JobState.UNSUPPORTED_CHAIN
    assert fakes.answers == []


def test_with_one_attempt_the_first_unsupported_ends_the_job(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path, [pass1_response(chain="other")])
    first_cycle(fakes, dataclasses.replace(SETTINGS, max_attempts=1))
    assert fakes.state() is JobState.UNSUPPORTED_CHAIN


def test_recorded_unknown_chain_takes_the_unsupported_path(tmp_path: Path) -> None:
    # A live Lidl answer recorded against a reference that knows only Spar; the store and
    # purchase time are nulled, as they are the owner's own purchase.
    recorded = (FIXTURES / "unknown_chain" / "pass1.json").read_text(encoding="utf-8")
    fakes = make_fakes(tmp_path, [recorded, recorded])
    first_cycle(fakes)
    assert fakes.state() is JobState.UNSUPPORTED_CHAIN
    assert fakes.pass2_calls() == 0


def test_supported_chain_persists_pass1_and_a_restart_skips_it(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path, [pass1_response(), STOP])
    first_cycle(fakes)
    job = fakes.job()
    assert job.state is JobState.EXTRACT_PENDING
    assert job.pass1_json is not None and '"chain":"spar"' in job.pass1_json

    again = restarted(fakes, tmp_path, [response()])
    rerun(again)
    assert again.state() is JobState.STORED
    assert again.generated == [SparPass2]


def test_chain_withdrawn_before_pass2_restarts_pass1_without_an_attempt(tmp_path: Path) -> None:
    # One attempt already spent, so keeping the count differs from resetting it.
    fakes = make_fakes(tmp_path, ["not json", pass1_response(), STOP])
    first_cycle(fakes)
    assert (fakes.state(), fakes.job().attempts) == (JobState.EXTRACT_PENDING, 1)

    fakes.reference = SPAR_WITHDRAWN
    fakes.answers = [STOP]
    fakes.now += timedelta(seconds=600)
    before = len(fakes.generated)
    rerun(fakes)
    job = fakes.job()
    assert (job.state, job.attempts, job.pass1_json) == (JobState.CHAIN_PENDING, 1, None)
    # The withdrawn chain cost no pass-2 call; the one call made was pass 1 again.
    [again] = fakes.generated[before:]
    assert again is not SparPass2


def test_valid_receipt_is_kept_with_its_id_before_the_write(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path)
    fakes.write_result = RuntimeError("postgres down")
    first_cycle(fakes)
    job = fakes.job()
    assert job.state is JobState.WRITE_PENDING
    assert job.payload_version == PAYLOAD_VERSION
    assert job.receipt_json is not None and job.receipt_id is not None
    [(receipt_id, receipt, _)] = fakes.written
    assert str(receipt_id) == job.receipt_id
    assert NormalizedReceipt.model_validate_json(job.receipt_json) == receipt
    # The write exception keeps the job where it is, due after the generic delay.
    assert fakes.due_at() == fakes.now + SETTINGS.retry_delay


@pytest.mark.parametrize(
    ("kind", "state"),
    [(WriteKind.STORED, JobState.STORED), (WriteKind.DUPLICATE, JobState.DUPLICATE)],
)
def test_restart_in_write_pending_never_calls_gemini(
    tmp_path: Path, kind: WriteKind, state: JobState
) -> None:
    fakes = make_fakes(tmp_path)
    fakes.write_result = RuntimeError("postgres down")
    first_cycle(fakes)
    kept_id = fakes.job().receipt_id

    again = restarted(fakes, tmp_path, [])
    again.write_result = kind
    rerun(again)
    assert again.state() is state
    assert again.generated == []
    [(receipt_id, _, _)] = again.written
    assert str(receipt_id) == kept_id


@pytest.mark.parametrize(
    "corruption",
    ["payload_version = 0", "receipt_json = '{\"payload_version\": 1'"],
    ids=["other-version", "unparseable"],
)
def test_kept_receipt_of_another_version_redoes_pass2_only(tmp_path: Path, corruption: str) -> None:
    fakes = make_fakes(tmp_path)
    fakes.write_result = RuntimeError("postgres down")
    first_cycle(fakes)
    fakes.queue._conn.execute(f"UPDATE jobs SET {corruption}")

    again = restarted(fakes, tmp_path, [response()])
    rerun(again)
    assert again.state() is JobState.STORED
    assert again.generated == [SparPass2]
    assert again.job().attempts == 0


@pytest.mark.parametrize("pass_no", [1, 2])
@pytest.mark.parametrize(
    ("error", "level", "delay"),
    [(UNAVAILABLE, logging.WARNING, 37), (BLOCKED, logging.ERROR, 600)],
    ids=["unavailable", "blocked"],
)
def test_gemini_wait_keeps_the_state_and_consumes_no_attempt(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    error: GeminiCallError,
    level: int,
    delay: int,
    pass_no: int,
) -> None:
    answers: list[str | Exception] = [error] if pass_no == 1 else [pass1_response(), error]
    fakes = make_fakes(tmp_path, answers)
    first_cycle(fakes)
    job = fakes.job()
    waiting = JobState.CHAIN_PENDING if pass_no == 1 else JobState.EXTRACT_PENDING
    assert (job.state, job.attempts, job.waits, job.step_starts) == (waiting, 0, 1, 0)
    assert fakes.due_at() == fakes.now + timedelta(seconds=delay)
    [record] = [r for r in caplog.records if r.name == jobs.__name__ and r.levelno == level]
    assert record.exc_info is None

    fakes.answers = list(STORED_ANSWERS[pass_no - 1 :])
    fakes.now += timedelta(seconds=delay - 1)
    rerun(fakes)
    assert fakes.state() is waiting
    fakes.now += timedelta(seconds=1)
    rerun(fakes)
    assert fakes.state() is JobState.STORED
    # A wait in pass 2 resumes at pass 2; pass 1 ran once.
    assert len(fakes.generated) == 3


def test_gemini_wait_logs_the_quota_message_on_one_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Google's quota message: two link sentences, then the metric line that shows a zero quota.
    detail = (
        "You exceeded your current quota, please check your plan and billing details. For more "
        "information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. "
        "To monitor your current usage, head to: https://ai.dev/usage?tab=rate-limit. \n"
        "* Quota exceeded for metric: generativelanguage.googleapis.com/"
        "generate_content_free_tier_input_token_count, limit: 0, model: gemini-3.8-flash\n"
        "Please retry in 36.4s."
    )
    fakes = make_fakes(
        tmp_path, [GeminiCallError(code=429, status="RESOURCE_EXHAUSTED", detail=detail)]
    )
    first_cycle(fakes)
    [record] = [r for r in caplog.records if r.name == jobs.__name__ and "gemini" in r.msg]
    assert record.levelno == logging.ERROR
    message = record.getMessage()
    assert "status=RESOURCE_EXHAUSTED reason=None: You exceeded" in message
    assert "limit: 0" in message
    assert "\n" not in message


def wait_again(fakes: Fakes, answers: Sequence[str | Exception]) -> timedelta:
    """Runs the job when it is due with the given answers; returns how long it now waits."""
    fakes.now = fakes.due_at()
    fakes.answers = list(answers)
    rerun(fakes)
    return fakes.due_at() - fakes.now


def test_repeated_gemini_waits_double_up_to_the_cap(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path, [BLOCKED])
    first_cycle(fakes)
    first = fakes.due_at() - fakes.now
    delays = [first, wait_again(fakes, [BLOCKED]), wait_again(fakes, [BLOCKED])]
    assert delays == [timedelta(seconds=s) for s in (600, 1200, 1800)]
    job = fakes.job()
    assert (job.state, job.attempts, job.waits) == (JobState.CHAIN_PENDING, 0, 3)


def test_server_delay_wins_over_the_backoff_and_still_counts(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path, [BLOCKED])
    first_cycle(fakes)
    assert wait_again(fakes, [UNAVAILABLE]) == timedelta(seconds=37)
    assert fakes.job().waits == 2


@pytest.mark.parametrize(
    ("answers", "state"),
    [
        ([pass1_response(), BLOCKED], JobState.EXTRACT_PENDING),
        (["not json", BLOCKED], JobState.CHAIN_PENDING),
    ],
    ids=["transition", "attempt"],
)
def test_transition_or_attempt_starts_the_backoff_again(
    tmp_path: Path, answers: list[str | Exception], state: JobState
) -> None:
    fakes = make_fakes(tmp_path, [BLOCKED])
    first_cycle(fakes)
    assert wait_again(fakes, [BLOCKED]) == timedelta(seconds=1200)
    assert wait_again(fakes, answers) == timedelta(seconds=600)
    job = fakes.job()
    assert (job.state, job.waits) == (state, 1)


def test_step_exception_keeps_the_wait_count(tmp_path: Path) -> None:
    # A retry delay unlike the backoff, so the two cannot be mistaken for each other.
    settings = dataclasses.replace(SETTINGS, retry_delay=timedelta(seconds=900))
    fakes = make_fakes(tmp_path, [BLOCKED])
    first_cycle(fakes, settings)
    fakes.now = fakes.due_at()
    fakes.answers = [STOP]
    loop.run_due(fakes.ports(), settings, threading.Event())
    assert fakes.due_at() - fakes.now == timedelta(seconds=900)
    assert fakes.job().waits == 1
    assert wait_again(fakes, [BLOCKED]) == timedelta(seconds=1200)


def test_step_start_is_counted_before_the_step_and_kept_by_an_exception(fakes: Fakes) -> None:
    fakes.answers = [STOP]
    first_cycle(fakes)
    assert fakes.step_starts_seen == [1]
    assert fakes.job().step_starts == 1

    fakes.answers = [STOP]
    fakes.now += timedelta(seconds=600)
    rerun(fakes)
    assert fakes.step_starts_seen == [1, 2]

    fakes.answers = list(STORED_ANSWERS)
    fakes.now += timedelta(seconds=600)
    rerun(fakes)
    # Pass 2 starts afresh after the pass-1 transition.
    assert fakes.step_starts_seen == [1, 2, 3, 1]
    assert fakes.job().step_starts == 0


def test_oversize_after_getfile_fails_the_job(fakes: Fakes) -> None:
    fakes.download_error = FileTooLarge("too big")
    first_cycle(fakes)
    assert fakes.state() is JobState.FAILED
    assert fakes.failure_reason() == "file_too_large"
    assert fakes.generated == []


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("telegram unavailable"),
        TelegramAPIError("getFile", 401, "Unauthorized"),
        TelegramRetryExhaustedError("getFile", 3),
    ],
    ids=["exception", "unauthorized", "retries-exhausted"],
)
def test_download_exception_keeps_the_job_received_without_an_attempt(
    fakes: Fakes, error: Exception
) -> None:
    fakes.download_error = error
    first_cycle(fakes)
    job = fakes.job()
    assert (job.state, job.attempts) == (JobState.RECEIVED, 0)
    assert fakes.due_at() == fakes.now + SETTINGS.retry_delay
    assert fakes.generated == [] and fakes.pipelines_opened == 0


UNAVAILABLE_FILE = FileUnavailable("getFile: HTTP 400: Bad Request: wrong file_id")


def test_unavailable_file_consumes_an_attempt_and_opens_no_pipeline(
    fakes: Fakes, caplog: pytest.LogCaptureFixture
) -> None:
    fakes.download_error = UNAVAILABLE_FILE
    first_cycle(fakes)
    job = fakes.job()
    assert (job.state, job.attempts, job.step_starts) == (JobState.RECEIVED, 1, 0)
    assert fakes.due_at() == fakes.now + SETTINGS.retry_delay
    assert fakes.pipelines_opened == 0
    assert all(record.exc_info is None for record in caplog.records)
    assert "failed in its step" not in caplog.text


def test_unavailable_file_fails_the_job_at_the_attempt_limit(fakes: Fakes) -> None:
    fakes.download_error = UNAVAILABLE_FILE
    first_cycle(fakes)
    for _ in range(2):
        fakes.now = fakes.due_at()
        rerun(fakes)
    assert fakes.state() is JobState.FAILED
    assert fakes.failure_reason() == "file_unavailable"
    assert len(fakes.downloads) == 3
    assert fakes.generated == [] and fakes.pipelines_opened == 0


def test_getfile_400_through_the_real_client_fails_the_job_at_the_limit(fakes: Fakes) -> None:
    getfile_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        getfile_calls.append(str(request.url))
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: wrong file_id"})

    client = TelegramClient(SecretStr("1:fake"), transport=httpx.MockTransport(handler))
    ports = dataclasses.replace(
        fakes.ports(),
        download=lambda file_id, size: download_file(client, file_id, size, MAX_FILE_BYTES),
    )
    loop.poll(FakeTelegram([[pdf_update(100, 3)]]), ports, SETTINGS)
    for _ in range(3):
        loop.run_due(ports, SETTINGS, threading.Event())
        fakes.now += SETTINGS.retry_delay
    assert fakes.state() is JobState.FAILED
    assert fakes.failure_reason() == "file_unavailable"
    assert len(getfile_calls) == 3 and all("/getFile" in url for url in getfile_calls)
    assert fakes.generated == [] and fakes.pipelines_opened == 0


def test_file_fetched_after_refusals_gets_every_gemini_attempt(fakes: Fakes) -> None:
    fakes.download_error = UNAVAILABLE_FILE
    first_cycle(fakes)
    fakes.now = fakes.due_at()
    rerun(fakes)
    fakes.download_error = None
    # Two wrong results would end the job if the refused downloads still counted.
    fakes.answers = ["not json", "not json", *STORED_ANSWERS]
    fakes.now = fakes.due_at()
    rerun(fakes)
    assert fakes.state() is JobState.STORED
    assert len(fakes.downloads) == 3


@pytest.mark.parametrize(
    ("due_in_s", "timeout"),
    [(7, 7), (6.2, 7), (0, 0), (-90, 0), (45, 30)],
    ids=["in-7s", "rounded-up", "due-now", "overdue", "beyond-timeout"],
)
def test_long_poll_ends_when_the_next_job_is_due(
    fakes: Fakes, due_in_s: float, timeout: int
) -> None:
    loop.poll(FakeTelegram([[pdf_update(100, 3)]]), fakes.ports(), SETTINGS)
    fakes.queue.postpone(1, fakes.now + timedelta(seconds=due_in_s), fakes.now)
    telegram = FakeTelegram([])
    loop.poll(telegram, fakes.ports(), SETTINGS)
    assert telegram.timeouts == [timeout]


def test_long_poll_is_full_with_no_waiting_job(fakes: Fakes) -> None:
    telegram = FakeTelegram([[pdf_update(100, 3)]])
    cycle(telegram, fakes)
    assert fakes.state() is JobState.STORED
    loop.poll(telegram, fakes.ports(), SETTINGS)
    # Empty queue, then only a finished job.
    assert telegram.timeouts == [30, 30]


@pytest.mark.parametrize(
    "update",
    [pdf_update(100, 3, sender=99999), pdf_update(100, 3, chat_type="group")],
    ids=["not-allowlisted", "group-chat"],
)
def test_filtered_update_makes_no_job_but_is_acknowledged(
    fakes: Fakes, update: dict[str, Any]
) -> None:
    telegram = FakeTelegram([[update]])
    cycle(telegram, fakes)
    assert fakes.queue._conn.execute("SELECT count(*) FROM jobs").fetchone() == (0,)
    assert fakes.queue.read_offset() == 101
    assert fakes.downloads == [] and fakes.telegram.calls == []


def with_message(**fields: Any) -> dict[str, Any]:
    update = pdf_update(100, 3)
    del update["message"]["document"]
    update["message"].update(fields)
    return update


PDF_DOC = {"file_id": "f3", "file_size": 16, "mime_type": "application/pdf"}


@pytest.mark.parametrize(
    "update",
    [
        with_message(text="hi"),
        with_message(sticker={"file_id": "s"}),
        with_message(document={**PDF_DOC, "mime_type": "application/zip"}),
        with_message(document={**PDF_DOC, "file_size": MAX_FILE_BYTES + 1}),
        with_message(document={k: v for k, v in PDF_DOC.items() if k != "file_size"}),
    ],
    ids=["text", "sticker", "other-mime", "over-20-mb", "unknown-size"],
)
def test_refused_content_gets_only_the_not_accepted_reaction(
    fakes: Fakes, update: dict[str, Any]
) -> None:
    cycle(FakeTelegram([[update]]), fakes)
    assert fakes.queue._conn.execute("SELECT count(*) FROM jobs").fetchone() == (0,)
    assert fakes.telegram.calls == [("reaction", ALLOWED, 3, "🙈")]
    # Sent only once the batch was acknowledged.
    assert fakes.telegram.seen == [(None, False, 101)]
    assert fakes.downloads == []


def test_failed_not_accepted_reaction_does_not_break_the_poll(
    fakes: Fakes, caplog: pytest.LogCaptureFixture
) -> None:
    fakes.telegram.fail = True
    batch = [with_message(text="hi"), pdf_update(101, 4)]
    loop.poll(FakeTelegram([batch]), fakes.ports(), SETTINGS)
    assert fakes.queue.read_offset() == 102
    assert fakes.state() is JobState.RECEIVED
    assert "message 3: reaction failed" in caplog.text


def test_redelivered_update_is_not_processed_twice(fakes: Fakes) -> None:
    first_cycle(fakes)
    first_cycle(fakes)
    assert len(fakes.written) == 1


def test_exception_keeps_the_job_and_retries_after_the_delay(
    fakes: Fakes, caplog: pytest.LogCaptureFixture
) -> None:
    fakes.answers = [RuntimeError("boom"), *STORED_ANSWERS]
    first_cycle(fakes)
    assert fakes.state() is JobState.CHAIN_PENDING
    assert fakes.job().attempts == 0
    assert "job 1 failed in its step" in caplog.text
    assert len(fakes.downloads) == 1

    fakes.now += timedelta(seconds=599)
    rerun(fakes)
    assert len(fakes.generated) == 1

    fakes.now += timedelta(seconds=1)
    rerun(fakes)
    assert fakes.state() is JobState.STORED
    # The file was saved before the failure, so the retry does not download it again.
    assert len(fakes.downloads) == 1


def test_restart_fetches_from_the_committed_offset_and_resumes_jobs(
    fakes: Fakes, tmp_path: Path
) -> None:
    fakes.answers = [STOP]
    first = FakeTelegram([[pdf_update(100, 3), pdf_update(101, 4, sender=99999)]])
    cycle(first, fakes)
    assert first.offsets == [None]

    again = restarted(fakes, tmp_path, STORED_ANSWERS)
    second = FakeTelegram([])
    cycle(second, again)
    assert second.offsets == [102]
    assert again.state() is JobState.STORED
    assert again.downloads == []


def test_version_1_queue_is_upgraded_and_its_job_runs_to_stored(tmp_path: Path) -> None:
    write_v1_queue(tmp_path / "queue.sqlite3", JobState.CHAIN_PENDING)
    fakes = make_fakes(tmp_path)
    fakes.files.save(fakes.files.path_for(12345, 1, "image/jpeg"), PDF_BYTES)
    telegram = FakeTelegram([])
    cycle(telegram, fakes)
    assert telegram.offsets == [101]
    assert fakes.state() is JobState.STORED
    assert fakes.queue.read_offset() == 101


def test_a_poll_failure_still_runs_due_jobs(fakes: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    loop.poll(FakeTelegram([[pdf_update(100, 3)]]), fakes.ports(), SETTINGS)
    monkeypatch.setattr(loop, "POLL_ERROR_BACKOFF_S", 0.0)
    stop = threading.Event()

    class DownThenStop:
        calls = 0

        def get_updates(
            self, *, offset: int | None, timeout: int, allowed_updates: Sequence[str] | None = None
        ) -> list[dict[str, Any]]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("telegram down")
            stop.set()
            return []

    loop.run(DownThenStop(), fakes.ports(), SETTINGS, stop)
    assert fakes.state() is JobState.STORED


def test_run_stops_and_survives_a_poll_failure(fakes: Fakes) -> None:
    stop = threading.Event()

    class Failing:
        calls = 0

        def get_updates(
            self, *, offset: int | None, timeout: int, allowed_updates: Sequence[str] | None = None
        ) -> list[dict[str, Any]]:
            self.calls += 1
            stop.set()
            raise RuntimeError("network")

    telegram = Failing()
    loop.run(telegram, fakes.ports(), SETTINGS, stop)
    assert telegram.calls == 1


ITEMS_MISMATCH = response(payments=[{"text": "PLAĆANJE MASTERCARD", "amount": "2,50"}])


@pytest.mark.parametrize(
    ("attempt", "reason"),
    [
        ([pass1_response(), ITEMS_MISMATCH], FailureReason.ITEMS_SETTLEMENT_MISMATCH),
        ([pass1_response(), response(total="2,99")], FailureReason.TOTAL_SETTLEMENT_MISMATCH),
        (["not json"], FailureReason.NO_VALID_RESULT),
    ],
    ids=["items-mismatch", "total-mismatch", "no-valid-result"],
)
def test_failure_sends_the_admin_the_file_before_it_is_deleted(
    tmp_path: Path, attempt: list[str], reason: FailureReason
) -> None:
    fakes = make_fakes(tmp_path, attempt * SETTINGS.max_attempts)
    first_cycle(fakes)
    assert (fakes.state(), fakes.failure_reason()) == (JobState.FAILED, reason)
    admin = f"{TEXTS.admin_messages[reason]}\nAna\n#1"
    assert fakes.telegram.calls == [
        ("reaction", ALLOWED, 3, "👎"),
        ("message", ALLOWED, TEXTS.sender_messages[reason], 3),
        ("document", ADMIN, fakes.file().name, admin),
    ]
    assert fakes.telegram.seen == [(JobState.FAILED, True, 101)] * 3
    assert not fakes.file().exists()


def test_oversize_after_getfile_tells_both_without_a_copy(fakes: Fakes) -> None:
    fakes.download_error = FileTooLarge("too big")
    first_cycle(fakes)
    reason = FailureReason.FILE_TOO_LARGE
    assert fakes.telegram.calls == [
        ("reaction", ALLOWED, 3, "👎"),
        ("message", ALLOWED, TEXTS.sender_messages[reason], 3),
        ("message", ADMIN, f"{TEXTS.admin_messages[reason]}\nAna\n#1", None),
    ]
    assert fakes.telegram.seen == [(JobState.FAILED, False, 101)] * 3


def test_unavailable_download_tells_both_without_a_copy(fakes: Fakes) -> None:
    fakes.download_error = UNAVAILABLE_FILE
    first_cycle(fakes)
    for _ in range(2):
        fakes.now = fakes.due_at()
        rerun(fakes)
    reason = FailureReason.FILE_UNAVAILABLE
    assert fakes.telegram.calls == [
        ("reaction", ALLOWED, 3, "👎"),
        ("message", ALLOWED, TEXTS.sender_messages[reason], 3),
        ("message", ADMIN, f"{TEXTS.admin_messages[reason]}\nAna\n#1", None),
    ]
    assert fakes.telegram.seen == [(JobState.FAILED, False, 101)] * 3


def test_gemini_unavailable_shows_in_progress_once_per_stretch(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path, [UNAVAILABLE])
    first_cycle(fakes)
    assert fakes.telegram.calls == [("reaction", ALLOWED, 3, "👀")]
    # The wait was recorded before the reaction went out.
    assert fakes.telegram.seen == [(JobState.CHAIN_PENDING, True, 101)]
    assert fakes.job().waits == 1
    wait_again(fakes, [UNAVAILABLE])
    assert fakes.telegram.calls == [("reaction", ALLOWED, 3, "👀")]
    wait_again(fakes, STORED_ANSWERS)
    assert fakes.telegram.calls[-1] == ("reaction", ALLOWED, 3, "👍")


def test_blocked_gemini_sends_no_reaction(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path, [BLOCKED])
    first_cycle(fakes)
    wait_again(fakes, [UNAVAILABLE])
    assert fakes.state() is JobState.CHAIN_PENDING
    # The unavailable wait came second in its stretch, so it is not announced either.
    assert [c for c in fakes.telegram.calls if c[0] == "reaction"] == []
    assert len(fakes.telegram.calls) == 1
    assert fakes.telegram.calls[0][1] == ADMIN
    assert "gemini_config" in fakes.telegram.calls[0][2]


def stored(fakes: Fakes) -> None:
    pass


def duplicate(fakes: Fakes) -> None:
    fakes.write_result = WriteKind.DUPLICATE


def unsupported(fakes: Fakes) -> None:
    fakes.answers = [pass1_response(chain="other")] * 2


def no_valid_result(fakes: Fakes) -> None:
    fakes.answers = ["not json"] * 3


def too_large(fakes: Fakes) -> None:
    fakes.download_error = FileTooLarge("too big")


@pytest.mark.parametrize("arrange", [stored, duplicate, unsupported, no_valid_result, too_large])
def test_every_send_failing_leaves_the_same_final_state(
    tmp_path: Path, arrange: Callable[[Fakes], None]
) -> None:
    outcomes = []
    for fail in (False, True):
        fakes = make_fakes(tmp_path / str(fail))
        arrange(fakes)
        fakes.telegram.fail = fail
        first_cycle(fakes)
        job = fakes.job()
        outcomes.append((job.state, fakes.failure_reason(), job.receipt_id is None))
        assert fakes.telegram.calls
        assert not fakes.file().exists()
        fakes.queue.close()
    assert outcomes[0] == outcomes[1]


PDF = "application/pdf"


def queued(fakes: Fakes, message_id: int) -> Path:
    item = Accepted(ALLOWED, message_id, "Ana", f"f{message_id}", FileKind.DOCUMENT, PDF, 16)
    fakes.queue.enqueue([item], message_id + 100, fakes.now)
    return fakes.files.path_for(ALLOWED, message_id, PDF)


def test_sweep_deletes_files_of_finished_jobs_only(fakes: Fakes) -> None:
    finished, finished_gone, waiting = (queued(fakes, n) for n in (3, 4, 5))
    for path in (finished, waiting):
        fakes.files.save(path, PDF_BYTES)
    fakes.queue.finish(1, JobState.STORED, fakes.now)
    fakes.queue.finish(2, JobState.FAILED, fakes.now, failure_reason=FailureReason.NO_VALID_RESULT)
    jobs.sweep_files(fakes.ports())
    assert not finished.exists() and not finished_gone.exists()
    assert waiting.read_bytes() == PDF_BYTES
    assert fakes.telegram.calls == []


def test_two_blocked_waits_give_one_alert_and_one_recovery(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path, [BLOCKED])
    first_cycle(fakes)
    assert fakes.state() is JobState.CHAIN_PENDING
    assert fakes.alerts.is_active(AlertKind.GEMINI_CONFIG)

    admin_alerts = [c for c in fakes.telegram.calls if c[0] == "message" and c[1] == ADMIN]
    assert len(admin_alerts) == 1
    assert admin_alerts[0][2] == (
        f"{TEXTS.alerts[AlertKind.GEMINI_CONFIG]}\n"
        "gemini_config\n"
        "code=404 status=NOT_FOUND reason=None"
    )

    wait_again(fakes, [BLOCKED])
    assert fakes.state() is JobState.CHAIN_PENDING
    admin_alerts = [c for c in fakes.telegram.calls if c[0] == "message" and c[1] == ADMIN]
    assert len(admin_alerts) == 1

    wait_again(fakes, STORED_ANSWERS)
    assert fakes.state() is JobState.STORED
    assert not fakes.alerts.is_active(AlertKind.GEMINI_CONFIG)

    admin_calls = [c for c in fakes.telegram.calls if c[0] == "message" and c[1] == ADMIN]
    assert len(admin_calls) == 2
    assert admin_calls[1][2] == (f"{TEXTS.recoveries[AlertKind.GEMINI_CONFIG]}\ngemini_config")


def test_two_failed_polls_then_one_good_poll_give_one_alert_and_one_recovery(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop, "POLL_ERROR_BACKOFF_S", 0.0)
    stop = threading.Event()

    class PollSequence:
        calls = 0

        def get_updates(
            self, *, offset: int | None, timeout: int, allowed_updates: Sequence[str] | None = None
        ) -> list[dict[str, Any]]:
            self.calls += 1
            if self.calls in (1, 2):
                raise TelegramRetryExhaustedError("getUpdates", 3)
            stop.set()
            return []

    loop.run(PollSequence(), fakes.ports(), SETTINGS, stop)
    admin_calls = [c for c in fakes.telegram.calls if c[0] == "message" and c[1] == ADMIN]
    assert len(admin_calls) == 2
    assert admin_calls[0][2] == (
        f"{TEXTS.alerts[AlertKind.TELEGRAM_UNREACHABLE]}\n"
        "telegram_unreachable\n"
        "TelegramRetryExhaustedError getUpdates"
    )
    assert admin_calls[1][2] == (
        f"{TEXTS.recoveries[AlertKind.TELEGRAM_UNREACHABLE]}\ntelegram_unreachable"
    )


def test_non_telegram_poll_error_gives_no_alert(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop, "POLL_ERROR_BACKOFF_S", 0.0)
    stop = threading.Event()

    class Failing:
        calls = 0

        def get_updates(
            self, *, offset: int | None, timeout: int, allowed_updates: Sequence[str] | None = None
        ) -> list[dict[str, Any]]:
            self.calls += 1
            stop.set()
            raise RuntimeError("something unexpected")

    loop.run(Failing(), fakes.ports(), SETTINGS, stop)
    assert not fakes.alerts.is_active(AlertKind.TELEGRAM_UNREACHABLE)
    assert fakes.telegram.calls == []


def test_failed_alert_send_leaves_job_state_identical(tmp_path: Path) -> None:
    working = make_fakes(tmp_path / "working", [BLOCKED])
    first_cycle(working)
    working_job = working.job()

    failing = make_fakes(tmp_path / "failing", [BLOCKED])
    failing.telegram.fail = True
    first_cycle(failing)
    failing_job = failing.job()

    assert failing_job.state == working_job.state
    assert failing_job.waits == working_job.waits
    assert failing.alerts.is_active(AlertKind.GEMINI_CONFIG)


def chain_reference_messages(fakes: Fakes) -> list[str]:
    return [c[2] for c in fakes.telegram.calls if c[1] == ADMIN and "\nchain_reference" in c[2]]


def test_withdrawn_plugin_alerts_once_and_leaves_the_job_path_unchanged(tmp_path: Path) -> None:
    # Spar withdrawn leaves it out of the pass-1 schema, so the model can only answer `other`.
    other = pass1_response(chain="other")
    fakes = make_fakes(tmp_path, [other, other])
    fakes.reference = SPAR_WITHDRAWN
    jobs.check_reference(fakes.ports())
    first_cycle(fakes)
    # Two reference reads, one alert; the job takes the plain unsupported path.
    assert fakes.state() is JobState.UNSUPPORTED_CHAIN
    assert len(fakes.generated) == 2
    assert chain_reference_messages(fakes) == [
        f"{TEXTS.alerts[AlertKind.CHAIN_REFERENCE]}\nchain_reference\ninactive plug-in: spar"
    ]

    fakes.reference = SPAR_ONLY
    jobs.check_reference(fakes.ports())
    assert chain_reference_messages(fakes)[1:] == [
        f"{TEXTS.recoveries[AlertKind.CHAIN_REFERENCE]}\nchain_reference"
    ]


def test_startup_reference_check_with_postgres_down_only_logs(
    fakes: Fakes, caplog: pytest.LogCaptureFixture
) -> None:
    def postgres_down() -> contextlib.AbstractContextManager[Ports]:
        raise ConnectionError("connection refused")

    jobs.check_reference(dataclasses.replace(fakes.ports(), open_pipeline=postgres_down))
    assert "startup reference check failed: ConnectionError" in caplog.text
    assert fakes.telegram.calls == []


def test_failing_alert_sends_do_not_stop_the_loop(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop, "POLL_ERROR_BACKOFF_S", 0.0)
    fakes.telegram.fail = True
    stop = threading.Event()
    polls: list[int] = []

    class PollSequence:
        def get_updates(
            self, *, offset: int | None, timeout: int, allowed_updates: Sequence[str] | None = None
        ) -> list[dict[str, Any]]:
            polls.append(timeout)
            if len(polls) < 3:
                raise TelegramAPIError("getUpdates", 401, "Unauthorized")
            stop.set()
            return []

    loop.run(PollSequence(), fakes.ports(), SETTINGS, stop)
    assert len(polls) == 3
    assert not fakes.alerts.is_active(AlertKind.TELEGRAM_UNREACHABLE)
