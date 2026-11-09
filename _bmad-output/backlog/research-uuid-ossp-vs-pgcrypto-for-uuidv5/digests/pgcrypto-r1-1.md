# Digest: pgcrypto as the UUIDv5 route (round 1, assistant 3)

Accessed 2026-11-09. Versioned docs pages show no publication date.

| # | Claim | Source | Confidence |
| --- | --- | --- | --- |
| 1 | pgcrypto is trusted in PG18; a non-superuser with CREATE on the database can install it | https://www.postgresql.org/docs/18/pgcrypto.html | high |
| 2 | pgcrypto requires OpenSSL; not built without it | same | high |
| 3 | OpenSSL 3 legacy provider is needed only for old ciphers (DES, Blowfish); page does not say sha1 digest is affected | same | high on quote, medium on "sha1 unaffected" |
| 4 | sha1 is a listed digest algorithm and not marked deprecated; FIPS setting affects only gen_salt() and crypt(); no source on digest('sha1') under FIPS OpenSSL 3 | same | high on page, none on FIPS behaviour |
| 5 | digest(text,text) is IMMUTABLE STRICT PARALLEL SAFE in pgcrypto--1.3.sql (master); bytea overload only partly verified | https://raw.githubusercontent.com/postgres/postgres/master/contrib/pgcrypto/pgcrypto--1.3.sql | high text, medium bytea |
| 6 | PG18 core has no uuidv3 or uuidv5 | https://www.postgresql.org/docs/18/functions-uuid.html | high |
| 7 | Devel docs snapshot of 2026-11-07 also lists no name-based UUID generator | https://www.postgresql.org/docs/devel/functions-uuid.html | medium-high |
| 8 | uuid-ossp is trusted; docs call the OSSP library poorly maintained; build picks a backend explicitly | https://www.postgresql.org/docs/18/uuid-ossp.html | high |
| 9 | 2017 bug report: uuid_generate_v3/v5 accept only text names; no bytea overload planned | https://www.postgresql.org/message-id/15138.1495666113%40sss.pgh.pa.us | medium (snippet only) |
| 10 | gen_random_uuid() is in core since v13, so pgcrypto would be loaded only for digest() | https://hackorum.dev/topics/77365 | high |

Not found: a sourced working pgcrypto UUIDv5 SQL implementation; team accounts choosing between the two; any commitfest entry for a built-in uuidv5; sha1 under FIPS OpenSSL 3.

Assistant's advice: test our own function against the RFC 9562 v5 vector and against uuid-ossp output on a scratch database before any code.
