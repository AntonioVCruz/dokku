# Browser deployment fixture

This harness builds Dokku from a pinned source revision and deploys a small
web/API fixture through its CLI. Infrastructure probes do not establish browser
execution or testRigor reliability. No cloud run is part of the installer scripts.

Use Linux Bash, Docker Engine and Docker Compose. On Windows, run the scripts
through WSL with Docker Desktop integration enabled. Shell files must use LF.

```shell
export DOKKU_SOURCE_REVISION=$(git rev-parse HEAD)
bash tests/E2E/scripts/build-dokku.sh /path/to/private/artifacts
export DOKKU_E2E_IMAGE="dokku-e2e/source:${DOKKU_SOURCE_REVISION:0:9}"
bash tests/E2E/scripts/install-dokku.sh install
bash tests/E2E/scripts/install-dokku.sh status
```

The Compose project `dokku-browser-e2e` owns a separate privileged Docker-in-Docker
daemon. Dokku uses that daemon's socket; it never receives the host Docker socket.
The engine and Dokku share a network namespace so nginx can reach nested app
containers. Three named volumes hold daemon images, its socket, and Dokku state.
Only loopback ports are published: HTTP 19080, HTTPS 19443 and SSH 13022. HTTPS and
SSH are reserved mappings, not verified capabilities. No SSH key is installed.

The installer creates the reserved `browser-probe` app and preserves its marker on
repeat installation. It builds the fixture image inside the isolated daemon,
deploys it with `git:from-image`, scales web/API processes, and configures
`/api/v0` to reach the API process. The default URL is `http://127.0.0.1:19080`.
The page loads JavaScript; clicking **Check backend** should display the generated
backend marker. Browser execution and cloud connectivity require separate checks.

Available actions are `install`, `status`, `probe`, `logs`, `restart`, and `reset`.
Readiness and response polling are bounded and conditional. `restart` restarts
the fixture's processes. `reset` destroys only the owned reserved fixture app,
then recreates it with a new marker. It preserves Dokku/engine volumes, existing
credentials, image caches and other apps; it is not a factory reset. Never run a
global Docker prune or remove shared volumes to reset this fixture.

Record image IDs/digests, source SHA, harness hashes and local verification logs
in the private project artifacts directory. Image defaults are versioned tags;
record resolved digests and pin them for any later reliability evidence.

## First browser case

`TC-01 Browser renders the routed backend identity` verifies that clicking
**Check backend** replaces the initial page status with the fixture's exact API
marker. The marker must be read from Dokku's `E2E_MARKER` configuration before a
run and supplied as `expectedBackendMarker` through a private variables file.
Do not learn the expected value from the HTTP response being tested or commit a
live marker. The checked-in `variables.json` is intentionally empty.

This case only reads backend state. Each browser starts on a fresh page; there
is no persistent write to clean up. TestRigor assertions provide conditional
waiting without sleeps.
Syntax validation does not prove browser execution. Cloud runs require an
approved scope, and suite replacement needs separate explicit approval.

## Lifecycle profiles

Phase 4 adds two cases for distinct externally prepared states. Do not run every
case against the same state: TC-02 requires a removed route, while TC-01 and
TC-03 require a healthy route. Start sequentially and select one case label per
run. The browser cannot and must not administer Dokku through the fixture page.

| Profile | Preparation through Dokku CLI | Browser case | Cleanup |
| --- | --- | --- | --- |
| Baseline | Verify the owned app and `/api/v0 -> api:5001` route | TC-01, `dokku-browser-smoke` | None |
| Process restart | `ps:restart browser-probe`; wait for the original API identity | TC-01, `dokku-browser-smoke` | Verify original marker and route |
| Configuration rollout | Save original `E2E_MARKER`; generate a unique replacement; `config:set browser-probe E2E_MARKER=<replacement>`; wait for rollout | TC-03, `dokku-config-rollout` | Restore original marker using `config:set`; verify API identity |
| Route removed | First run the healthy TC-01 control; `proxy:route:remove browser-probe /api/v0`; wait for API 404 and web page 200 | TC-02, `dokku-route-removed` | `proxy:route:set browser-probe api /api/v0 --port 5001`; verify API identity and run TC-01 recovery control |

Before every mutation, check `E2E_FIXTURE_OWNER=dokku-browser-e2e`, the source
revision, image, and exact original route. Record the original marker and route
privately before changing anything. Restore in a controller `finally` block or
shell trap even if a browser run fails. Keep the same suite lock across profile
preparation, browser execution, and restoration. Never run these operations on
shared applications or use global configuration commands.

For TC-03, supply the new configured marker as `expectedBackendMarker` and the
original marker as `previousBackendMarker` in the private variables file. Require
different nonempty values. For TC-02, supply the original configured marker as
`expectedBackendMarker`; the exact 404 error comes from this fixture's web
process after the API route is removed. Pair the negative case with healthy
controls so an application that always fails cannot satisfy the full scenario.

Native coverage already exercises route creation/removal and prefix handling in
`tests/unit/proxy-route-nginx.bats`, process lifecycle in
`tests/unit/ps-dockerfile-1.bats`, and configuration commands in
`tests/unit/config.bats`. These profiles add browser JavaScript execution and
rendered response checks after actual Dokku operations. They do not establish
zero downtime, continuity within an already-open tab, or new native feature
coverage. Restart reuses TC-01 instead of adding a duplicate case.

No reusable rule is introduced for the few short assertions: preserving the
Phase 3 TC-01 definition avoids changing its recorded evidence. TC-02 and TC-03
need separate validation and browser evidence. Five consecutive passing complete
cycles are required before claiming reliability for the expanded lifecycle
scope; changing case/harness/profile inputs or a failing stage resets the count.
Generate the replacement marker once per campaign and freeze both marker values
and both private variables files across the five-cycle streak. Reuse those exact
profiles in the same order; changing a marker or variables file resets the count.

No suite settings file is supplied yet. The exposed suite metadata does not
provide a complete settings snapshot, so inventing settings keys or passing a
new settings file would not establish reproducibility. The observed profile is
private Desktop Web Chrome, one node, automatic retries enabled with unknown
count. Stored settings comparison and a reviewed export remain dependencies.
Preserve that limitation in evidence; never silently change suite settings.

## Opt-in CI draft

See [CI.md](CI.md) for the PR/manual workflow, configuration gate, dedicated
suite requirement, ownership decisions, artifact policy and verification limits.
Hosted connectivity and the portable CI runner remain unverified until an
approved hosted run. Phase 4 workstation results do not establish a hosted pass.
