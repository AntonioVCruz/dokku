# Routing coverage

All Bats references below are in `tests/unit/proxy-route-nginx.bats`. Browser
cases are gated only on nginx. The two declared duplicates establish the
preconditions for the lifecycle sequence; their value is browser rendering and
JavaScript fetch behavior after state changes, not a claim of new native coverage.

| Case | Existing Bats coverage (test name) | New or duplicate | Independent oracle source | Negative control | Negative run ID | Local run ID |
| --- | --- | --- | --- | --- | --- | --- |
| TC-01 routed identity | `basic routing - /api/v0 hits api, / hits web` (line 16) | Duplicate/precondition | `config:get E2E_MARKER` | Remove route | TF7AhRqAqdaBxBhvA (failed at assertion) | sQoc8KDSdc5jTQYys (pass) |
| TC-02 restart | No lifecycle test in original file | New lifecycle check | Config marker; pre-restart Docker hostname | Skip restart | YsuQDeH2fAjGjoNmj (failed at assertion) | oFn8aJ3qHq6X8AAqJ (pass) |
| TC-03 configuration | No lifecycle test in original file | New lifecycle check | Controller-generated marker; original config marker | Skip config:set | xQDJz9PaA9qdNcNmJ (failed at assertion) | AxMqjKdyeRxtnx9Me (pass) |
| TC-04 removal | `removing a route falls back to web` (line 63) | Duplicate/precondition | Repository fixture's web fallback (404) | Keep route | 8TkxYZnY6dJD3ZppR (failed at assertion) | sP7r8ewEZ4rxpZJft (pass) |
| TC-05 re-addition | Original file tests removal, not remove/re-add | New lifecycle check | Original config marker | Leave route removed | MdADuYJYDH7tCa2ai (failed at assertion) | tqxtu2SQv6tYdACcz (pass) |
| TC-06 WebSocket | `websocket upgrade headers are present in rendered config` (line 117) | New live browser WebSocket | Test-generated message; config marker; independently specified Host | Remove /ws route | Bto8N5hYNk2NGhDnZ (failed at assertion) | JKDRZ8KWu3dYWYKYR (pass) |
| TC-07 continuous client | No live continuous-client test | Contract-pending, not authored or gating | Non-web restart availability guarantee unconfirmed | Would scale API to zero | Not run | Not run |
| TC-08 scaled to zero | No rendered error-page test | New browser error page | Repository `500-error.html` heading/detail; post-case HTTP 502 | Keep API at one | SJaMeDCf9hMJ87dsW (failed at assertion) | Xuqn2FzZYDjZ8M4aD (pass) |
| TC-09 prefix-stripped redirect | No browser redirect test | Contract-pending, characterization only | Fixture's literal API login page | Scale API to zero | pcAgvMJ838AcuPdwC (failed during navigation; assertion not reached) | z2NZh7LXsJEzuoCSY (404 navigation) |
| TC-10 reserved | Prefix boundary and overlap belong to native track | No browser case | Not applicable | Not applicable | Not run | Not run |

The routing contract describes longest-prefix-first matching and the web
catch-all (`docs/networking/proxy-management.md:196`, `:260`), transparent
WebSocket forwarding (`:277`), and no upstream while a process is scaled to zero
(`:278`). nginx's stub listener is implemented in
`plugins/nginx-vhosts/functions:257`; its HTTP error mapping is in
`plugins/nginx-vhosts/templates/nginx.conf.sigil:133`.

The local feasibility probe on source `77ec0bea450c3b978e114a75e0db6cd18a1f982b`
with nginx 1.24.0 returned 502 and the bundled error page when API was zero.
Unsaved cloud probe [i3Mi9XskfMsQdGuLf](https://app.testrigor.com/test-suites/MwsfmyjDKaczwnB3G/runs/i3Mi9XskfMsQdGuLf)
passed WebSocket echo and observed HTTP/WebSocket Host `localhost:19080` through
the local tunnel. This is not a GitHub-hosted result. Hosted results must identify
their run URL and tested revision; see the fork PR checks for individual executions.
The local gating cases and negative controls above ran at source/harness revision
`d04ebd6bbb5cbbceb742a756d73f2404c297e130`; all seven gating controls failed their
assertions and agreed with the independent post-case checks. TC-09 stopped at
HTTP 404 during navigation; its wrong-state control is reported separately and
is not a proof that the later login-heading assertion executed.

TC-07 stays contract-pending: `docs/deployment/zero-downtime-deploys.md:15`
describes deployment switching, and `plugins/ps/ps.go:88` invokes deployment,
but no explicit guarantee for a continuous client of a routed non-web process
was established. TC-09 intentionally asserts a user expectation rather than a
documented redirect-rewrite contract and never runs in CI.

Retry limit: 2, confirmed by the suite owner on November 11, 2026. CLI 2.0.9's
`dist/commands/test-suite/run.js:170` accepts settings, but no authoritative retry
field/schema was found; no guessed settings file is sent. This is not retry-free
evidence. Negative controls run only during development and retain red results.

The previous hosted run [42880164031](https://github.com/AntonioVCruz/dokku/actions/runs/42880164031)
took 12m43s, including a 5m12s source build. Its five old lifecycle stages do not
validate these rewritten cases. Buildx/GitHub cache attempts took 10.48, 10.27
and 15.48 minutes before failing runtime-package installation with DNS errors
(runs 43036399471, 43036437004 and 43041069466). No successful cached comparison
was obtained, so the cache experiment was removed. Source timing is included in
each new run's build-timing JSON; no cost reduction is claimed from failed builds.
