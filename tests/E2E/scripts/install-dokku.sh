#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
action=${1:-install}
app=${DOKKU_E2E_APP:-browser-probe}
expected_revision=${DOKKU_SOURCE_REVISION:-$(git -C "$root" rev-parse HEAD)}
: "${DOKKU_E2E_IMAGE:?Set DOKKU_E2E_IMAGE to the source-built image}"
[[ "$app" =~ ^browser-probe(-[a-z0-9-]+)?$ ]] || { echo 'Use a reserved browser-probe app name' >&2; exit 1; }
compose() { docker compose -f "$root/compose.yml" "$@"; }
dokku() { compose exec -T dokku dokku "$@"; }

wait_ready() {
  local deadline=$((SECONDS + 600))
  until compose exec -T dokku curl -fsS http://127.0.0.1:18080/_dokku/health >/dev/null 2>&1; do
    if ((SECONDS >= deadline)); then
      compose logs --tail 100 >&2
      echo 'Dokku readiness timed out' >&2
      return 1
    fi
    sleep 2
  done
  local actual
  actual=$(compose exec -T dokku cat /var/lib/dokku/GIT_REV | tr -d '\r\n')
  [[ "$actual" == "$expected_revision" ]] || { echo "Wrong source revision: $actual" >&2; return 1; }
}

assert_owned() {
  local owner
  owner=$(dokku config:get "$app" E2E_FIXTURE_OWNER | tr -d '\r\n')
  [[ "$owner" == dokku-browser-e2e ]] || { echo "Refusing to change unowned app: $app" >&2; return 1; }
}

probe() {
  local deadline=$((SECONDS + 120)) marker body
  marker=$(dokku config:get "$app" E2E_MARKER | tr -d '\r\n')
  [[ -n "$marker" ]] || return 1
  until body=$(compose exec -T dokku curl -fsS http://127.0.0.1/api/v0/identity) &&
    [[ "$body" == *"$marker"* && "$body" == *'"role": "api"'* ]]; do
    ((SECONDS < deadline)) || { echo 'Backend probe timed out' >&2; return 1; }
    sleep 2
  done
  compose exec -T dokku curl -fsS http://127.0.0.1/ | grep -q 'Backend not checked'
  compose exec -T dokku curl -fsS http://127.0.0.1/probe.js | grep -q '/api/v0/identity'
  printf 'LOCAL_HTTP_PROBE=passed\nFIXTURE_APP=%s\nFIXTURE_MARKER=%s\nLOCAL_URL=http://127.0.0.1:%s\n' \
    "$app" "$marker" "${DOKKU_E2E_HTTP_PORT:-19080}"
}

install() {
  compose up -d
  wait_ready
  local marker fixture_hash fixture_image
  if dokku apps:exists "$app"; then
    assert_owned
    marker=$(dokku config:get "$app" E2E_MARKER | tr -d '\r\n')
    [[ -n "$marker" ]] || { echo 'Existing fixture marker is missing' >&2; return 1; }
  else
    dokku apps:create "$app"
    marker="dokku-backend-$(cat /proc/sys/kernel/random/uuid)"
    dokku config:set --no-restart "$app" E2E_FIXTURE_OWNER=dokku-browser-e2e E2E_MARKER="$marker"
  fi
  # Stable content tags make repeat installation a no-op deployment.
  fixture_hash=$(cd "$root/fixture" && sha256sum Dockerfile Procfile server.py | sha256sum | cut -c1-16)
  fixture_image="dokku-e2e/fixture:$fixture_hash"
  if ! compose exec -T dokku docker image inspect "$fixture_image" >/dev/null 2>&1; then
    tar -C "$root/fixture" -cf - Dockerfile Procfile server.py |
      compose exec -T dokku docker build -t "$fixture_image" -
  fi
  if [[ "$(dokku domains:report "$app" --domains-app-enabled)" != true ]]; then
    dokku domains:enable "$app"
  fi
  dokku domains:set "$app" localhost 127.0.0.1
  dokku ports:set "$app" http:80:5000
  if [[ "$(dokku git:report "$app" --git-source-image)" != "$fixture_image" ]]; then
    dokku git:from-image "$app" "$fixture_image"
  elif [[ "$(dokku ps:report "$app" --deployed)" != true ]]; then
    dokku ps:rebuild "$app"
  else
    echo 'Fixture image already deployed; preserving existing revision'
  fi
  dokku ps:scale "$app" web=1 api=1
  dokku proxy:route:set "$app" api /api/v0 --port 5001
  probe
}

case "$action" in
  install) install ;;
  status)
    compose ps
    wait_ready
    dokku ps:report "$app"
    dokku proxy:route:report "$app"
    probe
    ;;
  probe) wait_ready; assert_owned; probe ;;
  logs) compose logs --tail 100; dokku logs "$app" -n 100 ;;
  restart)
    wait_ready
    assert_owned
    dokku ps:restart "$app"
    probe
    ;;
  reset)
    wait_ready
    if dokku apps:exists "$app"; then
      assert_owned
      dokku --force apps:destroy "$app"
    fi
    install
    ;;
  *) echo 'Usage: install-dokku.sh [install|status|probe|logs|restart|reset]' >&2; exit 2 ;;
esac
