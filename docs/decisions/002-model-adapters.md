# Evidence selection model boundary

The user chose local Ollama. The native adapter uses `/api/chat`, a JSON schema for evidence IDs, `think=false`, a fixed context window and bounded generation. Server code validates every ID and renders exact quotations with deterministic attribution/time labels. Known structured contradictions and linked medication-stop evidence cannot be dropped by the selector.

The optional compatible adapter accepts a separately configured `/chat/completions` endpoint. Redirects and inherited proxy settings are disabled. Non-loopback endpoints require HTTPS. Notes cannot select an endpoint or invoke tools. Provider failures return errors, not empty records. Malformed selections retry once; fabricated IDs are rejected.

Free-form paraphrased clinical synthesis is postponed until it has an independent support evaluator. The first local model is a small CPU-feasible engineering baseline. Benchmark multiple candidates on new held-out fixtures before asserting comparative quality; the first corpus has already been used to debug retrieval.

References: [Ollama structured outputs](https://ollama.com/blog/structured-outputs), [Ollama API specification](https://github.com/ollama/ollama/blob/main/docs/openapi.yaml), [HTTPX timeout behavior](https://www.python-httpx.org/advanced/timeouts/).
