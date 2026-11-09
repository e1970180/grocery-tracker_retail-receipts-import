# Digest: UUIDv5 specification and verification (round 1, assistant 2)

Accessed 2026-11-09. Fetches were summarised by a small model, so quotes are second-hand.

| # | Claim | Source | Confidence |
| --- | --- | --- | --- |
| 1 | v5 = SHA-1 over namespace bytes (network order) followed by name; leftmost 128 bits used; version and variant bits overwritten (RFC 9562 sections 4.1, 4.2) | https://www.rfc-editor.org/rfc/rfc9562.txt, May 2024 | high |
| 2 | RFC text mentions no name encoding or Unicode normalisation | same | medium-high |
| 3 | Namespaces: DNS 6ba7b810-9dad-11d1-80b4-00c04fd430c8, URL 6ba7b811-..., OID ...812, X500 ...814; confirmed by Go google/uuid and uuidjs | same, plus hash.go and v35.test.ts | high |
| 4 | Python uuid5 encodes a str name as UTF-8 | https://docs.python.org/3/library/uuid.html | high |
| 5 | Node uuid v5 encodes string names as UTF-8 via TextEncoder | https://raw.githubusercontent.com/uuidjs/uuid/main/src/v35.ts | high |
| 6 | Go NewSHA1 takes bytes, caller owns encoding | https://raw.githubusercontent.com/google/uuid/master/hash.go | high |
| 7 | uuid_generate_v5(namespace uuid, name text): docs silent about text encoding | https://www.postgresql.org/docs/current/uuid-ossp.html | high on signature, encoding unverified |
| 8 | .NET Guid.ToByteArray is little-endian in the first three fields; wrong namespace bytes unless swapped | https://learn.microsoft.com/dotnet/api/system.guid.tobytearray | medium-high |
| 9 | Canonically equivalent Unicode forms hash to different UUIDs; fix normalisation in the application | search summary, no primary source | low-medium |

Test vectors (independently sourced):
- RFC 9562 A.4: DNS, `www.example.com` -> `2ed6657d-e927-568b-95e1-2665a8aea6a2`.
- CPython: DNS `python.org` -> `886313e1-3b8a-5372-9b90-0c9aee199e5d`; URL `http://python.org/` -> `4c565f0d-3f5a-5890-b41b-20cf47701c5e`; OID `1.3.6.1` -> `1447fa61-5277-5fef-a9b3-fbc6e44f4af3`; X500 `c=ca` -> `cc957dd1-a972-5349-98cd-874190002798`.
- uuidjs: URL `http://example.com/hello` -> `3bbcee75-cecc-5b56-8031-b6641c1ed1f1`.

Not found: any published non-ASCII v5 vector; whether uuid_generate_v5 hashes in the database encoding (risk if not UTF-8); RFC 4122 full text.
