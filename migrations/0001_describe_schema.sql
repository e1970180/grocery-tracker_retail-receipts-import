-- Baseline: the schema and roles are provisioned outside migrations; this records what the schema is for.
COMMENT ON SCHEMA retail_receipts_import IS
    'retail-receipts-import service tables; written only by the service, read by others only through resolver_v* views';
