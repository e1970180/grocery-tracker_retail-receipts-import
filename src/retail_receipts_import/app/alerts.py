"""Operational alerts sent to the admin once on fault and once on recovery."""

import functools
import logging
from collections.abc import Callable

from pydantic import BaseModel

from retail_receipts_import.adapters.postgres.chains import (
    ChainReference,
    ChainReferenceError,
)
from retail_receipts_import.app.notify import Notifier
from retail_receipts_import.app.pipeline import Generate
from retail_receipts_import.app.texts import Texts
from retail_receipts_import.domain.chains.registry import PLUGINS
from retail_receipts_import.domain.jobs import JobState
from retail_receipts_import.domain.outcomes import AlertKind

log = logging.getLogger(__name__)


def _alert_key(kind: AlertKind, state: JobState | str | None = None) -> str:
    if kind is AlertKind.INTERNAL and state is not None:
        state_str = state.value if isinstance(state, JobState) else str(state)
        return f"internal:{state_str}"
    return str(kind)


class Alerts:
    def __init__(self, notifier: Notifier, texts: Texts) -> None:
        self._notifier = notifier
        self._texts = texts
        self._active: set[str] = set()

    def is_active(self, kind: AlertKind, state: JobState | str | None = None) -> bool:
        return _alert_key(kind, state) in self._active

    def start(self, kind: AlertKind, reason: str, state: JobState | str | None = None) -> None:
        key = _alert_key(kind, state)
        if key in self._active:
            return
        self._active.add(key)
        text = f"{self._texts.alerts[kind]}\n{key}\n{reason}"
        self._notifier.admin(f"alert {key}", text)

    def recover(self, kind: AlertKind, state: JobState | str | None = None) -> None:
        key = _alert_key(kind, state)
        if key not in self._active:
            return
        self._active.remove(key)
        text = f"{self._texts.recoveries[kind]}\n{key}"
        self._notifier.admin(f"alert {key}", text)

    def check_reference(self, reference: ChainReference) -> ChainReference:
        faults: list[str] = []
        active_ids = {c.chain_id for c in reference.chains}
        inactive_ids = set(reference.inactive_ids)

        for plugin_id in sorted(PLUGINS.keys()):
            if plugin_id in inactive_ids:
                faults.append(f"inactive plug-in: {plugin_id}")
            elif plugin_id not in active_ids:
                faults.append(f"missing plug-in: {plugin_id}")

        if reference.rejected:
            rejected_strs = [f"{r.chain_id or 'null'}: {r.reason}" for r in reference.rejected]
            faults.append(f"rejected rows: {', '.join(rejected_strs)}")

        if faults:
            self.start(AlertKind.CHAIN_REFERENCE, "; ".join(faults))
        else:
            self.recover(AlertKind.CHAIN_REFERENCE)
        return reference

    def watch_generate(self, generate: Generate) -> Generate:
        @functools.wraps(generate)
        def wrapped(data: bytes, mime: str, prompt: str, schema: type[BaseModel]) -> str:
            result = generate(data, mime, prompt, schema)
            self.recover(AlertKind.GEMINI_CONFIG)
            return result

        return wrapped

    def read_checked(self, read: Callable[[], ChainReference]) -> ChainReference:
        try:
            reference = read()
        except ChainReferenceError as exc:
            self.start(AlertKind.CHAIN_REFERENCE, str(exc))
            raise
        return self.check_reference(reference)
