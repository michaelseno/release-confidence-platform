# Raw Evidence Philosophy

Raw evidence is the future source of truth for release-confidence analysis. Derived findings should be reproducible from versioned raw results and should not replace the underlying evidence.

Phase 0 reserves the `raw_result_version` identifier and the future raw-results resource name:

`release-confidence-platform-${stage}-raw-results`

Future phases must define object keys, retention, encryption, immutability/append behavior, and sanitization before implementing persistence.
