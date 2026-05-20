# Mock Target API

Backend-only internal operational fixture for Layer 1 validation of release-confidence-platform runner behavior. This is not a customer-facing or production product surface. It intentionally has no auth, user management, persistence, analytics, AI, dashboards, or heavy web framework.

## Endpoints

All completed responses are JSON with `service: mock-target-api` and an `endpoint` identifier.

| Route | Expected behavior | Audit interpretation |
| --- | --- | --- |
| `GET /health/fast` | Immediate `200` healthy body; no intentional sleep. | Stable low-latency success baseline. |
| `GET /health/slow` | `200` healthy after deterministic delay. Valid `delay_ms` is `800..1500`; otherwise `seed` derives `800 + sha256(seed) % 701`; otherwise `1000`. | Stable success with measurable latency. |
| `GET /health/flaky` | Query `seed`, then `X-RCP-Seed`, then manual time-window fallback. `sha256(seed) % 5 == 0` returns intentional JSON `500` degraded; otherwise `200` healthy. | Reproducible intermittent failure/degraded classification. |
| `GET /health/inconsistent` | Always `200`. `variant=A|B` forces schema; otherwise seed derives A/B using SHA-256 modulo 2; otherwise time-window fallback. | Reproducible schema/fingerprint variation. |
| `GET /health/timeout` | Default deterministic sleep is 35-45 seconds, exceeding runner `max_timeout_seconds=30`. `MOCK_TARGET_SHORT_TIMEOUT=true` shortens to 2-3 seconds for local/test only. | Timeout and retry classification validation. |

## Local Lambda Invocation

From `apps/mock-target-api/`:

```bash
sls invoke local -f healthFast -p events/sample_events/health_fast.json
sls invoke local -f healthSlow -p events/sample_events/health_slow.json
sls invoke local -f healthFlaky -p events/sample_events/health_flaky_failure.json
sls invoke local -f healthInconsistent -p events/sample_events/health_inconsistent_a.json
MOCK_TARGET_SHORT_TIMEOUT=true sls invoke local -f healthTimeout -p events/sample_events/health_timeout_short.json
```

Do not run the timeout endpoint in default mode during normal local/CI tests unless a long wait is intended.

## Deployment

Deploy with Serverless Framework from this directory:

```bash
sls deploy --stage dev
sls deploy --stage staging
sls deploy --stage prod
```

The default deployed `MOCK_TARGET_SHORT_TIMEOUT` value is `false`; only set it explicitly for local/test validation.

## Curl Testing

Set the deployed or local HTTP base URL:

```bash
export MOCK_TARGET_API_BASE_URL="https://example.execute-api.us-east-1.amazonaws.com"
curl -i "$MOCK_TARGET_API_BASE_URL/health/fast"
curl -i "$MOCK_TARGET_API_BASE_URL/health/slow?delay_ms=800"
curl -i "$MOCK_TARGET_API_BASE_URL/health/flaky?seed=seed-4"
curl -i "$MOCK_TARGET_API_BASE_URL/health/inconsistent?variant=A"
curl --max-time 30 -i "$MOCK_TARGET_API_BASE_URL/health/timeout"
```

## Tests

From the repository root:

```bash
python -m pytest apps/mock-target-api/tests/unit apps/mock-target-api/tests/integration
```

HTTP integration tests skip unless `MOCK_TARGET_API_BASE_URL` is set. Unit tests monkeypatch sleeps so the normal suite does not wait 35-45 seconds.
