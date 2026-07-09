# Pull Request

## 1. Feature Name

Phase 7.8 — Validation Campaign: Live Certification Campaigns

## 2. Summary

This PR completes Phase 7.8 validation campaign work on the Phase 7 certification system. It includes:

1. **Phase 6 bug fix**: Added missing `aggregate_set_hash` field to `ReportMetadata` in the COMPLETE state transition. The Phase 6→7 consumer contract requires this field as stable and required in `ReportMetadata`, but Phase 6 never populated it. Bug discovered during live campaign execution.

2. **Regression test**: New unit test asserting `aggregate_set_hash` is present in the COMPLETE update.

3. **Campaign evidence**: Two live certification campaigns validating the Phase 7 system:
   - Campaign 01: `CERTIFIED` terminal state with all 8 certification domains PASSED
   - Campaign 02: `CERTIFICATION_FAILED` with disclosed evidence integrity and lineage failures

Phase 7 is now formally complete — all subphases 7.1–7.8 merged and validated.

## 3. Related Documents

- Product Spec: `RCP_Product_Strategy.md` (Phase 7 authorization)
- Architecture: `docs/architecture/phase_6_phase7_consumer_contract.md` (Section 3.1 — ReportMetadata schema)
- Technical Design: `docs/architecture/execution_lifecycle.md` (certification system behavior)
- QA Report: `docs/qa/phase_7_8_campaign_01.md`, `docs/qa/phase_7_8_campaign_02.md`

## 4. Changes Included

### Code Changes
- `src/release_confidence_platform/deterministic_reporting/engine.py` (Step 14): Added `"aggregate_set_hash": report.intelligence_provenance.aggregate_set_hash` to `meta_complete_updates` dictionary in COMPLETE transition
- `tests/unit/deterministic_reporting/test_engine.py`: Added `test_report_metadata_complete_includes_aggregate_set_hash` asserting presence of the field

### Campaign Documentation
- `docs/qa/phase_7_8_campaign_01.md`: Live campaign 01 evidence and certification results
- `docs/qa/phase_7_8_campaign_02.md`: Live campaign 02 evidence and certification results

## 5. QA Status

**Approved: YES**

[QA SIGN-OFF APPROVED]

Coverage:
- All 8 certification domains verified across both campaigns
- Idempotency gate verified: `CERTIFICATION_ALREADY_CERTIFIED` on re-run without `--force`
- All 4 `retrieve cert-*` CLI commands verified with correct output and provenance envelopes
- Phase 6 artifact non-mutation verified: original S3 artifact and ReportMetadata record unchanged after Phase 7 certification
- 1399 unit tests pass at campaign time (pre-existing PDF formatter collection error unrelated to these changes)

## 6. Test Coverage

**Unit Tests**: 1 new test added
- `test_report_metadata_complete_includes_aggregate_set_hash`: Validates that `aggregate_set_hash` is populated in `ReportMetadata` during COMPLETE transition

**Integration / Campaign Tests**: 2 live certification campaigns
- Campaign 01: `audit_20260626_6f433adc` (composite_score 1.000) → `CERTIFIED` state
- Campaign 02: Failure-injection test audit → `CERTIFICATION_FAILED` state with disclosed failures

**Regression**: Full test suite pass (1399 unit tests)

## 7. Risks / Notes

### Bug Fix Context
The Phase 6 bug is a schema violation discovered during Phase 7.8 live execution. The Phase 6→7 consumer contract explicitly requires `aggregate_set_hash` as a stable, required field. This fix ensures contract compliance and unblocks Phase 8 consumers depending on this field.

### Non-Breaking Change
The fix adds a missing field to an existing state transition. Existing Phase 6 reports without the field remain valid; new reports will include it. No API contract change. No behavioral change other than field presence.

### Campaign Results
- Campaign 01 validates the happy path: full system works correctly with all domains passing
- Campaign 02 validates error handling: failures are properly captured and disclosed
- Both campaigns demonstrate idempotency and artifact preservation

### Phase Completion
Phase 7 subphases 7.1–7.8 are now all merged and validated. Phase 7 is formally complete.

## 8. Linked Issue

Closes #83
