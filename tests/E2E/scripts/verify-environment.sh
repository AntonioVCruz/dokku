#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
artifacts=${1:?Usage: verify-environment.sh PRIVATE_ARTIFACT_DIRECTORY}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$artifacts/evidence/local-environment-$stamp"
mkdir -p "$evidence" "$artifacts/backups"
exec > >(tee "$evidence/verification.log") 2>&1
logger_pid=$!
# WSL can otherwise terminate before the asynchronous logger flushes its last line.
trap 'result=$?; exec 1>&- 2>&-; wait "$logger_pid" || result=$?; exit "$result"' EXIT
compose() { docker compose -f "$root/compose.yml" "$@"; }
marker() { compose exec -T dokku dokku config:get "${DOKKU_E2E_APP:-browser-probe}" E2E_MARKER | tr -d '\r\n'; }
keys() { compose exec -T dokku bash -c 'sha256sum /etc/ssh/ssh_host_*_key.pub'; }
install() { bash "$root/scripts/install-dokku.sh" "$@"; }

date -u --iso-8601=seconds
git -C "$root" rev-parse HEAD
find "$root" -type f -print0 | sort -z | xargs -0 sha256sum >"$evidence/harness.sha256"
docker ps --format '{{.ID}} {{.Names}}' | sort >"$evidence/host-containers-before.txt"
install install
initial_marker=$(marker)
keys >"$evidence/ssh-public-key-hashes-before.txt"
install install
[[ "$(marker)" == "$initial_marker" ]] || { echo 'Repeat install changed marker' >&2; exit 1; }
echo 'REPEAT_INSTALL=passed'
install restart
[[ "$(marker)" == "$initial_marker" ]] || { echo 'Restart changed marker' >&2; exit 1; }
echo 'APP_RESTART=passed'
compose restart dokku
install probe
[[ "$(marker)" == "$initial_marker" ]] || { echo 'Dokku restart changed marker' >&2; exit 1; }
echo 'DOKKU_RESTART=passed'
python3 -m zipfile -c "$artifacts/backups/e2e-before-reset-$stamp.zip" "$root"
install reset
reset_marker=$(marker)
[[ "$reset_marker" != "$initial_marker" ]] || { echo 'Reset preserved transient fixture data' >&2; exit 1; }
keys >"$evidence/ssh-public-key-hashes-after.txt"
cmp "$evidence/ssh-public-key-hashes-before.txt" "$evidence/ssh-public-key-hashes-after.txt"
echo 'FIXTURE_RESET=passed'
echo 'SSH_HOST_KEYS_PRESERVED=passed'
install status
curl --fail --silent --show-error "http://127.0.0.1:${DOKKU_E2E_HTTP_PORT:-19080}/api/v0/identity" >"$evidence/host-api.json"
grep -Fq "$reset_marker" "$evidence/host-api.json"
echo 'HOST_LOOPBACK_HTTP=passed'
compose ps --format json >"$evidence/compose-status.json"
compose exec -T dokku cat /var/lib/dokku/GIT_REV >"$evidence/installed-source-revision.txt"
compose exec -T dokku docker image inspect "$(compose exec -T dokku dokku git:report "${DOKKU_E2E_APP:-browser-probe}" --git-source-image | tr -d '\r\n')" >"$evidence/fixture-image.json"
docker image inspect "$DOKKU_E2E_IMAGE" >"$evidence/source-image.json"
docker image inspect "$(compose images -q engine)" >"$evidence/engine-image.json"
docker ps --format '{{.ID}} {{.Names}}' | sort >"$evidence/host-containers-after.txt"
while read -r container_id container_name; do
  grep -Fxq "$container_id $container_name" "$evidence/host-containers-after.txt" || {
    echo "Pre-existing host container changed: $container_name" >&2
    exit 1
  }
done <"$evidence/host-containers-before.txt"
echo 'PREEXISTING_HOST_CONTAINERS_PRESERVED=passed'
printf '{"result":"passed","scope":"local infrastructure","cloudRuns":0}\n' >"$evidence/result.json"
printf 'PHASE2_LOCAL_VERIFICATION=passed\nEVIDENCE_DIRECTORY=%s\n' "$evidence"
