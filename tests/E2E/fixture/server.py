import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROLE = sys.argv[1]
MARKER = os.environ.get('E2E_MARKER', 'dokku-backend-unconfigured')
PAGE = b'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Dokku routing probe</title>
<script src="/probe.js" defer></script></head>
<body><h1>Dokku routing probe</h1><button id="check">Check backend</button>
<p id="result" role="status">Backend not checked</p></body></html>'''
SCRIPT = b'''document.querySelector('#check').addEventListener('click', async () => {
  const result = document.querySelector('#result');
  result.textContent = 'Checking backend';
  try {
    const response = await fetch('/api/v0/identity', {cache: 'no-store'});
    if (!response.ok) throw new Error('Backend HTTP ' + response.status);
    const data = await response.json();
    if (data.role !== 'api') throw new Error('Wrong upstream');
    result.textContent = data.marker;
  } catch (error) {
    result.textContent = 'Backend check failed: ' + error.message;
  }
});'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if ROLE == 'web' and self.path == '/':
            payload, content_type, status = PAGE, 'text/html; charset=utf-8', 200
        elif ROLE == 'web' and self.path == '/probe.js':
            payload, content_type, status = SCRIPT, 'text/javascript; charset=utf-8', 200
        elif ROLE == 'api' and self.path == '/api/v0/identity':
            payload = json.dumps({'role': ROLE, 'marker': MARKER}).encode()
            content_type, status = 'application/json', 200
        else:
            payload, content_type, status = b'Wrong upstream or path', 'text/plain', 404
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


ThreadingHTTPServer(('0.0.0.0', 5000 if ROLE == 'web' else 5001), Handler).serve_forever()
