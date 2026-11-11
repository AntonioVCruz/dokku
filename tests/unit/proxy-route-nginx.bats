#!/usr/bin/env bats

load test_helper

setup() {
  global_setup
  create_app
}

teardown() {
  dokku proxy:route:clear "$TEST_APP" >/dev/null 2>&1 || true
  destroy_app
  global_teardown
}

@test "(proxy-route:nginx) basic routing - /api/v0 hits api, / hits web" {
  run deploy_app python "dokku@$DOKKU_DOMAIN:$TEST_APP" add_api_process_callback
  echo "output: $output"
  echo "status: $status"
  assert_success

  run /bin/bash -c "dokku ps:scale $TEST_APP web=1 api=1"
  echo "output: $output"
  echo "status: $status"
  assert_success

  run /bin/bash -c "dokku proxy:route:set $TEST_APP api /api/v0 --port 5001"
  echo "output: $output"
  echo "status: $status"
  assert_success

  # Without --strip-prefix, /api/v0/Procfile reaches api as /api/v0/Procfile.
  # api (python's http.server) does not have that file on disk and returns
  # 404. A 404 here proves the route reaches api - web's catch-all would
  # have returned 200 instead.
  assert_http_localhost_response_contains "http" "${TEST_APP}.${DOKKU_DOMAIN}" "80" "/api/v0/Procfile" "" "404"
}

@test "(proxy-route:nginx) --strip-prefix toggles upstream path visibility" {
  run deploy_app python "dokku@$DOKKU_DOMAIN:$TEST_APP" add_api_process_callback
  echo "output: $output"
  echo "status: $status"
  assert_success

  run /bin/bash -c "dokku ps:scale $TEST_APP web=1 api=1"
  echo "output: $output"
  echo "status: $status"
  assert_success

  # Without --strip-prefix, /api/v0/Procfile is forwarded as-is to api,
  # which does not have an /api/v0/Procfile file on disk.
  run /bin/bash -c "dokku proxy:route:set $TEST_APP api /api/v0 --port 5001"
  assert_success
  assert_http_localhost_response_contains "http" "${TEST_APP}.${DOKKU_DOMAIN}" "80" "/api/v0/Procfile" "" "404"

  # With --strip-prefix, /api/v0/Procfile becomes /Procfile upstream and api
  # returns the Procfile content.
  run /bin/bash -c "dokku proxy:route:set $TEST_APP api /api/v0 --port 5001 --strip-prefix"
  assert_success
  assert_http_localhost_response_contains "http" "${TEST_APP}.${DOKKU_DOMAIN}" "80" "/api/v0/Procfile" "python3 -m http.server"
}

@test "(proxy-route:nginx) removing a route falls back to web" {
  run deploy_app python "dokku@$DOKKU_DOMAIN:$TEST_APP" add_api_process_callback
  echo "output: $output"
  echo "status: $status"
  assert_success

  run /bin/bash -c "dokku ps:scale $TEST_APP web=1 api=1"
  assert_success

  # First set the route without --strip-prefix so a 404 from api uniquely
  # identifies that the route reached api (avoids racing with web's catch-all
  # 200 during the brief window before nginx fully reloads).
  run /bin/bash -c "dokku proxy:route:set $TEST_APP api /api/v0 --port 5001"
  assert_success
  assert_http_localhost_response_contains "http" "${TEST_APP}.${DOKKU_DOMAIN}" "80" "/api/v0/Procfile" "" "404"

  # Now switch the route to --strip-prefix and assert api serves the Procfile.
  run /bin/bash -c "dokku proxy:route:set $TEST_APP api /api/v0 --port 5001 --strip-prefix"
  assert_success
  assert_http_localhost_response_contains "http" "${TEST_APP}.${DOKKU_DOMAIN}" "80" "/api/v0/Procfile" "python3 -m http.server"

  run /bin/bash -c "dokku proxy:route:remove $TEST_APP /api/v0"
  echo "output: $output"
  echo "status: $status"
  assert_success

  # Confirm storage was actually mutated; a CommandRouteRemove that returns
  # changed=false silently skips BuildConfig and leaves nginx with the old
  # route block.
  run /bin/bash -c "dokku proxy:route:report $TEST_APP"
  echo "output: $output"
  echo "status: $status"
  assert_success
  assert_output_contains "(none)"

  # nginx reload races with the curl after route removal: both api and web
  # return 200 for /api/v0/Procfile so the polling loop in
  # assert_http_localhost_response_contains exits on status alone before
  # nginx picks up the new config. Hand-roll a retry that polls the BODY
  # written to a file (avoids shell-quoting issues with JSON bodies that
  # contain embedded double quotes).
  rm -f /tmp/route-removed-body
  local attempt=0
  for attempt in $(seq 1 30); do
    curl --connect-to "${TEST_APP}.${DOKKU_DOMAIN}:80:localhost:80" -kSso /tmp/route-removed-body "http://${TEST_APP}.${DOKKU_DOMAIN}:80/api/v0/Procfile" || true
    if ! grep -q 'python3 -m http.server' /tmp/route-removed-body 2>/dev/null; then
      break
    fi
    sleep 1
  done
  run /bin/bash -c "grep -c 'python3 -m http.server' /tmp/route-removed-body || true"
  assert_output "0"
}

@test "(proxy-route:nginx) websocket upgrade headers are present in rendered config" {
  run deploy_app python "dokku@$DOKKU_DOMAIN:$TEST_APP" add_api_process_callback
  assert_success
  run /bin/bash -c "dokku ps:scale $TEST_APP web=1 api=1"
  assert_success
  run /bin/bash -c "dokku proxy:route:set $TEST_APP api /api/v0 --port 5001"
  assert_success

  run /bin/bash -c "dokku nginx:show-config $TEST_APP"
  echo "output: $output"
  echo "status: $status"
  assert_success
  assert_output_contains "location /api/v0"
  # These headers appear in both the route's location block AND the existing
  # location / block, so allow >= 1 occurrence (count = -1) rather than the
  # default exact-count-of-1.
  assert_output_contains "proxy_http_version 1.1" -1
  assert_output_contains "proxy_set_header Upgrade \$http_upgrade" -1
  assert_output_contains "proxy_set_header Connection \$http_connection" -1
}

@test "(proxy-route:nginx) route survives process restart" {
  run deploy_app python "dokku@$DOKKU_DOMAIN:$TEST_APP" add_lifecycle_api_process_callback
  echo "output: $output"
  assert_success
  run dokku ps:scale "$TEST_APP" web=1 api=1
  assert_success
  run dokku proxy:route:set "$TEST_APP" api /api/v0 --port 5001 --strip-prefix
  assert_success
  assert_routed_response "/api/v0/routing.txt" "short-prefix"

  run dokku ps:restart "$TEST_APP"
  echo "output: $output"
  assert_success
  assert_routed_response "/api/v0/routing.txt" "short-prefix"
}

@test "(proxy-route:nginx) configuration rollout reaches routed process" {
  run deploy_app python "dokku@$DOKKU_DOMAIN:$TEST_APP" add_lifecycle_api_process_callback
  echo "output: $output"
  assert_success
  run dokku ps:scale "$TEST_APP" web=1 api=1
  assert_success
  run dokku proxy:route:set "$TEST_APP" api /api/v0 --port 5001 --strip-prefix
  assert_success
  run dokku config:set "$TEST_APP" ROUTE_TEST_MARKER=before-rollout
  assert_success
  assert_routed_response "/api/v0/identity" "api:before-rollout"

  run dokku config:set "$TEST_APP" ROUTE_TEST_MARKER=after-rollout
  echo "output: $output"
  assert_success
  assert_routed_response "/api/v0/identity" "api:after-rollout"
}

@test "(proxy-route:nginx) remove then re-add restores routing" {
  run dokku config:set --no-restart "$TEST_APP" ROUTE_TEST_MARKER=web-fallback-control
  assert_success
  run deploy_app python "dokku@$DOKKU_DOMAIN:$TEST_APP" add_lifecycle_api_process_callback
  echo "output: $output"
  assert_success
  run dokku ps:scale "$TEST_APP" web=1 api=1
  assert_success
  run dokku proxy:route:set "$TEST_APP" api /api/v0 --port 5001 --strip-prefix
  assert_success
  assert_routed_response "/api/v0/routing.txt" "short-prefix"
  run dokku proxy:route:remove "$TEST_APP" /api/v0
  assert_success
  # Unlike api's static file, web's catch-all returns its environment.
  assert_routed_response "/api/v0/routing.txt" '"ROUTE_TEST_MARKER": "web-fallback-control"'

  run dokku proxy:route:set "$TEST_APP" api /api/v0 --port 5001 --strip-prefix
  echo "output: $output"
  assert_success
  assert_routed_response "/api/v0/routing.txt" "short-prefix"
}

@test "(proxy-route:nginx) longest overlapping prefix wins on live requests" {
  run deploy_app python "dokku@$DOKKU_DOMAIN:$TEST_APP" add_lifecycle_api_process_callback
  echo "output: $output"
  assert_success
  run dokku ps:scale "$TEST_APP" web=1 api=1 admin=1
  assert_success
  run dokku proxy:route:set "$TEST_APP" api /api/v0 --port 5001 --strip-prefix
  assert_success
  # The short route cannot serve the admin marker: its /admin directory is absent.
  assert_http_localhost_response_contains "http" "${TEST_APP}.${DOKKU_DOMAIN}" "80" "/api/v0/admin/routing.txt" "" "404"
  run dokku proxy:route:remove "$TEST_APP" /api/v0
  assert_success
  run dokku proxy:route:set "$TEST_APP" admin /api/v0/admin --port 5002 --strip-prefix
  assert_success
  # Add the shorter route last so declaration order cannot explain precedence.
  run dokku proxy:route:set "$TEST_APP" api /api/v0 --port 5001 --strip-prefix
  assert_success
  assert_routed_response "/api/v0/routing.txt" "short-prefix"
  assert_routed_response "/api/v0/admin/routing.txt" "long-prefix"
}

add_lifecycle_api_process_callback() {
  local APP="$1"
  local APP_REPO_DIR="$2"
  add_api_process_callback "$APP" "$APP_REPO_DIR"
  convert_to_dockerfile "$APP" "$APP_REPO_DIR"
  # A small live endpoint reads the environment of the routed process itself.
  sed -i 's/api: python3 -m http.server 5001/api: python3 api.py/' "$APP_REPO_DIR/Procfile"
  cat >"$APP_REPO_DIR/api.py" <<'PY'
import http.server
import os


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/identity':
            # web's environment dump contains the marker too; identify api explicitly.
            body = ('api:' + os.environ.get('ROUTE_TEST_MARKER', 'unset')).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()


http.server.HTTPServer(('0.0.0.0', 5001), Handler).serve_forever()
PY
  echo short-prefix >"$APP_REPO_DIR/routing.txt"
  # Keep this directory distinct from /admin so api cannot serve the same marker
  # when the shorter prefix incorrectly wins.
  mkdir -p "$APP_REPO_DIR/admin-docroot"
  echo long-prefix >"$APP_REPO_DIR/admin-docroot/routing.txt"
  echo "admin: python3 -m http.server 5002 --directory admin-docroot" >>"$APP_REPO_DIR/Procfile"
}

assert_routed_response() {
  local path="$1" expected="$2" body attempt
  # Both upstreams return 200; status-only polling can observe the old worker.
  # Wait for the exact body condition before applying the shared assertions.
  for attempt in $(seq 1 30); do
    body=$(curl --connect-to "${TEST_APP}.${DOKKU_DOMAIN}:80:localhost:80" -kfSs "http://${TEST_APP}.${DOKKU_DOMAIN}:80$path") || true
    [[ "$body" == *"$expected"* ]] && break
    sleep 1
  done
  assert_http_localhost_response_contains "http" "${TEST_APP}.${DOKKU_DOMAIN}" "80" "$path" "$expected"
}

add_api_process_callback() {
  local APP="$1"
  local APP_REPO_DIR="$2"
  # api serves /app's working directory on port 5001. GET /Procfile returns
  # the literal Procfile bytes, which web.py does not serve - this gives the
  # HTTP assertions a clear marker for which process handled the request.
  echo "api: python3 -m http.server 5001" >>"$APP_REPO_DIR/Procfile"
}
