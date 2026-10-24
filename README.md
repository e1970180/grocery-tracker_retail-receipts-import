# retail-receipts-import

Import pipeline for retail grocery receipts into PostgreSQL over LAN.

## Configuration

All settings come from `RRI_*` environment variables, or from a gitignored `.env` in the
working directory. `.env.example` lists them. The service refuses to start on an invalid value.

| Variable | Meaning |
| --- | --- |
| `RRI_ENV` | `dev` or `prod`. `dev` needs a database name ending in `-dev`; `prod` needs one that does not. |
| `RRI_TELEGRAM_BOT_TOKEN` | Telegram bot token. |
| `RRI_GEMINI_API_KEY` | Gemini API key. |
| `RRI_GEMINI_MODEL` | Gemini model id (default `gemini-3.8-flash`). |
| `RRI_GEMINI_TIMEOUT_S` | Timeout of one Gemini request in seconds (default 120). |
| `RRI_GEMINI_THINKING_LEVEL` | `minimal`, `low`, `medium` or `high` (default `low`; `gemini-3.8-flash` has no `minimal`). |
| `RRI_GEMINI_BACKOFF_INITIAL_S` | First wait in seconds after an unavailable or misconfigured Gemini that names no delay of its own; each further wait in a row doubles (default 600). |
| `RRI_GEMINI_BACKOFF_CAP_S` | Cap on that doubling wait in seconds (default 1800). |
| `RRI_IMAGE_MAX_PIXELS` | Maximum image pixels before downscaling (default 16000000). |
| `RRI_DB_HOST`, `RRI_DB_PORT`, `RRI_DB_NAME` | PostgreSQL server and database. |
| `RRI_DB_USER`, `RRI_DB_PASSWORD` | Writer role, used by the service. |
| `RRI_DB_CONNECT_TIMEOUT_S` | Connect timeout in seconds (default 10). |
| `RRI_DB_STATEMENT_TIMEOUT_MS` | Server-side cap on one statement in milliseconds (default 30000). |
| `RRI_MIGRATE_DB_USER`, `RRI_MIGRATE_DB_PASSWORD` | Schema owner role, used only by `migrate`. |
| `RRI_ALLOWED_USER_IDS` | Required. Telegram user ids whose private messages are taken as receipts, comma-separated. |
| `RRI_ADMIN_CHAT_ID` | Required. Chat that gets failure notices and file copies; the admin must have started the bot. |
| `RRI_TELEGRAM_POLL_TIMEOUT_S` | Telegram long-polling timeout in seconds (default 30). |
| `RRI_JOB_RETRY_DELAY_S` | Wait in seconds before retrying a failed job step (default 600). |
| `RRI_JOB_MAX_ATTEMPTS` | Refused downloads or Gemini attempts before a job fails (default 3). |
| `RRI_DATA_DIR` | Directory for the SQLite queue and downloaded receipt files (default `/data`). |
| `RRI_TEXTS_PATH` | Texts file (default `texts/messages.toml`). |
| `RRI_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR` (default `INFO`). |

User- and admin-facing texts and reaction emoji live in `texts/messages.toml`. Every key must be
present and every reaction must be an emoji Telegram allows, or the service refuses to start.

## Chain reference

The service learns the known retail chains from an admin-owned reference, the view
`public.chains_v1`, which the writer role must be able to `SELECT`. This project never creates
or writes it; the admin sets it up from [`docs/contracts/chains_v1.sql`](docs/contracts/chains_v1.sql).
The shape the service relies on is the consumer contract
[`docs/contracts/chains_v1.md`](docs/contracts/chains_v1.md); versions are listed in
[`docs/api-versions.md`](docs/api-versions.md).

## Resolver feed contract

Stored receipts and a feed of stored and deleted events are exposed to the Resolver through views in
schema `resolver_v1`. The consumer reads only those views. The contract is
[`docs/contracts/resolver_v1.md`](docs/contracts/resolver_v1.md); versions are listed in
[`docs/api-versions.md`](docs/api-versions.md).

## Commands

```bash
uv run python -m retail_receipts_import migrate
```

```bash
uv run python -m retail_receipts_import run
```

`migrate` applies the numbered SQL files in `migrations/` that are not yet recorded in
`retail_receipts_import.schema_migrations`, each in its own transaction, as the schema owner.
Both schemas (`retail_receipts_import` and `resolver_v1`) and the three roles (schema owner,
writer, Resolver read-only) are provisioned with the database, not by migrations;
`resolver_v1` must exist before `migrate` applies `0004_resolver_v1.sql`.

## Deployment

On the server, from a sparse checkout:

```bash
docker compose build
```

```bash
docker compose run --rm -e RRI_MIGRATE_DB_USER -e RRI_MIGRATE_DB_PASSWORD receipts migrate
```

```bash
docker compose up -d
```

Export the schema owner credentials in the shell for the `migrate` run only; keep them out of
the server's `.env`.
