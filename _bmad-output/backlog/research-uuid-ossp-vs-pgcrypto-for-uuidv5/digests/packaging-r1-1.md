# Digest: uuid-ossp packaging and operations (round 1, assistant 1)

Accessed 2026-11-09. Sources are primary (PG18 docs, postgres/postgres master, Debian salsa, docker-library/postgres). No source page showed a publication date.

| # | Claim | Source | Confidence |
| --- | --- | --- | --- |
| 1 | uuid-ossp is trusted; a non-superuser with CREATE on the database can install it | https://www.postgresql.org/docs/18/uuid-ossp.html | high |
| 2 | Control file: trusted = true, relocatable = true, default_version 1.1 (master branch, not REL_18 tag) | https://raw.githubusercontent.com/postgres/postgres/master/contrib/uuid-ossp/uuid-ossp.control | high |
| 3 | uuid_generate_v3/v5 and uuid_ns_* are IMMUTABLE STRICT PARALLEL SAFE (C); v1/v1mc/v4 VOLATILE; script has no schema qualification and no SET search_path (master) | https://raw.githubusercontent.com/postgres/postgres/master/contrib/uuid-ossp/uuid-ossp--1.1.sql | high |
| 4 | Debian PGDG packaging builds with --with-uuid=e2fs (libuuid), not OSSP; per-version override not checked | https://salsa.debian.org/postgresql/postgresql-common/-/raw/master/server/postgresql.mk | medium-high |
| 5 | Official postgres:18 (Debian) installs postgresql-18 from PGDG apt; inferred same e2fs build; uuid-ossp presence inferred from contrib in package, not verified | https://raw.githubusercontent.com/docker-library/postgres/master/18/bookworm/Dockerfile | medium |
| 6 | postgres:18-alpine builds from source with --with-uuid=e2fs and make -C contrib install | https://raw.githubusercontent.com/docker-library/postgres/master/18/alpine3.24/Dockerfile | high on flags, medium on presence |
| 7 | Docs: OSSP library is "not well maintained"; module can be built without it; options bsd, e2fs, ossp | https://www.postgresql.org/docs/18/uuid-ossp.html | high |
| 8 | PG18 adds core uuidv7() and uuidv4(); release notes list no uuid-ossp change | https://www.postgresql.org/docs/18/release-18.html | high |
| 9 | PG18 core has no uuidv5 (absence of evidence in release notes) | same | medium |

Not verified: behavior under empty search_path, pg_dump/restore behavior, Debian Build-Depends, maintainer deprecation statements.
