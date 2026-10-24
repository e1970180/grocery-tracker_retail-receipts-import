-- Provisions one environment: three login roles, the database, both service schemas, the chain
-- reference and the minimal grants. Run once as the PostgreSQL admin, from the repository root:
--   psql -h <host> -p <port> -U postgres -d postgres -v ON_ERROR_STOP=1 \
--        -v db=grocery-tracker-dev -v owner=rri_dev_owner -v writer=rri_dev_writer \
--        -v reader=resolver_dev_reader -f docs/deploy/provision.sql
-- psql asks for each role's password; none is written to a file or the shell history.

CREATE ROLE :"owner" LOGIN;
CREATE ROLE :"writer" LOGIN;
CREATE ROLE :"reader" LOGIN;
\password :owner
\password :writer
\password :reader

CREATE DATABASE :"db";
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO :"owner", :"writer", :"reader";

\connect :"db"

-- Only the writer reads public (the chain reference view).
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"writer";

CREATE SCHEMA retail_receipts_import AUTHORIZATION :"owner";
CREATE SCHEMA resolver_v1 AUTHORIZATION :"owner";
GRANT USAGE ON SCHEMA retail_receipts_import TO :"writer";
GRANT USAGE ON SCHEMA resolver_v1 TO :"reader";

-- Tables that migrations create later: the writer reads and inserts, never updates or deletes.
-- after-migrate.sql trims the tables it only inserts into and the migrations ledger.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA retail_receipts_import
    GRANT SELECT, INSERT ON TABLES TO :"writer";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA retail_receipts_import
    GRANT USAGE ON SEQUENCES TO :"writer";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA retail_receipts_import
    GRANT USAGE ON TYPES TO :"writer";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA resolver_v1
    GRANT SELECT ON TABLES TO :"reader";

BEGIN;
\ir ../contracts/chains_v1.sql
GRANT SELECT ON public.chains_v1 TO :"writer";
COMMIT;
