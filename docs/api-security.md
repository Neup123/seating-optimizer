# Supported security boundary — local-only API

The FastAPI adapter is a **local operator tool**, not an authenticated public service. The API has no accounts or API keys.

## Enforced controls

1. **Direct clients must be loopback:** the ASGI middleware rejects any non-loopback source with HTTP 403, including access to documentation, health and every v1/v2 API route. It accepts IPv4 `127.0.0.0/8` and IPv6 `::1`. The standard ASGI test-client sentinel is accepted only for automated in-process tests. It never trusts client-controlled `X-Forwarded-For` or `Forwarded` headers.
2. **JSON request size:** request payloads for POST/PUT/PATCH are capped at 8 MiB, checked both from declared Content-Length and actual accumulated stream bytes before JSON parsing. Larger imports should be split into operator-controlled files rather than raising server limits silently.
3. **Expensive work:** solve and reassignment requests are capped at a declared 60-second solve timeout, 16 solver workers, 2,000 guests and 200 tables. The core Python package retains its configurable solver interface for trusted offline code; these are HTTP-ingress caps.
4. **Local deployment command:** `uvicorn seating_optimizer.api.app:app --host 127.0.0.1 --port 8000`. The browser and API docs are on that same origin.

## Network access

Binding Uvicorn to `0.0.0.0` alone will **not** make the API available to remote TCP peers: the app rejects them. The intended access model is one operator on the host computer. This is not an authentication mechanism and must not be described as safe multi-user internet deployment.

If an administrator deliberately places an **authenticated, TLS-protected reverse proxy** on the same host and forwards requests from that local proxy to loopback, the API may see the proxy as loopback. The proxy then owns all client identity, authorization, exposure and abuse limits. Treat that as a separate deployment requiring security review, not an approved default. Misconfigured same-host proxies can expose the otherwise local API. No proxy/header identity is trusted or validated by this service.

## Resource limits and exclusions

- The request cap protects import, solve and export POST bodies, not the size of all output PDFs/HTML or CPU consumption of syntactically valid models within permitted limits.
- A 60-second solver time limit does not cap all process lifetime or memory usage, and does not replace service-level process/memory limits in the host supervisor.
- A loopback client can still read/send any accessible planning data. Keep real guest names in a trusted browser profile and apply the [browser privacy policy](browser-privacy.md) once PR #104 merges.
- The API does not provide anti-CSRF tokens, user accounts, multi-tenant isolation or public rate limiting. Do not advertise remote access without designing those separately.
- This change does not make the browser's localStorage encrypted.

## Acceptance

`tests/test_api_security.py` checks external client rejection despite forged forwarding headers, IPv4/IPv6 loopback, actual body replay into import, declared oversized request rejection, solve limit rejection and normal schema validation. Browser E2E tests must still run against a real loopback Uvicorn process.

When changing HTTP routes or adding a new endpoint, confirm the guard applies automatically and do not add a second route-specific copy of these controls.
