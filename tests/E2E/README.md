# Browser routing tests

This optional suite tests nginx path routing to non-web processes through a
source-built Dokku instance. See [COVERAGE.md](COVERAGE.md) for native overlap,
oracles, negative controls and contract limits. Seven cases gate CI; the redirect
characterization is separate and never gates it.

## Run locally

Requires Linux, Docker Engine with Compose, Python 3 and the Node version in
`.node-version`. Use an exclusively reserved private Desktop Web Chrome suite.

```shell
npm ci --prefix tests/E2E
export DOKKU_SOURCE_REVISION=$(git rev-parse HEAD)
export DOKKU_E2E_IMAGE=dokku-e2e/source:${DOKKU_SOURCE_REVISION:0:9}
export DOKKU_HARNESS_BRANCH=$(git branch --show-current)
bash tests/E2E/scripts/build-dokku.sh /private/artifacts
bash tests/E2E/scripts/install-dokku.sh install
# Set TESTRIGOR_SUITE_ID and TESTRIGOR_API_KEY privately; never put tokens in arguments.
python3 tests/E2E/scripts/run-ci.py /private/artifacts/positive
```

The installer owns only the reserved `browser-probe` app. It checks source
revision and ownership, preserves its configured marker on repeat installation,
and deploys web/API/WebSocket processes in a separate Docker daemon. Only
loopback ports 19080, 19443 and 13022 are published; HTTP is the tested interface.
The host Docker socket is never mounted into Dokku. No endpoint runs Dokku commands.
Installer actions: `install`, `status`, `probe`, `logs`, `restart`, `reset`.
Reset recreates only the owned fixture app; it preserves daemon/state volumes.

The controller prepares states in order: baseline, restart, configuration rollout,
route removal, re-addition, WebSocket route, then API scaled to zero. Readiness
uses web `/healthz` and `nginx -t`, never the case outcome. Expected markers come
from configuration, prior hostname from container inspection, and error text from
the repository template. After each browser verdict, HTTP/upgrade checks must
agree or the run fails with `oracle disagreement`. Finally, original marker,
routes and process scale are restored and checked, including on failure.

```shell
# Development only: wrong-state controls must fail their browser assertions.
python3 tests/E2E/scripts/run-ci.py /private/artifacts/negative --negative-controls
# Never included in the gating sequence; retain its failure as characterization.
python3 tests/E2E/scripts/run-ci.py /private/artifacts/redirect --cases 9
```

## CI and service settings

Configure variable `TESTRIGOR_SUITE_ID` and secret `TESTRIGOR_CI_TOKEN` on the
repository. The gate receives only a token-presence boolean, without checkout.
The token is passed only to CLI children by the runner, redacted from their logs,
and excluded from Docker commands, files and uploaded artifacts. Checkout does
not persist credentials. Actions are pinned by SHA; permissions are read-only.

Eligible same-repository PRs use path filters; manual dispatch and weekly
default-branch schedules are also supported. Missing configuration and fork PRs
emit a notice and summary, then skip. Per-suite concurrency never cancels an
active run. Reserve the suite against external/manual clients too: starting
another testRigor run can cancel one already using it.

The suite owner confirmed two automatic retries on November 11, 2026. The CLI
accepts settings JSON/YAML but exposes no validated retry key. No settings file
is guessed or sent. Retry-free execution remains unverified; see COVERAGE.md.
Ordinary runs omit `--explicit-mutations`, preserving saved suite objects.

JUnit, redacted CLI logs, provenance and build diagnostics are retained for seven
days. Variables and CLI home are excluded. One hosted success proves only that
revision and execution; a local pass does not establish hosted compatibility.
No hosted result is claimed without its run URL.

Offline checks: `python3 tests/E2E/scripts/test_ci.py`, actionlint, repository
yamllint, shfmt (`-bn -ci -i 2`) and `bash -n` on the scripts.
