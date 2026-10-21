---
type: review
lens: adversary
target: ../architecture-receipts-import.md
created: '2026-10-21'
---

# Adversarial review: architecture spine receipts-import

## Verdict

The spine is sound in its owner decisions: the single loop, SQLite queue, offset-in-transaction, own-write recognition and atomic write hold. But the chain-detection vocabulary, the per-job error boundary, the persisted receipt payload, the Gemini error classes and the intake download step are loose enough that two stories can each obey every AD and still ship a service that misfiles receipts or stalls intake.

Method: for each hole, two units one level down (stories built by different agents) are constructed. Each obeys the ADs to the letter, and together they still produce a defect. Every hole ends with paste-ready AD text. Holes this deployment cannot reach (about 2 receipts a day, one process, one thread) are listed under "Rejected at this scale".

Severity: **high** means a receipt can be lost, stored wrong, stored twice, or intake stops. **medium** means a wrong user-visible outcome or cost waste. **low** means hygiene.

---

## H1 — The pass-1 vocabulary cannot say "other chain" (high)

**Unit A, the Gemini adapter story (AD-4, AD-6).** By AD-6, "that registry *is* the supported-chain list and the pass-1 vocabulary". The pass-1 response schema is therefore `chain: enum["kaufland","lidl","dm","mueller","spar"]`. Under constrained decoding with temperature 0, the model must pick one of the five values.

**Unit B, the jobs story (AD-3, AD-7).** It implements `chain_pending → unsupported_chain: other chain` and `chain_pending → failed` on an "unreadable chain" (AD-7 `invalid`).

**Clash:**
- A Konzum or Plodine receipt can never produce "other". It gets a supported chain id, most likely the nearest look-alike, and goes through that chain's pass 2. If the totals happen to balance, it is **stored under the wrong chain**, with a dedup key in the wrong namespace. Otherwise it burns 3 attempts and lands in `failed`, with a "resend a better photo" message.
- The `unsupported_chain` row of the outcome matrix becomes unreachable. The "unreadable chain" case is equally unreachable.
- The admin's "chain unsupported" message also has nothing to name, because pass 1 returns only an id.

Secondary: chain slugs are part of the dedup key (AD-8). A later rename, for example `mueller` to `muller`, silently splits the key space. Nothing forbids that rename.

**Proposed rule, tightening AD-6:**

> **AD-6 (tightened)**
> **Rule (added):** The pass-1 vocabulary is the registry ids plus two sentinels, `other` and `unreadable`. The sentinels are defined in `domain`, not in the registry, so they are never chains. The pass-1 schema also returns `printed_store_name` as free text. It is used only in the admin message and logs, never for routing. `other` maps to `unsupported_chain`, and `unreadable` maps to AD-7 `invalid`. A chain id, once released, is never renamed or reused, because it is part of the dedup key. Each chain plug-in ships at least one pass-1 fixture. The registry test includes a non-supported-chain fixture that must yield `other`.

---

## H2 — No per-job error boundary: one poison job stops intake (high)

**Unit A, the postgres writer story (AD-3, AD-10).** It follows AD-3 literally ("While PostgreSQL is unreachable the job waits there"). It catches connection errors as a wait and lets every other `psycopg.Error` propagate. Examples:
- `permission denied for type` or `for sequence`, which is exactly the addendum's trigger-grant lesson;
- `numeric field overflow`;
- a check violation;
- a constraint-name mismatch.

**Unit B, the loop story (AD-14).** It processes "every due job sequentially" and has no catch, because no AD says what an unclassified error is.

**The chain of effects:**
1. The exception kills the process.
2. Compose restarts it.
3. AD-3 resumes the job from its persisted state, so the same job runs first and kills the process again.

The loop is the intake (AD-14), so `getUpdates` stops too. New receipts are not lost at first, because the offset is not acknowledged. But after Telegram's roughly 24 h hold, the unfetched updates expire. That violates the spec's "no accepted receipt is lost". The admin may get only one alert, or none, because AD-13 keeps alert state in memory and the process may die before the send.

The same path is open from:
- a bug in one chain's normalization code (`KeyError`);
- Pillow failing on an image type it cannot open (see H5);
- a `write_pending` payload that no longer validates after a deploy (see H3);
- a missing local file.

A third story could instead map "anything else" to `failed`. The sender would then get a failure message for a server-side grant mistake that a resend cannot fix, and the outcome matrix says the sender sees "—" for internal errors. Both readings obey the ADs. They differ in visible behavior.

**Proposed rule, new AD:**

> **AD-16 — Per-job error boundary**
> - **Binds:** CAP-9, CAP-10, all
> - **Prevents:** one job's unexpected error stopping the loop, or two units choosing wait vs failure for the same error.
> - **Rule:** The loop wraps each job step in one boundary. Errors fall into exactly these classes:
>   - Gemini results go through AD-7.
>   - PostgreSQL connection-class errors are a wait: SQLSTATE class `08`, `57P01`–`57P03`, connect timeout, and a connection lost during `COMMIT`. AD-9 resolves the in-doubt commit.
>   - Every other exception is **internal**. The job stays in its current state, its `next_try_at` is pushed out by capped backoff, no attempt is consumed, the sender is not told, and AD-13 raises the alert kind `internal:<state>` with the exception type, redacted. The loop then continues with the next job and the next `getUpdates`.
>
>   An internal error never moves a job to `failed`, because recovery is a deploy fix, not a resend. The boundary is in `app/`, and adapters never decide the class.
>   The jobs module records each job step's start in its own transaction before the call. A job whose step has started 3 times without a recorded result is treated as internal. This covers a crash the boundary cannot catch, such as OOM or a segfault.

---

## H3 — The normalized receipt in the job row has no fixed shape (medium-high)

**Unit A, the domain normalization story (AD-5, AD-8).** It calls the shared Zagreb-to-`timestamptz` function. It returns a pydantic `NormalizedReceipt` with `purchase_at: datetime` (aware, UTC) and `Decimal` amounts. The jobs story then stores it in the `write_pending` row with `json.dumps(model.model_dump(), default=str)`.

**Unit B, the postgres writer story (AD-8, AD-10).** By AD-8, "the printed Europe/Zagreb wall time is converted to `timestamptz` in one shared function". The writer reads that as "the writer applies the conversion". It loads the job payload, sees a datetime, treats it as wall time and converts again. The result is shifted by 1–2 h.

Each unit used "the one shared function", and the shift happens anyway:
- **Dedup:** a resend that was extracted before a deploy and one extracted after it get different keys. The purchase is stored twice.
- **Money:** `json.dumps` with `default=float` or with numbers loses `Decimal`. Pydantic JSON mode emits strings. Two units can disagree on the format.
- **Deploys:** a job waiting in `write_pending` through a PostgreSQL outage, while a deploy changes the model, fails validation on resume. That becomes a poison job (H2).

The same split exists one step earlier. One chain plug-in declares printed amounts as JSON `number` in its Gemini response schema, and another declares them as `string`. The `number` path goes through float before `Decimal`, which breaks the "never float" convention without any code saying `float`.

**Proposed rule, new AD:**

> **AD-17 — One normalized receipt type and its persisted form**
> - **Binds:** CAP-3, CAP-4, CAP-6, CAP-7, CAP-9
> - **Prevents:** domain, queue and writer disagreeing on time, money or version of the receipt that waits in `write_pending`.
> - **Rule:**
>   - `domain/model` defines one pydantic `NormalizedReceipt`. It is the only type the domain hands to `app` and the only type the postgres writer accepts.
>   - `purchase_at` is an aware UTC datetime. The AD-8 conversion is applied exactly once, inside domain normalization, and adapters never convert time.
>   - The job row stores it only through `model_dump_json()` and `model_validate_json()`. Money is serialized as decimal strings.
>   - The row also stores `payload_version`, an integer bumped whenever the model changes. On resume, a version mismatch or a validation error moves the job back to `extract_pending` without consuming an attempt. That costs one Gemini call.
>   - `receipt_id` (UUIDv7) is assigned when the job enters `write_pending` and lives in the payload, so retries reuse it.
>   - Every Gemini response schema carries printed money as `string`, exactly as printed. Only domain code parses it into `Decimal`.

---

## H4 — Gemini errors that fit neither AD-7 class (medium)

**Unit A, the Gemini adapter and classifier story (AD-7).** The text lists `unavailable` as 429, 5xx, network and timeout, and `invalid` as schema failure, unreadable chain or date, or a mismatch. Auth, permission, quota-project and model-not-found errors are in neither list. The author picks "otherwise `invalid`", the safe-looking default for "a response that fails".

**Unit B, the alerts story (AD-13).** It expects "Gemini auth failure" as an alert kind that starts and recovers. So it treats auth failure as a waiting condition.

**Clash:** when the key is rotated or revoked, or `gemini-3.6-flash` is retired and returns not-found, Unit A burns 3 attempts per job within seconds. Every waiting receipt goes to `failed`, and each sender is told to resend a better photo. The real fix is a config change. Unit B's alert fires too, but the receipts are already failed. A resend of all of them is the only recovery.

A related gap: an HTTP 200 with no usable candidate, for example a safety or recitation finish reason or empty content, is not listed either. Classifying it as `invalid` is reasonable, but it should be written down.

Classification must key on the error reason, not only the status code. Google APIs can report an invalid API key as a 400 with a reason field. **Confirm this against the `google-genai` 2.32.0 error types** when the adapter is built, and record a fixture.

**Proposed rule, tightening AD-7:**

> **AD-7 (tightened)**
> **Rule (added):** A fourth class, `blocked`, covers configuration-side errors: authentication or permission failure, an invalid API key, model not found, and quota or billing disabled. They are identified from the SDK error's reason or status, not from the HTTP code alone. `blocked` behaves like `unavailable`: no attempt is consumed, the job waits with capped backoff, and the in-progress reaction is set once. It also raises the AD-13 alert kind `gemini_config` with the redacted reason. Any other 4xx tied to this file, for example an unprocessable image or PDF, is `invalid`. An HTTP 200 without a usable candidate is `invalid`. Each class has one recorded fixture.

---

## H5 — The intake download sits inside the offset transaction (medium)

Evidence in the spine:
- The state diagram reads `[*] --> received: file downloaded and saved`. The download therefore happens before the job row exists.
- By AD-2, the offset commits in the same transaction that inserts the batch's jobs, so the download sits inside that window.
- `received --> chain_pending` has no action, so `received` is an empty state.

**Unit A, the intake story (AD-2, AD-15).** It downloads each file with the pack's retry rules (5 attempts), then inserts the jobs and the offset. When a download finally fails, for example on a Telegram file-server 5xx or a timeout on a 20 MB PDF, the unit has only two choices. It can advance the offset, which drops a receipt silently with no reaction. Or it can hold the offset, which blocks the batch and every receipt after it.

**Unit B, the jobs story (AD-3).** It sees `received` as a no-op and transitions it immediately.

Both choices obey the ADs. The first loses an accepted receipt, and the second stalls intake.

Two related gaps:
- **Accepted MIME set.** The intake unit accepts any `image/*` document, by CAP-1's "image". The preprocessing unit opens it with Pillow for the EXIF transpose. HEIC (common from iPhones sent as a file), TIFF and GIF fail to open. That makes an internal error, or a poison job under H2. Nothing defines the accepted MIME types in one place.
- **Over-limit files.** The outcome matrix has no row for a file over 20 MB.

**Proposed rule, tightening AD-2 and AD-3:**

> **AD-2 / AD-3 (tightened)**
> **Rule (added):**
> - Intake inserts the job as `received` with the Telegram `file_id`, MIME type, size and source reference. No download happens before the offset commit.
> - Downloading is the job step `received → chain_pending`. Telegram unavailability during it is a wait, like AD-7 `unavailable`, and AD-16 handles everything else.
> - The local file path is deterministic from the source reference (`<chat_id>_<message_id>.<ext>`), so a repeated download overwrites instead of duplicating.
> - One list in `domain` defines the accepted content types. The list is JPEG, PNG, WebP and PDF, plus HEIC only if preprocessing can open it. The gate and preprocessing both use that list.
> - Anything else, including a file whose size is unconfirmed or over 20 MB, is unsupported content and gets the "not accepted" reaction.

---

## Further holes (medium and low)

### H6 — AD-9 covers only the dedup conflict, not the source-reference conflict (medium)

The postgres writer story inserts `receipts` with two unique constraints: the dedup key (AD-8) and the source reference (AD-9). It handles `UniqueViolation` by checking whether the constraint name equals the dedup constraint. After a crash between AD-11 steps 1 and 2, the re-insert violates **both** constraints, and PostgreSQL reports whichever index it checks first. If that is the source-reference constraint, the writer sees a non-dedup violation and treats it as internal. Under H2 the job then never resolves. The jobs story assumed AD-9 handled the case.

> **AD-9 (tightened)**
> **Rule (added):** The writer checks before inserting, in the same transaction. If a row with this source reference exists, the result is `stored` (own write). Otherwise, if a row with this dedup key exists, the result is `duplicate`. Otherwise it inserts. A unique violation on insert re-runs the same two checks. The writer returns a closed result of `stored`, `duplicate` or `own_write`. The jobs module never inspects constraint names.

### H7 — The dedup timestamp field is not fixed per chain, so a PDF and a photo get different keys (medium)

Scenario: the same purchase arrives as a Lidl Plus app PDF and as a photo of the paper receipt. One printed time is the fiscal issue time on the JIR/ZKI line, and another is the transaction or terminal time. They can differ by seconds, and one format may print no seconds at all. Each chain plug-in author picks "the purchase time" independently. The two files then produce two keys, and the purchase is **stored twice**. CAP-6 names "a different photo of the same paper", and the PDF case is the same class of risk.

> **AD-8 (tightened)**
> **Rule (added):**
> - Each chain plug-in declares which printed field is the purchase timestamp. It is the fiscalized issue time wherever the receipt prints it. For Kaufland that is the fiscal line's time, never the bank-terminal date.
> - A source without seconds is `invalid` for pass 2, never padded with `:00`.
> - Each plug-in that accepts both forms ships a fixture pair, paper photo and digital PDF of the same purchase, and asserts equal dedup keys.

### H8 — A hung connect or call blocks the single loop (medium)

When the PostgreSQL host is down rather than refusing connections, a psycopg connect with no `connect_timeout` waits on OS TCP retries, about 2 min on Linux, **per job per try**. The google-genai client also has no explicit timeout set by any AD. In one thread this stalls Telegram polling and every other due job. The AD-14 shortened poll timeout does not help, because the loop never gets back to it. The project's Known pitfalls already flag the same issue for httpx.

> **AD-14 (tightened)**
> **Rule (added):** Every adapter call has an explicit timeout from config: the PostgreSQL `connect_timeout` and `statement_timeout`, a Gemini request timeout, and the Telegram timeouts from the pack. When a PostgreSQL connect fails, the loop skips the other `write_pending` jobs for that iteration and does not probe once per job.

### H9 — Texts-file keys and failure reasons are open sets (medium)

The notify story looks up `success` and `duplicate`. The platform-baseline story wrote `messages.toml` with `stored` and `already_stored`. Both obey "looked up by outcome key". The failure message must "explain the problem", but no AD says whether the reason is a code that the texts file translates into Russian, or the English exception text shown to a family member.

> **Config convention (tightened):** `domain/outcomes` defines two closed enums. One is the outcome keys: `stored`, `duplicate`, `unsupported_chain`, `failed`, `in_progress` and `not_accepted`. The other is the failure reason codes: `schema_invalid`, `chain_unreadable`, `date_unreadable`, `totals_mismatch` and `no_candidate`. It also defines the alert kinds: `postgres_unreachable`, `gemini_unavailable`, `gemini_config` and `internal:<state>`. The texts file holds exactly one entry per key and code, each with a reaction where applicable. Startup validation fails if any is missing. Users never see exception text.

### H10 — Notify and jobs both want to write job columns (low)

AD-3 says only the jobs module changes a job's *state*. AD-7's "in-progress reaction once" needs a persisted flag, or it is re-sent after every restart. That is harmless for a reaction but unclear for ownership. The attempt count, `next_try_at` and the last reason are also job columns. A notify story could set `in_progress_sent` itself.

> **AD-3 (tightened):** Every job column, not only `state`, is written only by the jobs module. Notify, the classifier and adapters return values, and jobs persists them.

### H11 — Crash between AD-11 steps 2 and 4 orphans the local file (low)

A crash after the SQLite final mark, or during the up-to-5-attempt Telegram sends, leaves the job final and the local file on the volume forever. The spec allows the file only "until the receipt reaches a final outcome". The same orphan appears when the intake crashes after saving a file and before the offset commit, under today's ordering.

> **AD-11 (tightened):** At startup, delete every local file whose job is final or which has no job. With deterministic paths (H5), a repeated download is idempotent.

That notifications are lost after a crash is a recorded owner decision and is not reopened as a hole. See the decision card below.

### H12 — Alert recursion when Telegram itself is down (low)

The notify story raises an AD-13 alert when a send fails after 5 attempts. The alert is sent through Telegram, fails, and raises an alert again. Nothing forbids that loop.

> **AD-13 (tightened):** A Telegram send failure is logged only and never raises an alert. A failure to send an alert never raises another alert.

### H13 — Feed gaps (low)

A rolled-back AD-10 transaction consumes an identity value, so `seq` has gaps. A Resolver that is strict about `last + 1` stalls.

> **AD-12 (tightened):** The contract states that `seq` is strictly increasing and may have gaps, and that the Resolver reads `seq > cursor`.

### H14 — Spec drift on the Telegram pack (low)

The spec constraint still says the pack is "requirements only, never imported code". AD-15 adopts it as code, an owner override recorded in the memlog. A story agent that reads the spec, which calls itself the canonical contract, can refuse to copy the pack. Update the spec constraint before inception.

---

## Scenario walk

| Scenario | Result | Notes |
| --- | --- | --- |
| Crash during intake, before the offset commit | Holds; orphan file | Updates are re-fetched (AD-2). Today a re-download can leave a second file (H5, H11). |
| Crash in `chain_pending` or `extract_pending` mid-call | Holds | No result is persisted, the pass re-runs, and no attempt is consumed. A crash loop on the same job needs the start counter from AD-16. |
| AD-11 step 1: crash before the PostgreSQL commit | Holds | The transaction rolls back (AD-10), and `write_pending` retries from the stored payload. |
| AD-11 between steps 1 and 2: committed, SQLite not marked | Holds with H6 | AD-9 resolves to `stored`, but only if the writer checks the source reference regardless of which constraint fires. |
| AD-11 between steps 2 and 3, or during 3 | Owner-accepted loss; orphan file | The notification is never sent (owner decision), and the file is orphaned (H11). |
| AD-11 between steps 3 and 4 | Orphan file | H11. |
| PostgreSQL down mid-job | Holds with H8 | Wait in `write_pending`, Gemini is not re-called, and one alert is raised. A hung connect blocks the loop without timeouts. |
| Connection lost during `COMMIT` | Holds | AD-9 resolves the in-doubt commit on retry. |
| PostgreSQL up but a grant is missing | **Hole** | H2: poison job, then intake stops. |
| Gemini down across a restart | Holds | The state is persisted, and the backoff restarts from zero, which is harmless. The in-progress reaction may be re-sent, which is harmless (H10). The alert may re-fire once, which AD-13 accepts. |
| Gemini key revoked or model retired | **Hole** | H4: mass false `failed`. |
| Telegram down when notifying | Holds with H12 | Logged after 5 attempts, and the outcome is unchanged. Alerts must not recurse. |
| Telegram file server fails during download | **Hole** | H5. |
| Same paper sent twice before the first finishes | Holds | AD-14 processes the jobs in order, and AD-8 makes the later writer `duplicate`. If job 1 is in backoff and job 2 is stored first, job 1's sender sees the duplicate reaction on their first send. That is acceptable: one row, and the matrix is honored. |
| Same paper, OCR misreads the seconds on one copy | Residual | Two keys, so two rows. The consistency check cannot catch it. That is the inherent limit of the owner's key. H7 narrows it. A "possible duplicate" admin hint (same chain, same total, within minutes) is optional and not proposed. |
| PDF vs photo of the same receipt | **Hole** | H7 for the key field. A PDF skips Pillow, so the MIME list from H5 covers the preprocessing difference. |
| Unsupported chain | **Hole** | H1. |

## Rejected at this scale

- **DST fall-back ambiguity** (a Zagreb wall time that occurs twice on the last Sunday of October). The stores are closed at 02:00–03:00.
- **Races on dedup, offset or job rows.** AD-14 allows one process and one thread, and nothing else writes the queue.
- **Feed `seq` assigned at insert, not at commit.** There is a single sequential writer, so the insert order is the commit order.
- **Decompression bombs beyond the pixel cap and the 20 MB limit.** Both are already bound.
- **Notification outbox or durable retry.** The spec's non-goal and the owner's decision. Reopen it only through the card below.
- **Retrying at temperature 0 probably returns the same invalid output.** That costs at most two extra Flash calls per bad receipt at about 2 receipts a day. It is not worth a rule.
- **Long-receipt slicing.** Already deferred until a fixture shows the need.

## Decision card for the owner

**Повторять ли уведомления после сбоя процесса?**
- **Что решается:** если сервис упадёт между записью итогового статуса и отправкой реакции, отправитель и администратор не узнают результат. Сейчас архитектура это сознательно допускает: повтора после сбоя нет.
- **Почему сейчас:** от этого зависит, нужна ли в таблице заданий колонка «уведомление отправлено» и шаг при запуске. Это проще заложить до разбивки на истории.
- **Варианты:**
  1. Оставить как есть. Потеря возможна только при сбое в окне в несколько секунд (до 5 попыток отправки); при ~2 чеках в день это крайне редко.
  2. Флаг `notify_pending`: он ставится в той же транзакции, что и итоговый статус, снимается после отправки, а при запуске уведомление отправляется повторно. Около 15 строк кода; в редком случае уведомление может прийти дважды.
- **Стоимость и риск:** вариант 2 даёт возможный дубль сообщения, но не дубль данных. Вариант 1 даёт редкую тихую потерю уведомления, в том числе админского уведомления о сбое с копией файла.
- **Рекомендация:** вариант 2, потому что спецификация обещает, что каждый сбой доходит до отправителя и администратора. Если важнее минимализм, вариант 1 допустим.
