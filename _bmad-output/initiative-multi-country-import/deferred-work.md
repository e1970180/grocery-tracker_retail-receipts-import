- source_plan: `_bmad-output/initiative-multi-country-import/tickets/epic-shared-chains-contract/tickets/story-consumer-contract-chains-v1-update-and-common-ownership-plan.md`
  summary: tests/test_chains_reader.py loads chains_v1.sql and still uses seller_oibs, so `pytest -m integration` fails until the adapter and tests move to country_code/tax_numbers.
  evidence: grep shows seller_oibs at tests/test_chains_reader.py lines 78-186 and CONTRACT_SQL at line 17; fixed by the adapter/test tickets of the same epic.
  resolution: done in tickets 1.2 and 1.4 (commits 11349c7, da443fb); tests/test_chains_reader.py uses country_code and tax_numbers.
- source_plan: `_bmad-output/initiative-multi-country-import/tickets/epic-shared-chains-contract/tickets/story-consumer-contract-chains-v1-update-and-common-ownership-plan.md`
  summary: docs/adding-a-chain.md (lines 75, 287) still tells operators to supply seller_oibs and 11-digit OIBs.
  evidence: contradicts chains_v1 1.2.0; belongs to the epic's sweep ticket.
  resolution: done in tickets 1.2 and 1.5 (commits 11349c7, 25a08e5); docs/adding-a-chain.md matches chains_v1 1.2.0.
- source_plan: `_bmad-output/initiative-multi-country-import/tickets/epic-shared-chains-contract/tickets/story-consumer-contract-chains-v1-update-and-common-ownership-plan.md`
  summary: Add integration tests that insert into public.chains and expect CheckViolation for bad country_code, blank/comma tax number, non-11-digit HR number, and acceptance of NULL/empty/non-HR rows.
  evidence: the new CHECK constraints have no executing test and were not run against PostgreSQL in this ticket (no RRI_TEST_DATABASE_URL available).
  resolution: closed as delegated to provider (owner, 2026-11-10); grocery-tracker/common owns public.chains DDL and tests these CHECK constraints in its conformance suite (docs/contracts/external/chains.md).
- source_plan: `_bmad-output/initiative-multi-country-import/tickets/epic-shared-chains-contract/tickets/story-consumer-contract-chains-v1-update-and-common-ownership-plan.md`
  summary: Contract does not say how one chain operating in several countries is represented, nor whether one tax number may appear on two chain rows.
  evidence: chain_id is globally unique while each row has one country_code (maybe real; would need an owner decision with common).
  resolution: moved to epic-multi-country-pipeline Open questions for coordination with grocery-tracker/common (owner, 2026-11-10).
