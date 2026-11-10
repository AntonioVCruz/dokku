"""One sequential lifecycle cycle using a dedicated CI suite; Linux, stdlib only."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def execute(artifacts):
  token = os.environ['TESTRIGOR_API_KEY']
  suite = os.environ['TESTRIGOR_SUITE_ID']
  if not token.strip() or not re.fullmatch(r'[A-Za-z0-9_-]+', suite):
    raise ValueError('Nonempty CI token and valid dedicated suite ID required')
  image = os.environ['DOKKU_E2E_IMAGE']
  revision = os.environ['DOKKU_SOURCE_REVISION']
  artifacts.mkdir(parents=True, exist_ok=False)
  # Tokens are passed only to CLI children, never Docker, commands, or files.
  local_env = {k: v for k, v in os.environ.items() if k != 'TESTRIGOR_API_KEY'}
  cli_env = os.environ.copy()
  cli_env['TESTRIGOR_CLI_HOME'] = str(artifacts / 'cli-home')
  compose = ['docker', 'compose', '-f', str(ROOT / 'compose.yml')]
  results = []

  def command(args):
    result = subprocess.run(args, cwd=REPO, env=local_env, capture_output=True,
                text=True, encoding='utf-8', errors='replace', check=True)
    return result.stdout.strip()

  def dokku(*args):
    return command(compose + ['exec', '-T', 'dokku', 'dokku', *args])

  def wait_api(marker, absent=False):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
      try:
        with urllib.request.urlopen('http://localhost:19080/api/v0/identity', timeout=10) as response:
          if not absent and json.load(response) == {'role': 'api', 'marker': marker}:
            return
      except urllib.error.HTTPError as error:
        if absent and error.code == 404 and error.read() == b'Wrong upstream or path':
          return
      except (OSError, ValueError):
        pass
      time.sleep(1)
    raise RuntimeError('Local API readiness condition timed out')

  def run_case(stage, filename, label, variables):
    folder = artifacts / stage
    folder.mkdir()
    values = folder / 'variables.json'
    values.write_text(json.dumps(variables), encoding='utf-8')
    case = ROOT / 'test-cases' / filename
    # Strict syntax validation does not execute or replace suite objects.
    validation = ['testrigor', 'test-suite', 'validate-syntax', suite,
           '--test-cases-path', str(case), '--explicit-mutations']
    args = ['testrigor', 'test-suite', 'run', suite, '--localhost', '--url', 'http://localhost:19080',
        '--test-cases-path', str(case), '--variables-path', str(values), '--labels', label,
        '--branch', os.environ['DOKKU_HARNESS_BRANCH'], '--commit', revision,
        '--min-port', '48196', '--max-port', '48196',
        '--junit-report-save-path', str(folder / 'report.xml')]
    exit_code = None
    for name, argv in [('validation', validation), ('cli', args)]:
      with (folder / (name + '.log')).open('w', encoding='utf-8') as log:
        process = subprocess.Popen(argv, cwd=REPO, env=cli_env, stdin=subprocess.DEVNULL,
          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        for line in process.stdout:
          safe = line.replace(token, '[REDACTED]')
          log.write(safe); log.flush(); print(safe, end='', flush=True)
        exit_code = process.wait()
      if exit_code:
        results.append({'stage': stage, 'operation': name, 'exitCode': exit_code})
        raise RuntimeError(stage + ' ' + name + ' failed')
    tree = ET.parse(folder / 'report.xml')
    counts = {name: len(tree.findall('.//' + tag)) for name, tag in
         [('tests', 'testcase'), ('failures', 'failure'), ('errors', 'error'), ('skipped', 'skipped')]}
    run_id = next((e.get('value') for e in tree.iter() if e.get('name') == 'taskId'), None)
    results.append({'stage': stage, 'exitCode': exit_code, 'junit': counts, 'runID': run_id})
    if counts != {'tests': 1, 'failures': 0, 'errors': 0, 'skipped': 0} or not run_id:
      raise RuntimeError(stage + ' did not produce one passing test and a run ID')

  cli_version = subprocess.check_output(['testrigor', '--version'], env=cli_env, text=True).strip()
  if '/2.0.9 ' not in cli_version:
    raise RuntimeError('Expected testRigor CLI 2.0.9')
  if command(['git', 'rev-parse', 'HEAD']) != revision:
    raise RuntimeError('Checkout differs from requested source revision')
  if command(compose + ['exec', '-T', 'dokku', 'cat', '/var/lib/dokku/GIT_REV']) != revision:
    raise RuntimeError('Installed Dokku revision differs from checkout')
  if dokku('config:get', 'browser-probe', 'E2E_FIXTURE_OWNER') != 'dokku-browser-e2e':
    raise RuntimeError('Refusing to change an unowned app')
  original = dokku('config:get', 'browser-probe', 'E2E_MARKER')
  route = dokku('proxy:route:report', 'browser-probe')
  if not original.startswith('dokku-backend-') or route.count('/api/v0') != 1 or '-> api:5001' not in route:
    raise RuntimeError('Unexpected fixture state')
  replacement = 'dokku-backend-' + str(uuid.uuid4())
  files = {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
      for p in ROOT.rglob('*') if p.is_file()}
  provenance = {'sourceRevision': revision, 'harnessRevision': command(['git', 'rev-parse', 'HEAD']),
    'harnessHashes': files, 'cliVersion': cli_version, 'url': 'http://localhost:19080',
    'runtimeImage': json.loads(command(['docker', 'image', 'inspect', image, '--format', '{{json .}}'])),
    'originalMarker': original, 'replacementMarker': replacement, 'suiteID': suite,
    'automaticRetries': 'Inherited settings; verify and record before hosted use', 'hostedConnectivity': 'unverified until this job succeeds'}
  (artifacts / 'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
  healthy = 'TC-01 Browser renders the routed backend identity.yaml'
  passed = False
  try:
    wait_api(original)
    run_case('baseline', healthy, 'dokku-browser-smoke', {'expectedBackendMarker': original})
    dokku('ps:restart', 'browser-probe'); wait_api(original)
    run_case('restart', healthy, 'dokku-browser-smoke', {'expectedBackendMarker': original})
    dokku('config:set', 'browser-probe', 'E2E_MARKER=' + replacement); wait_api(replacement)
    run_case('rollout', 'TC-03 Browser renders the rolled out configuration identity.yaml', 'dokku-config-rollout',
        {'expectedBackendMarker': replacement, 'previousBackendMarker': original})
    dokku('config:set', 'browser-probe', 'E2E_MARKER=' + original); wait_api(original)
    dokku('proxy:route:remove', 'browser-probe', '/api/v0'); wait_api(original, absent=True)
    run_case('route-removed', 'TC-02 Browser reports the removed backend route.yaml', 'dokku-route-removed',
        {'expectedBackendMarker': original})
    dokku('proxy:route:set', 'browser-probe', 'api', '/api/v0', '--port', '5001'); wait_api(original)
    run_case('recovered', healthy, 'dokku-browser-smoke', {'expectedBackendMarker': original})
    passed = True
  finally:
    failures = []
    for args in [('config:set', 'browser-probe', 'E2E_MARKER=' + original),
          ('proxy:route:set', 'browser-probe', 'api', '/api/v0', '--port', '5001')]:
      try:
        dokku(*args)
      except Exception as error:
        failures.append(type(error).__name__)
    try:
      wait_api(original)
      if dokku('proxy:route:report', 'browser-probe') != route:
        failures.append('Route differs after cleanup')
    except Exception as error:
      failures.append(type(error).__name__)
    (artifacts / 'result.json').write_text(json.dumps({'passed': passed and not failures,
      'stages': results, 'cleanupFailures': failures}, indent=2), encoding='utf-8')
    if failures:
      raise RuntimeError('Fixture cleanup failed')


if __name__ == '__main__':
  sys.stdout.reconfigure(encoding='utf-8', errors='replace')
  try:
    execute(Path(sys.argv[1]))
  except Exception as error:
    # Avoid printing HTTP/CLI objects or environment values on an error path.
    print('Browser lifecycle failed: ' + type(error).__name__, file=sys.stderr)
    sys.exit(1)
