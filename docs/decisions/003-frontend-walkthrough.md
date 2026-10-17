# B12: Synthetic handoff frontend

The requested frontend is served at `/app/` by FastAPI. It uses plain browser JavaScript and CSS with no separate Node build or frontend server. Static assets are packaged inside the Python module. Existing API authorization and evidence contracts remain unchanged.

The UI presents a session-scoped patient directory, date-selected shift summary, source timeline with pagination, questions, and an evidence dialog. All clinical content comes from the API. Unknowns, conflicts, historical/patient-reported attribution, incomplete coverage and failures remain visible. Text is inserted with textContent, never interpreted as HTML. Request generations discard stale responses when switching patients.

`scripts.frontend_demo` imports six fictional profiles into a fresh synthetic tenant and issues a read-only nurse assignment. The browser receives the session via a URL fragment, removes it immediately, and keeps demo credentials in tab-scoped sessionStorage so refresh preserves the session. Disconnect removes the stored session. This storage is for the synthetic walkthrough; production identity remains deferred. The launcher is local tooling, not an unauthenticated token-issuing HTTP route. Do not share the session link. Sessions expire after eight hours. Importing the older fixture-loader JSON retains that file's permissions; the new launcher is preferred.

The demo defaults to the fixture date January 2, 2026, with current system knowledge, so corrections are visible. It does not imply that old observations are current clinical measurements. Date selection changes the event-time horizon, not knowledge time. No predictions, treatment recommendations, Codex SDK adapter, or production identity flow were added.
