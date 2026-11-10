---
title: 'Technical research: uuid-ossp vs. pgcrypto for UUIDv5'
type: 'technical'
topic: 'uuid-ossp vs pgcrypto for UUIDv5'
decision: 'Choose uuid-ossp or pgcrypto to compute deterministic UUIDv5 in PostgreSQL 18.6'
source: 'native'
status: complete
preset: 'standard'
validation: 'normal'
claims_verified: 3
claims_unverified: 6
created: '2026-11-09'
updated: '2026-11-10'
---

# Technical research: uuid-ossp vs. pgcrypto for UUIDv5

**Decision this research serves:** Choose `uuid-ossp` or `pgcrypto` to compute deterministic UUIDv5 in PostgreSQL 18.6.

## Executive summary

Use **`uuid-ossp` (`uuid_generate_v5`)** rather than implementing UUIDv5 over `pgcrypto` (`digest`).

1. **PostgreSQL 18 has no built-in UUIDv5:** PostgreSQL 18 adds `uuidv4()` and `uuidv7()` in core [7], but neither PostgreSQL 18 [10] nor the 2026-11-07 `devel` branch [11] includes a core name-based UUID generator (single publisher, `unverified` against an independent source).
2. **`uuid-ossp` avoids custom cryptographic code and uses `e2fs` (`libuuid`) in Debian and Alpine Docker builds:** Both Debian PGDG packaging (`per-version override not checked`, `medium-high` confidence) [4] and the official `postgres:18-alpine` Dockerfile (`high` on build flags, `medium` on runtime presence) [6] compile with `--with-uuid=e2fs`, avoiding the unmaintained OSSP library noted in upstream documentation [1] (`verified` across Debian packaging and Docker build definitions; Bookworm `postgres:18` uses PGDG apt and is inferred `e2fs`, `medium` confidence [5]). In `master` SQL, `uuid_generate_v5` is `IMMUTABLE`, `STRICT`, and `PARALLEL SAFE` in C [3], and dev-database checks matched RFC 9562 [14], CPython [15], and non-ASCII UTF-8 outputs (`verified`).
3. **`pgcrypto` adds custom maintenance and FIPS uncertainty:** Searches found no sourced, working SQL implementation of UUIDv5 using `pgcrypto`, and `pgcrypto` documentation leaves `sha1` behavior in `digest()` under FIPS OpenSSL 3 unverified [8] (`unverified`).

| Option | Core PG 18 availability | `e2fs` / OpenSSL dependency | Query safety & optimization | Main risk or gap |
| --- | --- | --- | --- | --- |
| Core PostgreSQL 18 | No (`uuidv4()`, `uuidv7()`, `gen_random_uuid()` only) [7][10][13] | None | N/A | Unavailable in PG 18 and 2026-11-07 `devel` [11] |
| `uuid-ossp` (`uuid_generate_v5`) | Contrib extension (`trusted`, `1.1`) [1][2] | `e2fs` (`libuuid`) in Debian/Alpine builds [4][6] | `IMMUTABLE STRICT PARALLEL SAFE` [3] | No `SET search_path` in script [3]; `text` only [12][19] |
| `pgcrypto` (`digest`) | Contrib extension (`trusted`) [8] | Requires OpenSSL [8] | `digest(text, text)` is `IMMUTABLE` (`master`) [9] | No sourced UUIDv5 SQL recipe; FIPS `sha1` unverified [8] |

> **Important:** Two operational items remain `unverified`: how `uuid-ossp--1.1.sql` behaves under an empty `search_path` and during `pg_dump` and restore (the script uses no schema qualification or `SET search_path` [3]), and whether the project's migration role holds `CREATE` on the database to install a trusted extension [1][2]. Cover both in migration tests and contract normalization rules.

---

## Core landscape and the `pgcrypto` alternative

- **No core UUIDv5:** PostgreSQL 18 adds `uuidv7()` and `uuidv4()` [7] alongside `gen_random_uuid()` from PostgreSQL 13 [13], but neither PostgreSQL 18 [10] nor the 2026-11-07 `devel` snapshot [11] provides `uuidv3` or `uuidv5` (`unverified`).
- **`pgcrypto` properties:** `pgcrypto` is `trusted` in PostgreSQL 18 and requires OpenSSL [8]. In `pgcrypto--1.3.sql` (`master` branch), `digest(text, text)` is `IMMUTABLE STRICT PARALLEL SAFE` (the `bytea` overload is only partly verified in the digest) [9]. Because `gen_random_uuid()` is already in core, loading `pgcrypto` would serve solely to call `digest()` [13] (`unverified`).
- **Missing recipe and FIPS risk:** Searches found no sourced, working SQL implementation of UUIDv5 using `pgcrypto` (`unverified`). Although `pgcrypto` documentation lists `sha1` and notes that OpenSSL 3's legacy provider affects old ciphers (`DES`, `Blowfish`; `medium` confidence that `sha1` is unaffected), the documentation's FIPS note covers only `gen_salt()` and `crypt()`, leaving `digest(..., 'sha1')` under FIPS OpenSSL 3 unverified (`none` confidence) [8].

---

## Packaging, build lineage, and operations (`uuid-ossp`)

- **Privileges and control metadata:** In PostgreSQL 18, `uuid-ossp` is `trusted`, allowing a non-superuser role with `CREATE` privilege on the target database to install it [1] (`medium` confidence, `unverified` for the project's migration role). The `master` branch control file (`not REL_18 tag`) sets `trusted = true`, `relocatable = true`, and `default_version = '1.1'` [2].
- **Function attributes and script behavior:** In `uuid-ossp--1.1.sql` (`master` branch, `not REL_18 tag`), `uuid_generate_v3`, `uuid_generate_v5`, and `uuid_ns_*` are `IMMUTABLE STRICT PARALLEL SAFE` C functions, whereas `uuid_generate_v1`, `v1mc`, and `v4` are `VOLATILE` [3]. These attributes let `uuid_generate_v5` run safely in functional indexes, triggers, and parallel plans. However, the script uses no schema qualification and no `SET search_path` [3]; behavior under an empty `search_path` and during `pg_dump` and restore across schemas remains `unverified`.
- **Library backend (`e2fs` vs. OSSP):** Although PostgreSQL 18 documentation warns that the OSSP UUID library is "not well maintained," `uuid-ossp` builds against `bsd`, `e2fs`, or `ossp` [1]. Debian PGDG packaging passes `--with-uuid=e2fs` (`libuuid`; `per-version override not checked`, `medium-high` confidence) [4], `postgres:18` (Debian Bookworm) installs `postgresql-18` from PGDG apt (`e2fs` and extension presence inferred, `medium` confidence) [5], and `postgres:18-alpine` builds from source with `--with-uuid=e2fs` and `make -C contrib install` (`high` on flags, `medium` on presence) [6].

---

## RFC 9562 conformance, text encoding, and interoperability

_Note from digest `rfc-conformance-r1-1.md`: web fetches in this dimension were summarized by a small model, so source quotes are second-hand._

- **Specification and standard namespaces:** Under RFC 9562 (Sections 4.1–4.2), UUIDv5 uses SHA-1 to hash the 16-byte namespace UUID (in network byte order) concatenated with the name bytes, keeps the leftmost 128 bits, and overwrites the version (`5`) and variant bits [14]. Standard namespaces (`DNS`, `URL`, `OID`, `X500`) match across RFC 9562 [14], `google/uuid` [17], and `uuidjs` (`v35.test.ts` cited in digest without a separate URL) (`verified`).
- **Encoding and normalization:** RFC 9562 specifies neither character encoding nor Unicode normalization for names [14]. Python `uuid.uuid5` encodes `str` names as UTF-8 [15], and `uuidjs` encodes strings as UTF-8 using `TextEncoder` [16], whereas Go's `NewSHA1` takes raw bytes so the caller owns encoding [17]. PostgreSQL's `uuid_generate_v5(namespace uuid, name text)` accepts only `text` [19] (no `bytea` overload is planned according to a 2017 `pgsql-bugs` thread [12], `unverified`), and upstream `current` documentation does not specify its encoding conversion [19] (`unverified` outside `UTF8` databases).
- **Cross-stack caveats:**
  - `.NET Guid.ToByteArray()` uses little-endian byte order for the first three fields, yielding mismatched namespace bytes unless the caller swaps those bytes [18] (`medium-high` confidence, `unverified`).
  - Canonically equivalent Unicode forms (such as NFC vs. NFD) hash to different UUIDs because RFC 9562 specifies hashing raw name bytes without normalization (`low-medium` confidence from a search summary with no primary source, consistent with [14]; `unverified`).
- **Non-ASCII coverage:** Searches found no published non-ASCII UUIDv5 test vector (`unverified`).

### Test vectors and empirical dev-database verification

On `2026-11-09`, read-only checks on `grocery-tracker-dev` confirmed `uuid-ossp` `1.1` installed in `public`, `UTF8` server encoding, and `IMMUTABLE`, `PARALLEL SAFE`, and `STRICT` attributes on `public.uuid_generate_v5` (matching [3]). Independently published vectors and live database checks agree:

| Namespace | Name input | Expected / returned UUID | Published source | Dev-DB (`grocery-tracker-dev`) & Python `uuid.uuid5` |
| --- | --- | --- | --- | --- |
| `DNS` | `www.example.com` | `2ed6657d-e927-568b-95e1-2665a8aea6a2` | RFC 9562 Appendix A.4 [14] | `uuid_generate_v5` matched (`verified`) |
| `URL` | `http://python.org/` | `4c565f0d-3f5a-5890-b41b-20cf47701c5e` | CPython `uuid` docs [15] | `uuid_generate_v5` matched (`verified`) |
| `DNS` | `python.org` | `886313e1-3b8a-5372-9b90-0c9aee199e5d` | CPython `uuid` docs [15] | Not run in dev DB |
| `OID` | `1.3.6.1` | `1447fa61-5277-5fef-a9b3-fbc6e44f4af3` | CPython `uuid` docs [15] | Not run in dev DB |
| `X500` | `c=ca` | `cc957dd1-a972-5349-98cd-874190002798` | CPython `uuid` docs [15] | Not run in dev DB |
| `URL` | `http://example.com/hello` | `3bbcee75-cecc-5b56-8031-b6641c1ed1f1` | `uuidjs` (`v35.test.ts`, no URL in digest) | Not run in dev DB |
| `URL` | `spar:Čaj zeleni 0,5l ß` | `165b574d-f4c8-528e-b1a8-7b8651ade646` | Non-ASCII UTF-8 check | Both `uuid_generate_v5` and `uuid.uuid5` matched (`verified`) |

---

## Cross-dimension insights

Packaging lineage and encoding constraints reinforce one another: because Debian and Alpine PostgreSQL 18 images avoid the unmaintained OSSP library by linking `e2fs` (`libuuid`) [4][6], the historical reason to consider `pgcrypto` disappears, while cross-language determinism with Python [15] and JavaScript [16] depends on `UTF8` encoding and explicit pre-hash text normalization [14].

---

## Contrary evidence

No adversarial red-team pass ran (`preset: standard`, `validation: normal`, `red_team: off`). The main counterarguments surfaced during research are:

1. **Upstream OSSP caution:** PostgreSQL 18 documentation states the OSSP UUID library is "not well maintained" [1], mitigated in Debian and Alpine images via `--with-uuid=e2fs` [4][6].
2. **Text-only signature without documented encoding rules:** `uuid_generate_v5` accepts only `text` [12][19], and upstream documentation does not specify its encoding conversion [19].
3. **Unqualified install script:** `uuid-ossp--1.1.sql` (`master`) lacks `SET search_path` and schema qualification [3], leaving empty-`search_path` and `pg_dump` behavior `unverified`.

---

## Recommendations

- **Decision — adopt `uuid-ossp` (`public.uuid_generate_v5`):**
  - **Confidence basis:** `high` on RFC 9562 and CPython vector matches [14][15], live non-ASCII UTF-8 match, and Alpine `--with-uuid=e2fs` flags [6]; `medium-high` on Debian `--with-uuid=e2fs` packaging [4]; `medium` on Bookworm PGDG inference [5].
  - **Downstream binding (database migrations and outgoing feed contract):**
    1. Schema-qualify calls as `public.uuid_generate_v5(...)` and pass an explicit `uuid` namespace literal (for example, RFC 9562 `NAMESPACE_URL` [14]) rather than relying on `search_path`.
    2. Specify the UTF-8 encoding and text normalization order (`unaccent` and `sanitize`) in the migration function, and document the final normalized-string recipe plus test vectors in the outgoing feed contract, explicitly warning .NET and other non-Python consumers about byte order [18] and Unicode normalization [14].
- **Runner-up (`pgcrypto`):** Use `pgcrypto` only if a target PostgreSQL host forbids installing `uuid-ossp`; in that case, write an explicit bit-manipulation wrapper around `digest(..., 'sha1')` (`unverified` under FIPS OpenSSL 3 [8]) and verify it against RFC 9562 [14] and non-ASCII Python vectors [15] before shipping.

---

## Open questions

1. **Empty `search_path`, `pg_dump`, and restore behavior (`unverified`):** Upstream `uuid-ossp--1.1.sql` sets no `search_path` [3]. Verify in CI that dumping and restoring a database with `public.uuid_generate_v5(...)` inside triggers and functions succeeds under `pg_dump`'s restricted `search_path`.
2. **Migration-role `CREATE EXTENSION` privileges (`unverified`):** `uuid-ossp` is `trusted` (`CREATE` on the database suffices) [1][2], but the dev-database check inspected an already-installed extension as superuser. Test `CREATE EXTENSION IF NOT EXISTS "uuid-ossp"` in CI under the project's schema-owner or migration role.
3. **Canonical Unicode normalization (`unverified`, `low-medium` confidence):** Because RFC 9562 specifies no Unicode normalization [14], confirm in the application or SQL normalization contract how the pipeline handles NFC and NFD inputs before calling `uuid_generate_v5`.
4. **FIPS OpenSSL 3 `sha1` behavior (moot):** Whether `pgcrypto` `digest(..., 'sha1')` works under FIPS-mode OpenSSL 3 remains `unverified` [8] and affects only the `pgcrypto` fallback.

---

## Source appendix

| # | Topic supported | Publisher | Pub date | Accessed | Confidence |
| --- | --- | --- | --- | --- | --- |
| [1] | PG18 `uuid-ossp` trusted status, OSSP note, backend options | [PostgreSQL 18 Docs: uuid-ossp](https://www.postgresql.org/docs/18/uuid-ossp.html) | undated | 2026-11-09 | high |
| [2] | `uuid-ossp.control` (`trusted`, `relocatable`, `1.1`, `master`) | [PostgreSQL Git (`uuid-ossp.control`)](https://raw.githubusercontent.com/postgres/postgres/master/contrib/uuid-ossp/uuid-ossp.control) | undated (`master`) | 2026-11-09 | high |
| [3] | `uuid-ossp--1.1.sql` volatility and missing `search_path` (`master`) | [PostgreSQL Git (`uuid-ossp--1.1.sql`)](https://raw.githubusercontent.com/postgres/postgres/master/contrib/uuid-ossp/uuid-ossp--1.1.sql) | undated (`master`) | 2026-11-09 | high |
| [4] | Debian PGDG `--with-uuid=e2fs` build flag (no per-version check) | [Debian Salsa (`postgresql.mk`)](https://salsa.debian.org/postgresql/postgresql-common/-/raw/master/server/postgresql.mk) | undated | 2026-11-09 | medium-high |
| [5] | `postgres:18` Bookworm PGDG apt (`e2fs` and presence inferred) | [Docker Official Images (`18/bookworm/Dockerfile`)](https://raw.githubusercontent.com/docker-library/postgres/master/18/bookworm/Dockerfile) | undated | 2026-11-09 | medium |
| [6] | `postgres:18-alpine` `--with-uuid=e2fs` source build | [Docker Official Images (`18/alpine3.24/Dockerfile`)](https://raw.githubusercontent.com/docker-library/postgres/master/18/alpine3.24/Dockerfile) | undated | 2026-11-09 | high (flags), medium (presence) |
| [7] | PG18 release notes (`uuidv7`/`uuidv4`, no `uuid-ossp` change) | [PostgreSQL 18 Release Notes](https://www.postgresql.org/docs/18/release-18.html) | undated | 2026-11-09 | high (`v4`/`v7`), medium (no `v5`) |
| [8] | PG18 `pgcrypto` OpenSSL, `sha1`, and FIPS scope | [PostgreSQL 18 Docs: pgcrypto](https://www.postgresql.org/docs/18/pgcrypto.html) | undated | 2026-11-09 | high (quote), medium (`sha1` unaffected), none (FIPS) |
| [9] | `pgcrypto--1.3.sql` `digest(text, text)` attributes (`master`) | [PostgreSQL Git (`pgcrypto--1.3.sql`)](https://raw.githubusercontent.com/postgres/postgres/master/contrib/pgcrypto/pgcrypto--1.3.sql) | undated (`master`) | 2026-11-09 | high (`text`), medium (`bytea`) |
| [10] | PG18 core UUID functions (no `uuidv3`/`uuidv5`) | [PostgreSQL 18 Docs: UUID Functions](https://www.postgresql.org/docs/18/functions-uuid.html) | undated | 2026-11-09 | high |
| [11] | PG `devel` UUID functions snapshot (no `uuidv5`) | [PostgreSQL devel Docs: UUID Functions](https://www.postgresql.org/docs/devel/functions-uuid.html) | 2026-11-07 | 2026-11-09 | medium-high |
| [12] | `uuid_generate_v3`/`v5` `text`-only signature, no `bytea` | [PostgreSQL `pgsql-bugs` Archive](https://www.postgresql.org/message-id/15138.1495666113%40sss.pgh.pa.us) | 2017 | 2026-11-09 | medium (snippet only) |
| [13] | Core `gen_random_uuid()` since PG13 (`pgcrypto` redundant) | [Hackorum](https://hackorum.dev/topics/77365) | undated | 2026-11-09 | high |
| [14] | RFC 9562 UUIDv5 spec, namespaces, A.4 vector, no encoding rule | [IETF RFC 9562](https://www.rfc-editor.org/rfc/rfc9562.txt) | 2024-05 | 2026-11-09 | high (spec/vector), medium-high (absence) |
| [15] | Python `uuid.uuid5` UTF-8 encoding and CPython test vectors | [Python 3 Docs (`uuid`)](https://docs.python.org/3/library/uuid.html) | undated | 2026-11-09 | high |
| [16] | `uuidjs` UTF-8 encoding using `TextEncoder` | [uuidjs/uuid (`src/v35.ts`)](https://raw.githubusercontent.com/uuidjs/uuid/main/src/v35.ts) | undated | 2026-11-09 | high |
| [17] | `google/uuid` namespaces and byte-level `NewSHA1` | [google/uuid (`hash.go`)](https://raw.githubusercontent.com/google/uuid/master/hash.go) | undated | 2026-11-09 | high |
| [18] | `.NET Guid.ToByteArray()` little-endian field order | [Microsoft Learn (.NET API)](https://learn.microsoft.com/dotnet/api/system.guid.tobytearray) | undated | 2026-11-09 | medium-high |
| [19] | PG `current` `uuid_generate_v5(uuid, text)` signature, silent on encoding | [PostgreSQL Current Docs: uuid-ossp](https://www.postgresql.org/docs/current/uuid-ossp.html) | undated | 2026-11-09 | high (signature), unverified (encoding) |

---

## Staleness map

Computed on `2026-11-10` with `recon_kit.py staleness` against the Technical pack freshness windows (`versions_compatibility`: 1 month, `ecosystem_signals`: 6 months, `landscape`: 12 months, `patterns`: 24 months). Undated live documentation pages use their access date (`2026-11-09`).

| Claim | Class | Pub / Access Date | Re-check Date | Stale Now? |
| --- | --- | --- | --- | --- |
| `uuid_generate_v3`/`v5` `text`-only mailing-list thread [12] | `ecosystem_signals` | 2017 | 2017-07-01 | **Yes** (historical signal) |
| RFC 9562 v5 spec, namespaces, and A.4 vector [14] | `patterns` | 2024-05 | 2026-05-01 | **Yes** (immutable RFC; verify only if superseded) |
| PostgreSQL 18 core and `devel` lack built-in `uuidv5` [10][11] | `versions_compatibility` | 2026-11-07 | 2026-12-07 | No |
| Debian and Alpine `--with-uuid=e2fs` build [4][6] | `versions_compatibility` | 2026-11-09 | 2026-12-09 | No |
| `uuid_generate_v5` `IMMUTABLE STRICT PARALLEL SAFE` [3] | `versions_compatibility` | 2026-11-09 | 2026-12-09 | No |
| `uuid-ossp` `trusted` and `relocatable` (`CREATE` privilege) [1][2] | `versions_compatibility` | 2026-11-09 | 2026-12-09 | No |
| `uuid-ossp--1.1.sql` lacks `SET search_path` [3] | `versions_compatibility` | 2026-11-09 | 2026-12-09 | No |
| `pgcrypto` `digest` status and missing FIPS `sha1` evidence [8][9] | `versions_compatibility` | 2026-11-09 | 2026-12-09 | No |
| `.NET` byte order (`2026-11-09`) and Unicode normalization caveats [14][18] | `patterns` | 2026-11-09 | 2028-11-09 | No |

**Earliest re-check:** `2017-07-01` / `2026-05-01` (flagged as stale due to the historical thread [12] and May 2024 RFC publication [14]); earliest upcoming compatibility re-check is **`2026-12-07`** (PostgreSQL `devel` snapshot [11]), followed by **`2026-12-09`** for PostgreSQL 18 and container packaging claims.
