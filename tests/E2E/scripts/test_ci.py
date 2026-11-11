"""Offline checks for trust boundaries, browser oracle order and cleanup."""
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


def load(name):
  spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


class GateTests(unittest.TestCase):
  def test_embedded_gate_matches_without_checkout_or_secret(self):
    root = Path(__file__).resolve().parents[3]
    workflow = (root / '.github/workflows/e2e-tests.yml').read_text()
    embedded = workflow.split("python3 - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
    self.assertEqual(textwrap.dedent(embedded).strip(), Path(__file__).with_name('ci-gate.py').read_text().strip())
    gate = workflow.split('  gate:\n', 1)[1].split('  browser:\n', 1)[0]
    self.assertNotIn('actions/checkout', gate)
    self.assertNotIn('TESTRIGOR_API_KEY', gate)
    self.assertIn("secrets.TESTRIGOR_CI_TOKEN != ''", gate)

  def test_skip_is_notice_and_summary_with_reason(self):
    with tempfile.TemporaryDirectory() as folder:
      output, summary = Path(folder) / 'output', Path(folder) / 'summary'
      result = subprocess.run([sys.executable, str(Path(__file__).with_name('ci-gate.py'))],
        env={'GITHUB_OUTPUT': str(output), 'GITHUB_STEP_SUMMARY': str(summary)}, capture_output=True, text=True, check=True)
      self.assertEqual(output.read_text(), 'enabled=false\n')
      self.assertIn('::notice::Browser E2E skipped: suite ID is not configured', result.stdout)
      self.assertIn('suite ID is not configured', summary.read_text())

  def test_event_matrix(self):
    gate = load('ci-gate')
    valid = {'TESTRIGOR_SUITE_ID': 'suite', 'TESTRIGOR_TOKEN_PRESENT': 'true',
             'DOKKU_DEFAULT_BRANCH': 'master', 'GITHUB_REF': 'refs/heads/master'}
    self.assertTrue(gate.evaluate(dict(valid, GITHUB_EVENT_NAME='workflow_dispatch')))
    self.assertTrue(gate.evaluate(dict(valid, GITHUB_EVENT_NAME='schedule')))
    self.assertFalse(gate.evaluate(dict(valid, GITHUB_EVENT_NAME='schedule', GITHUB_REF='refs/heads/topic')))
    self.assertFalse(gate.evaluate(dict(valid, GITHUB_EVENT_NAME='pull_request_target')))
    for token in ('false', '', ' true '):
      self.assertFalse(gate.evaluate(dict(valid, GITHUB_EVENT_NAME='workflow_dispatch', TESTRIGOR_TOKEN_PRESENT=token)))
    pr = dict(valid, GITHUB_EVENT_NAME='pull_request', GITHUB_REPOSITORY='owner/dokku', DOKKU_PR_HEAD_REPOSITORY='owner/dokku')
    self.assertTrue(gate.evaluate(pr))
    self.assertFalse(gate.evaluate(dict(pr, DOKKU_PR_HEAD_REPOSITORY='fork/dokku')))


class OracleTests(unittest.TestCase):
  def test_both_disagreements_fail(self):
    runner = load('run-ci')
    for browser, http in ((True, False), (False, True)):
      with self.assertRaisesRegex(RuntimeError, 'oracle disagreement'):
        runner.agree(browser, http)
    runner.agree(True, True)
    runner.agree(False, False)

  def test_missing_run_id_and_incomplete_results_are_not_verdicts(self):
    runner = load('run-ci')
    with tempfile.TemporaryDirectory() as folder:
      p = Path(folder) / 'report.xml'
      for body in ('<testcase/>', '<testcase><skipped/></testcase>', '<testcase/><testcase/>'):
        p.write_text('<testsuites><testsuite>' + body + '</testsuite></testsuites>')
        with self.assertRaises(RuntimeError): runner.verdict(p, 0)

  def test_browser_failure_is_not_a_successful_negative_cli_error(self):
    runner = load('run-ci')
    with tempfile.TemporaryDirectory() as folder:
      p = Path(folder) / 'report.xml'
      p.write_text('<testsuites><testcase/><property name="taskId" value="run"/></testsuites>')
      with self.assertRaisesRegex(RuntimeError, 'without a browser assertion'):
        runner.verdict(p, 1)

  def test_neutral_readiness_then_browser_then_crosscheck(self):
    runner = load('run-ci')
    events = []
    c = object.__new__(runner.Controller)
    c.original = 'dokku-backend-original'
    c.route = lambda *a, **k: events.append('prepare')
    c.neutral_ready = lambda: events.append('healthz')
    c.browser = lambda *a: (events.append('browser') or True, {})
    c.crosscheck = lambda *a: events.append('post-case-http') or True
    c.stage(1, False)
    self.assertEqual(events, ['prepare', 'healthz', 'browser', 'post-case-http'])

  def test_negative_control_cannot_pass(self):
    runner = load('run-ci')
    c = object.__new__(runner.Controller)
    c.original = 'dokku-backend-original'
    c.route = lambda *a, **k: None
    c.neutral_ready = lambda: None
    c.browser = lambda *a: (True, {})
    c.crosscheck = lambda *a: True
    with self.assertRaisesRegex(RuntimeError, 'Negative control unexpectedly passed'):
      c.stage(1, True)

  def test_infrastructure_failure_is_not_a_valid_negative_control(self):
    runner = load('run-ci')
    c = object.__new__(runner.Controller)
    c.original = 'dokku-backend-original'
    c.route = lambda *a, **k: None
    c.neutral_ready = lambda: None
    c.browser = lambda *a: (False, {'failureMessages': ['Browser node unavailable']})
    c.crosscheck = lambda *a: False
    with self.assertRaisesRegex(RuntimeError, 'intended assertion'):
      c.stage(1, True)

  def test_malformed_postcase_identity_disagrees_with_browser_success(self):
    runner = load('run-ci')
    c = object.__new__(runner.Controller)
    values = {'expectedBackendMarker': 'marker', 'previousHostname': 'old-host'}
    for body in ('not-json', '[]', '{"role":"api","marker":"marker"}'):
      with patch.object(runner, 'read_http', return_value=(200, body)):
        observed = c.crosscheck(2, values)
      self.assertFalse(observed)
      with self.assertRaisesRegex(RuntimeError, 'oracle disagreement'):
        runner.agree(True, observed)


class BoundaryTests(unittest.TestCase):
  def test_cli_child_receives_token_and_logs_are_redacted(self):
    runner = load('run-ci')
    token = 'offline-never-persist-secret'
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TESTRIGOR_API_KEY': token, 'TESTRIGOR_SUITE_ID': 'suite'}):
      c = runner.Controller(Path(folder) / 'out')
      self.assertNotIn('TESTRIGOR_API_KEY', c.local_env)
      class Process:
        def __init__(inner, args, **kwargs):
          self.assertNotIn(token, ' '.join(args))
          self.assertEqual(kwargs['env']['TESTRIGOR_API_KEY'], token)
          inner.stdout = iter([token + '\n'])
        def wait(inner): return 0
      log = c.artifacts / 'log'
      with patch.object(runner.subprocess, 'Popen', Process), contextlib.redirect_stdout(io.StringIO()) as printed:
        self.assertEqual(c.cli_process(['test-suite', 'run'], log), 0)
      self.assertNotIn(token, log.read_text() + printed.getvalue())
      self.assertIn('[REDACTED]', log.read_text())

  def test_failures_attempt_all_restoration_steps(self):
    runner = load('run-ci')
    revision, original = 'a' * 40, 'dokku-backend-original'
    routes = 'Route /api/v0 -> api:5001\nRoute /ws -> ws:5002'
    calls = []
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,
      {'TESTRIGOR_API_KEY': 'offline-token', 'TESTRIGOR_SUITE_ID': 'suite',
       'DOKKU_SOURCE_REVISION': revision, 'DOKKU_E2E_IMAGE': 'image'}):
      c = runner.Controller(Path(folder) / 'out')
      expected = json.loads((runner.ROOT / 'package.json').read_text())['dependencies']['@testrigor/testrigor-cli']
      def command(args):
        if '--version' in args: return '@testrigor/testrigor-cli/' + expected + ' linux'
        if 'inspect' in args: return '{"Id":"image"}'
        return revision
      def dokku(*args):
        calls.append(args)
        if args[0] == 'config:get': return 'dokku-browser-e2e' if args[-1] == 'E2E_FIXTURE_OWNER' else original
        if args[0] == 'proxy:route:report': return routes
        if args[0] == 'config:set': raise RuntimeError('restore failed')
        return ''
      with patch.object(c, 'command', command), patch.object(c, 'dokku', dokku), \
           patch.object(c, 'neutral_ready'), patch.object(c, 'stage', side_effect=RuntimeError('browser failed')), \
           patch.object(runner, 'read_http', return_value=(200, json.dumps({'marker': original}))):
        with self.assertRaisesRegex(RuntimeError, 'cleanup failed'): c.execute((1,))
      self.assertIn(('proxy:route:set', 'browser-probe', 'ws', '/ws', '--port', '5002'), calls)
      result = json.loads((c.artifacts / 'result.json').read_text())
      self.assertFalse(result['passed'])
      self.assertTrue(result['cleanupFailures'])


if __name__ == '__main__':
  unittest.main()
