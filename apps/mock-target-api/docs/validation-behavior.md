# Validation Behavior Ground Truth

This fixture provides deterministic target behavior for Layer 1 audit validation. It should be interpreted as internal operational infrastructure, not a product API.

## Stable Hashing

Seed-based behavior uses:

```python
int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
```

Python built-in `hash()` is not used because it is not stable across processes.

## Endpoint Outcomes

### `/health/fast`

- Status code: `200`.
- Body: `service=mock-target-api`, `endpoint=fast`, `status=healthy`.
- No intentional delay.
- Expected audit result: stable, low-latency success.

### `/health/slow`

- Status code: `200`.
- Valid explicit `delay_ms`: integer `800` through `1500` inclusive.
- Invalid explicit delay falls back to seed if `seed` exists; otherwise default `1000` ms.
- Seed delay formula: `800 + stable_hash(seed) % 701`.
- Expected audit result: successful response with controlled higher latency.

### `/health/flaky`

- Seed precedence: query `seed`, header `X-RCP-Seed`, deterministic time-window fallback.
- `stable_hash(seed) % 5 == 0`: intentional `500` JSON with `status=degraded`.
- Other modulo values: `200` JSON with `status=healthy`.
- Known seeds: `seed-4` and `abc` produce degraded; `seed-0` produces healthy.
- Expected audit result: reproducible intermittent failure/degraded behavior.

### `/health/inconsistent`

- Status code: always `200` for completed application responses.
- `variant=A` returns schema with `version: A`.
- `variant=B` returns schema with `metadata.variant: B`.
- Invalid/absent variant with seed uses `stable_hash(seed) % 2`: `0 -> A`, `1 -> B`.
- Known seeds: `seed-3 -> A`, `seed-0 -> B`.
- Expected audit result: response/schema/fingerprint variation without HTTP failure.

### `/health/timeout`

- Default mode sleeps deterministically for 35-45 seconds and is intended to exceed runner `max_timeout_seconds=30`.
- `MOCK_TARGET_SHORT_TIMEOUT=true` uses 2-3 seconds for local/test only.
- Completed responses are valid JSON with `endpoint=timeout`, `delay_seconds`, and `timeout_mode`.
- Expected audit result: timeout classification when client/runner timeout is below endpoint completion time.

## Logging and Safety

Logs include compact endpoint/status/source metadata and do not include raw events, raw seeds, full headers, authorization values, cookies, or secrets. No persistence is performed.
