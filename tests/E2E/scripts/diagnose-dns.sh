#!/usr/bin/env bash
set -euo pipefail

probe() {
  printf '\nDNS_PROBE %s\n' "$1"
  shift
  local code=0
  "$@" || code=$?
  printf 'DNS_PROBE_EXIT=%s\n' "$code"
}

probe 'runner resolv.conf' cat /etc/resolv.conf
probe 'runner upstream resolv.conf' cat /run/systemd/resolve/resolv.conf
probe 'runner DNS status' resolvectl status
probe 'Docker version' docker version
probe 'Buildx version' docker buildx version
probe 'Buildx inspect' docker buildx inspect
probe 'Alpine DNS' docker run --rm alpine nslookup github.com
probe 'runtime base DNS' docker run --rm --entrypoint bash phusion/baseimage:noble-1.0.3 -lc \
  'cat /etc/resolv.conf; for host in github.com archive.ubuntu.com security.ubuntu.com; do getent ahostsv4 "$host"; done'

context=$(mktemp -d)
trap 'rm -f "$context/Dockerfile"; rmdir "$context"' EXIT
cat >"$context/Dockerfile" <<'DOCKERFILE'
FROM phusion/baseimage:noble-1.0.3
RUN cat /etc/resolv.conf && getent ahostsv4 github.com && getent ahostsv4 archive.ubuntu.com && getent ahostsv4 security.ubuntu.com
DOCKERFILE
probe 'BuildKit runtime-base DNS' docker build --progress plain "$context"

# Diagnostic exit codes are recorded; the following source build remains mandatory.
