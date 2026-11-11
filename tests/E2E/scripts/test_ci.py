"""Offline checks for CI gating, failure propagation, cleanup and token handling."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import urllib.error


def load(name):
  spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


class GateTests(unittest.TestCase):
  def test_workflow_uses_the_exact_gate_without_pr_checkout(self):
    root = Path(__file__).resolve().parents[3]
    workflow = (root / '.github/workflows/e2e-tests.yml').read_text()
    embedded = workflow.split("python3 - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
    self.assertEqual(textwrap.dedent(embedded).strip(), Path(__file__).with_name('ci-gate.py').read_text().strip())
    gate_job = workflow.split('  gate:\n', 1)[1].split('  browser:\n', 1)[0]
    self.assertNotIn('actions/checkout', gate_job)

  def test_gate_process_writes_skip_without_credentials(self):
    with tempfile.TemporaryDirectory() as directory:
      output = Path(directory) / 'github-output'
      result = subprocess.run([sys.executable, str(Path(__file__).with_name('ci-gate.py'))],
        env={'GITHUB_OUTPUT': str(output), 'GITHUB_EVENT_NAME': 'workflow_dispatch',
             'GITHUB_REF': 'refs/heads/master', 'DOKKU_DEFAULT_BRANCH': 'master'},
        capture_output=True, text=True, check=True)
      self.assertEqual(output.read_text(), 'enabled=false\n')
      self.assertIn('skipped', result.stdout)

  def test_missing_config_and_untrusted_events(self):
    gate = load('ci-gate')
    valid = {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/master',
             'DOKKU_DEFAULT_BRANCH': 'master',
             'TESTRIGOR_SUITE_ID': 'offline-suite', 'TESTRIGOR_TOKEN_PRESENT': 'true'}
    self.assertTrue(gate.evaluate(valid))
    for key in ('TESTRIGOR_SUITE_ID', 'TESTRIGOR_TOKEN_PRESENT', 'DOKKU_DEFAULT_BRANCH'):
      self.assertFalse(gate.evaluate({k: v for k, v in valid.items() if k != key}))
    for change in ({'GITHUB_EVENT_NAME': 'pull_request'}, {'GITHUB_EVENT_NAME': 'pull_request_target'},
                   {'GITHUB_REF': 'refs/heads/topic'},
                   {'TESTRIGOR_TOKEN_PRESENT': 'false'}):
      self.assertFalse(gate.evaluate(dict(valid, **change)))

  def test_same_repository_pr_runs_and_fork_or_missing_config_skips(self):
    gate = load('ci-gate')
    env = {'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REPOSITORY': 'owner/dokku',
           'DOKKU_PR_HEAD_REPOSITORY': 'owner/dokku',
           'TESTRIGOR_SUITE_ID': 'offline-suite', 'TESTRIGOR_TOKEN_PRESENT': 'true'}
    self.assertTrue(gate.evaluate(env))
    self.assertFalse(gate.evaluate(dict(env, DOKKU_PR_HEAD_REPOSITORY='fork/dokku')))
    for key in ('TESTRIGOR_SUITE_ID', 'TESTRIGOR_TOKEN_PRESENT'):
      self.assertFalse(gate.evaluate({k: v for k, v in env.items() if k != key}))


class RunnerTests(unittest.TestCase):
  def exercise(self, fault=None):
    runner = load('run-ci')
    self.calls = []
    state = {'marker': 'dokku-backend-original', 'route': True}
    token = 'offline-secret-never-log'
    revision = 'a' * 40

    def command(args, **kwargs):
      self.assertNotIn('TESTRIGOR_API_KEY', kwargs['env'])
      self.calls.append(args)
      output = ''
      if args[:3] == ['git', 'rev-parse', 'HEAD'] or '/var/lib/dokku/GIT_REV' in args:
        output = revision
      elif args[:3] == ['docker', 'image', 'inspect']:
        output = '{"Id":"offline-image"}'
      elif 'config:get' in args:
        output = 'dokku-browser-e2e' if args[-1] == 'E2E_FIXTURE_OWNER' else state['marker']
      elif 'config:set' in args:
        state['marker'] = args[-1].split('=', 1)[1]
      elif 'proxy:route:report' in args:
        output = 'Route /api/v0 -> api:5001' if state['route'] else '(none)'
      elif 'proxy:route:remove' in args:
        state['route'] = False
      elif 'proxy:route:set' in args:
        state['route'] = True
      return subprocess.CompletedProcess(args, 0, output, '')

    def http(*args, **kwargs):
      if state['route']:
        return io.BytesIO(json.dumps({'role': 'api', 'marker': state['marker']}).encode())
      raise urllib.error.HTTPError(args[0], 404, 'not found', {}, io.BytesIO(b'Wrong upstream or path'))

    class Process:
      def __init__(inner, args, **kwargs):
        self.calls.append(args)
        self.assertEqual(kwargs['env']['TESTRIGOR_API_KEY'], token)
        self.assertNotIn(token, ' '.join(args))
        inner.stdout = iter(['diagnostic ' + token + '\n'])
        inner.code = 0
        if args[2] == 'validate-syntax':
          if fault == 'syntax':
            inner.code = 1
          return
        stage = Path(args[args.index('--junit-report-save-path') + 1]).parent.name
        if stage == 'rollout' and fault == 'cli':
          inner.code = 9
        report = Path(args[args.index('--junit-report-save-path') + 1])
        failure = '<failure message="offline failure"/>' if stage == 'rollout' and fault == 'junit' else ''
        report.write_text('<testsuites><testsuite><testcase>' + failure + '</testcase>'
                          '<properties><property name="taskId" value="offline-run"/></properties>'
                          '</testsuite></testsuites>', encoding='utf-8')

      def wait(inner):
        return inner.code

    env = {'TESTRIGOR_API_KEY': token, 'TESTRIGOR_SUITE_ID': 'offline-suite',
           'DOKKU_SOURCE_REVISION': revision, 'DOKKU_E2E_IMAGE': 'offline-image',
           'DOKKU_HARNESS_BRANCH': 'master'}
    with tempfile.TemporaryDirectory() as folder:
      out = Path(folder) / 'lifecycle'
      with patch.dict(os.environ, env, clear=True), patch.object(runner.subprocess, 'run', side_effect=command), \
           patch.object(runner.subprocess, 'check_output', return_value='@testrigor/testrigor-cli/2.0.9 linux-x64 node-v22.15.0'), \
           patch.object(runner.subprocess, 'Popen', Process), patch.object(runner.urllib.request, 'urlopen', side_effect=http), \
           contextlib.redirect_stdout(io.StringIO()) as printed:
        if fault:
          with self.assertRaises(RuntimeError):
            runner.execute(out)
        else:
          runner.execute(out)
      result = json.loads((out / 'result.json').read_text())
      self.assertEqual(result['passed'], fault is None)
      self.assertEqual(result['cleanupFailures'], [])
      self.assertEqual(state, {'marker': 'dokku-backend-original', 'route': True})
      self.assertNotIn(token, printed.getvalue())
      for path in out.rglob('*'):
        if path.is_file():
          self.assertNotIn(token, path.read_text())
      cloud = [args for args in self.calls if args[:3] == ['testrigor', 'test-suite', 'run']]
      self.assertTrue(all('--explicit-mutations' not in args and '--settings-path' not in args for args in cloud))
      return cloud

  def test_success_runs_five_stages_and_redacts_token(self):
    cloud = self.exercise()
    self.assertEqual(len(cloud), 5)
    self.assertEqual([Path(args[args.index('--junit-report-save-path') + 1]).parent.name for args in cloud],
                     ['baseline', 'restart', 'rollout', 'route-removed', 'recovered'])

  def test_cli_failure_stops_cycle_and_restores_state(self):
    self.assertEqual(len(self.exercise('cli')), 3)

  def test_junit_failure_stops_even_with_zero_cli_exit(self):
    self.assertEqual(len(self.exercise('junit')), 3)

  def test_invalid_syntax_starts_no_cloud_run(self):
    self.assertEqual(self.exercise('syntax'), [])


if __name__ == '__main__':
  unittest.main()
