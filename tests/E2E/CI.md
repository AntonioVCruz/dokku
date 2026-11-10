# Opt-in browser CI

The workflow `.github/workflows/e2e-tests.yml` is a Phase 5 draft. Local/cloud
lifecycle evidence exists for the Phase 4 workstation profile. GitHub-hosted
builds, tunneling, runner capacity, duration and CI-token execution are **unverified**.
A workflow draft does not establish hosted connectivity or hosted reliability.

## Decisions for Dokku

| Decision | Choice and reason |
| --- | --- |
| Trigger | Pull requests, plus manual dispatch on the repository's default branch. Configured same-repository PRs run one lifecycle cycle; fork PRs skip. |
| Opt-in | Require a suite ID and a CI token. Missing either skips the browser job successfully. |
| Check policy | Advisory: do not add it to required branch checks initially. Test failures remain visible and fail the dispatched job; they are not converted to success. |
| Runtime | `ubuntu-24.04`, Node22.15.0, testRigor CLI2.0.9, the existing isolated Docker-in-Docker deployment and pinned engine digest. Build the checked-out Dokku source, not a substitute release image. |
| Browser access | The verified localhost CLI tunnel, targeting `http://localhost:19080` with port48196. Its behavior on a GitHub runner must be proved by an approved hosted run. No publicly exposed app is needed. |
| Coverage | One five-stage lifecycle cycle per eligible PR event or dispatch: baseline, restart, configuration rollout, route removal and recovery. It reuses the Phase 4 case definitions. |
| Limits | Job120 minutes, source-build step60, fixture install15, lifecycle30 and teardown5. Retain selected logs/JUnit/provenance for7 days. Actual hosted resource use and duration remain unmeasured. |
| Serialization | A stable `testrigor-<suite ID>` workflow concurrency group with `cancel-in-progress: false`; no branch component. It protects this repository's workflow runs, not external/manual clients or other repositories. |
| Suite mutation | No suite replacement and no saved settings file. Ordinary CLI runs send local case definitions/variables without `--explicit-mutations`. That flag is used only by the separate read-only syntax validator. |

The workflow follows this repository's Ubuntu runner, YAML and action naming
conventions, while pinning all three external actions to full commit SHAs.
Tokens are exposed only to the configuration gate and lifecycle step. GitHub
context strings enter shell commands through environment variables rather than
being interpolated into executable shell text.

## Configuration and ownership

Before enabling CI, the repository operator must designate a dedicated private
Desktop Web Chrome suite with one node, whose inherited cases/rules and settings
have been reviewed. Keep it separate from the workstation development suite.
The runner intentionally uses a suite CI token and does not use PAT-only MCP
operations or modify another project's CLI authentication/default suite.

Repository configuration:

- Secret `TESTRIGOR_CI_TOKEN`: a CI token belonging to the designated suite.
- Variable `TESTRIGOR_SUITE_ID`: that suite's ID.

The gate requires both plus either a same-repository pull request or manual
dispatch on the default branch. It never prints credentials. Fork PRs trigger
the gate but skip the browser job, including when configuration is absent.
The gate does not check out or execute PR scripts with its secret; its embedded
logic is checked against `ci-gate.py` by the offline tests. Missing credentials
never cause a privileged fallback. `pull_request_target` is not used.

PR runs build GitHub's checked-out merge revision (`github.sha`) and annotate
the run with the head branch name. No user-controlled branch name is interpolated
into executable shell text.

The suite owner, token custodian and failure-triage maintainer are **not yet
assigned**. These are maintainer decisions, not responsibilities assigned by
this draft. Before activation, record the suite owner, token holder, contact for
failures, accepted service terms/data visibility, retry settings/count, and
whether the check should ever become required. The exposed metadata in Phase 4
did not provide a full settings export; no settings keys have been invented here.

To rotate credentials, revoke the old CI token in the suite, create its
replacement, and update the repository secret through the approved account.
Do not put either token in shell arguments, reports or source files.

To disable browser runs, remove the suite ID variable or CI token secret. Remove
the workflow if retiring the integration. Let any active run finish and preserve its
evidence before retiring the suite. No removal is performed by this draft.

## Execution and evidence

The source builder archives the selected Git revision and builds its Debian
package and runtime image. The installer deploys the fixture through Dokku CLI
inside a separate Docker daemon. Only loopback ports are published; the host
Docker socket is not mounted into Dokku. This is the existing deployment design.

`scripts/run-ci.py` checks source provenance and fixture ownership, records
harness hashes and image identity, validates each selected case, then executes
one case per stage synchronously. Expected backend identities are seeded through
Dokku configuration. A positive baseline and final recovery control accompany
the route-removal case. Cleanup attempts to restore both the original marker and
route even on a stage failure. A failing CLI/JUnit result remains a failing job.

Each workflow run gets a unique runner-temp artifact directory and artifact name
based on run ID and attempt. Uploads include JUnit, redacted CLI output, selected
build/failure logs and provenance. Generated variables and CLI home/config are
excluded from uploads. The runner uses the token only in the CLI child's
environment and replaces its literal value in captured output.

Compose teardown is scoped to the owned project on the ephemeral runner. It does
not run global Docker prune or remove shared volumes. No existing workstation or
shared VM is part of hosted execution.

One successful CI cycle proves only that execution, not a five-cycle
reliability streak for a new hosted profile. Phase 4's evidence remains scoped to
its recorded workstation source/runtime/client. A new source or settings profile
needs its own evidence. Automatic retries, if enabled, must be disclosed.

## Coordination and first hosted run

Reserve the CI suite exclusively for this workflow before enabling PR runs. Do not run another repository,
manual browser run or local CLI client against it concurrently: starting a run
can cancel an existing one. GitHub concurrency does not coordinate those clients.
Do not cancel an active job to make room for another. A runner timeout or manual
termination can leave a cloud run active; check the suite UI and wait for it to
finish before dispatching again. There is no unverified claim of a distributed
suite lock or automatic cloud cancellation in this draft.

The first approved hosted run must verify source build resource use, container
startup, tunnel origin, the five case outcomes, cleanup, token permissions,
settings before/after and uploaded logs. An unexpected failure should be
classified as build/setup/network/test/application/unknown from actual evidence.
Do not treat the known nested-container advisory port-listening limitation as a
successful native check merely because browser probes pass.

Push, repository configuration changes, workflow activation and hosted dispatch
are separate outward-facing actions. Phase 5 prepares the files and local checks;
none of those actions has been performed.

## Local validation

Run the offline gate, lifecycle failure/cleanup and token-redaction checks with:

```shell
python3 tests/E2E/scripts/test_ci.py
```

These checks simulate external commands and HTTP responses. They do not build
Dokku, spend cloud runs or prove the portable runner on a hosted machine.
