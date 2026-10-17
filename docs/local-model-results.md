# Local Ollama engineering trial — 2026-10-17

## Configuration

Ollama 0.40.5, official Windows ARM64 portable build, Snapdragon X1E80100 (12 logical CPUs), 32 GB system RAM, CPU inference. The runtime binds to `127.0.0.1:11434`.

Model: primary Qwen3.5 0.8B Q8_0 GGUF weights imported as `patient-memory-qwen35:0.8b`. Primary weight SHA-256: `889ea3b9143cdc32146c7d530ce5f3d452ec18069086f6f4167ce9ae72a9691f` (811,843,520 bytes). Weight hash was verified against the official Ollama manifest. The optional vision/draft layers were not required for this text-only trial. The verified original license is retained locally; the setup script imports it with the model.

The initial trial manifest digest was `15d0ea46cca38e39514f080c50d923464f9dd9268c8e08f125b439be7a516708`. Adding license metadata changes the local manifest digest but not the pinned primary weights. Runtime answers and cache keys resolve the current model manifest digest from Ollama.

Settings: thinking disabled, temperature 0, JSON schema restricted to permitted evidence IDs, 8,192 context, 600 output-token limit, maximum 12 source spans and 6,000 evidence UTF-8 bytes. Deterministic server code renders selected quotations and attribution; the model does not write free-form clinical prose.

## Measured results

One full 60-question synthetic regression run:

| Measure | Result |
| --- | --- |
| Expected source retrieved | 48/48 answerable questions |
| Expected source selected into a claim | 47/48 answerable questions |
| Appropriate abstention on unanswerable questions | 12/12 |
| Retrieved fact patient/tenant scope | 60/60 |
| Provider/schema failures | 0 |
| Generation latency, all questions (including fast no-evidence cases) | median 1.755 s; maximum 2.909 s |
| Retrieval latency including local DB connection | median 35.02 ms; p95 50.78 ms |

Failure: “Has pain changed in the patient report?” retrieved the correct “pain is unchanged” source, but the model selected no claim. The response abstained. The implementation now distinguishes model abstention (`selection_abstained`) from absent documentation and keeps the retrieved evidence inspectable.

The first five-question smoke run measured source retrieval only. Two further five-question repeats measured actual selection: expected sources selected 3/4 and 4/4, with the unanswerable question abstained in both. One repeat chose an older sleep observation instead of the expected newer one. This variability exists even at temperature 0. The earlier result must not be described as perfect model selection.

The runner now reports retrieval recall and selected-source recall separately, so a retrieved but unused citation cannot falsely pass model evaluation. Original outcomes remain in local ignored `artifacts/` files.

## Interpretation

This establishes that the local model adapter runs with the backend and that the small model has known selection misses. It does not establish clinical quality. The 60 questions are a regression set exposed during debugging. No two-model comparison, independent support review, new held-out patient study or large-corpus load test was completed. Use a new evaluation set before making model-quality claims. Local inference incurred no external API fee; electricity/hardware cost was not measured.
