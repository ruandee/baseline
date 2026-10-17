# 005: Baseline pages live in `frontend/`, served same-origin

Status: accepted (17 Oct 2026, BL-16, issue #18). Supersedes the `web/` Next.js plan in
`docs/06-baseline.md`.

## In plain words

The spec said to build a separate Next.js app in `web/`. Since the spec was written, `main` gained a small
buildless web app in `frontend/` (decision 003). We build the Baseline pages (`/unit`,
`/resident/:id`, `/check`) there instead, for three reasons:

1. **Fewer moving parts under hackathon time pressure.** One server (the existing FastAPI app)
   serves the API and the pages. No Node toolchain, no second service in compose, no proxy
   route, no CORS.
2. **The phone needs HTTPS for the microphone.** One public HTTPS address in front of one
   server is much simpler to set up and to debug than two.
3. **Less to review.** BL-17/18/19 reuse the existing shell and styles, so the two UIs do not
   drift apart.

Trade-offs we accept: charts are hand-drawn SVG (no Recharts), no generated OpenAPI types
(we follow the response shapes in `docs/06-baseline.md` by hand), and MediaPipe for BL-34
would be vendored rather than installed from npm.

## How a phone gets a token (the part that needed a decision)

`frontend/` was built to talk only to a browser on the same laptop: it refused any request
that did not come from localhost, and it handed out a fresh token on demand. A phone on LTE
cannot work that way. We chose the simple option:

- **Static demo token.** A person runs `demo_reset` (BL-21), which mints a 48-hour synthetic
  nurse token. That token is passed to the server as `PM_DEMO_TOKEN`, and the server returns
  it from `/demo/session` instead of minting one.
- The rejected alternative was a login-style endpoint protected by a shared secret. It adds
  a secret to carry around and a new public endpoint to defend, for no benefit in a demo
  with synthetic data only.

**What this means for security, honestly:** anyone who can open the demo URL gets a
read-and-record nurse token for the synthetic tenant. That is acceptable only because the
data is fictional, the token expires in 48 hours, the tenant is isolated by row-level
security, and the URL is not published. It is not production sign-in and must not be reused
for real data (see AGENTS.md invariants).

## Contract

- Default mode is unchanged: loopback client, loopback Host, same-origin header, own token.
- **Hosted mode is opt-in**: set `PM_FRONTEND_HOSTS=demo.example.com` (comma-separated public
  hostnames) behind a TLS proxy such as Caddy. The Host header must match the list, and the
  `Origin` must match the request's own origin. The loopback-client check is dropped in
  this mode only, because behind a proxy the client address is the visitor's.
- `PM_DEMO_TOKEN`: serve this token from `/demo/session`. Required whenever `PM_FRONTEND_HOSTS` is set; the app refuses to start otherwise.
- Pages: `/unit`, `/resident/{id}`, `/check` all serve `frontend/baseline.html`, which loads
  `baseline.js` and `baseline.css` (verdict colour tokens). The Content-Security-Policy keeps
  `script-src 'self'` and adds `media-src 'self' blob:` for the recorder; no CDN scripts.
- The proxy must pass `Host` and `X-Forwarded-Proto` unchanged (Caddy does by default).

## Affected tickets

BL-16 (this), BL-17/18/19 build into `frontend/`. BL-20 drops the `web` compose service. BL-21
writes `PM_DEMO_TOKEN` and the patient ids into the server's environment instead of
`web/.env.local`. BL-07 still has to relax the 415/413 body middleware for the multipart
upload route. BL-01 owns `PM_TOKEN_TTL_HOURS`; this decision does not touch `config.py`.

## Running it hosted

```sh
PM_FRONTEND_HOSTS=demo.example.com PM_DEMO_TOKEN=<token> uv run python -m scripts.frontend
```

The server listens on `127.0.0.1:8001` and trusts forwarded headers only from localhost, so put
a TLS proxy on the same machine. Minimal Caddy config: `demo.example.com { reverse_proxy 127.0.0.1:8001 }`
(Caddy forwards `Host` and `X-Forwarded-Proto` by default). The `Origin` check only runs when the
browser sends an `Origin` header, which it does for `fetch` POSTs but not for plain page loads.
