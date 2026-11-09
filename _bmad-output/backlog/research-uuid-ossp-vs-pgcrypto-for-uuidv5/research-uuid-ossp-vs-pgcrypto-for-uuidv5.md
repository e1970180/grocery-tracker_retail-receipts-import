---
title: 'technical research: uuid-ossp vs pgcrypto for UUIDv5'
type: 'technical'
topic: 'uuid-ossp vs pgcrypto for UUIDv5'
decision: 'Choose uuid-ossp or pgcrypto to compute deterministic UUIDv5 in PostgreSQL 18.6'
source: 'native'
status: draft
preset: 'standard'
validation: 'normal'
created: '2026-11-09'
updated: '2026-11-09'
---

# technical research: uuid-ossp vs pgcrypto for UUIDv5

**Decision this research serves:** Choose uuid-ossp or pgcrypto to compute deterministic UUIDv5 in PostgreSQL 18.6

_Sections are appended per the approved research plan; the executive summary is written last and placed here, first._

## Recommendation

Use `uuid-ossp` (`uuid_generate_v5`). Both extensions are trusted (CREATE on the database is enough), so privileges do not decide it. `uuid_generate_v5` is IMMUTABLE, PARALLEL SAFE and STRICT, and Debian, Docker (Debian and Alpine) builds link libuuid (e2fs), not the unmaintained OSSP library [packaging digest]. PostgreSQL 18 has no built-in UUIDv5, and none appears in the 2026-11-07 devel docs [pgcrypto digest]. A pgcrypto route has no sourced reference implementation, so it would be our own code to maintain, and sha1 under a FIPS OpenSSL is unverified.

## Dev-database verification (2026-11-09, grocery-tracker-dev, read-only)

- `uuid-ossp` 1.1 is installed in `public`; server encoding is UTF8; the function is IMMUTABLE, PARALLEL SAFE, STRICT.
- RFC 9562 vector DNS `www.example.com` gives `2ed6657d-e927-568b-95e1-2665a8aea6a2`; URL `http://python.org/` gives `4c565f0d-3f5a-5890-b41b-20cf47701c5e`; both match the published values.
- The non-ASCII name `spar:Čaj zeleni 0,5l ß` in the URL namespace gives `165b574d-f4c8-528e-b1a8-7b8651ade646` in both PostgreSQL and Python `uuid.uuid5`, so UTF-8 handling agrees.

## Open items

- Behavior under an empty `search_path` and in pg_dump/restore was not confirmed by a source; the C function takes no schema lookups, but test it in CI.
- sha1 under FIPS OpenSSL is irrelevant to the uuid-ossp route.
- Whether the project's migration role may run `CREATE EXTENSION` is not checked (the dev check ran as superuser); on dev the extension already exists.
- Text normalisation is application-level: the contract must fix UTF-8 and the unaccent/sanitize steps.
