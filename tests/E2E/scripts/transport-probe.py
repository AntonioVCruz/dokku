"""Probe HTTP Host and WebSocket forwarding through the CLI tunnel; no cloud tests."""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time


def websocket(proxy=None):
  connection = socket.create_connection(proxy or ('localhost', 19080), timeout=15)
  stream = connection.makefile('rb')
  def headers():
    first = stream.readline().decode().strip()
    fields = {}
    while True:
      line = stream.readline().decode().strip()
      if not line: break
      key, value = line.split(':', 1)
      fields[key.lower()] = value.strip()
    return first, fields
  try:
    if proxy:
      connection.sendall(b'CONNECT localhost:19080 HTTP/1.1\r\nHost: localhost:19080\r\n\r\n')
      first, _ = headers()
      if ' 200 ' not in first: raise RuntimeError('CONNECT: ' + first)
    key = base64.b64encode(os.urandom(16)).decode()
    connection.sendall(('GET /ws HTTP/1.1\r\nHost: localhost:19080\r\nUpgrade: websocket\r\n'
      'Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: ' + key + '\r\n\r\n').encode())
    first, fields = headers()
    expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
    if ' 101 ' not in first or fields.get('sec-websocket-accept') != expected:
      raise RuntimeError('Upgrade: ' + first)
    message = ('transport-probe-' + os.urandom(8).hex()).encode()
    mask = os.urandom(4)
    connection.sendall(bytes([0x81, 0x80 | len(message)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(message)))
    start = stream.read(2)
    length = start[1] & 127
    if length == 126: length = struct.unpack('!H', stream.read(2))[0]
    data = json.loads(stream.read(length))
    if data['echo'] != message.decode(): raise RuntimeError('Echo mismatch')
    return {'upgrade': first, 'echoMatched': True, 'upstreamHost': data['host'], 'marker': data['marker']}
  finally:
    stream.close()
    connection.close()


def main(out):
  out.mkdir(parents=True, exist_ok=False)
  # The tunnel does not require a suite token. Do not inherit one into Node.
  env = {k: v for k, v in os.environ.items() if k != 'TESTRIGOR_API_KEY'}
  script = """const path = require('path');
const root = process.env.TESTRIGOR_MODULE_ROOT || path.join(require('child_process').execFileSync('npm', ['root', '-g'], {encoding:'utf8'}).trim(), '@testrigor/testrigor-cli');
const Tunnel = require(path.join(root, 'dist/util/tunnel.js')).default;
(async () => { const t = new Tunnel(); await t.initialize(); await t.start(48197,48197);
console.log('PROBE_READY'); process.on('SIGTERM', async () => {await t.stop();process.exit(0)}); })().catch(e=>{console.error(e.message);process.exit(1)});
"""
  result = {'localWebSocket': websocket()}
  with (out / 'tunnel.log').open('w') as log:
    process = subprocess.Popen(['node', '-e', script], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
      # The workflow step timeout bounds download/startup as well as this loop.
      for line in process.stdout:
        log.write(line); log.flush()
        if 'PROBE_READY' in line: break
      else: raise RuntimeError('Tunnel did not start')
      connection = http.client.HTTPConnection('tunnel.testrigor.com', 48197, timeout=20)
      connection.request('GET', 'http://localhost:19080/probe-host', headers={'Host': 'localhost:19080'})
      response = connection.getresponse()
      result['tunnelHTTP'] = {'status': response.status, 'body': response.read().decode()}
      connection.close()
      result['tunnelWebSocket'] = websocket(('tunnel.testrigor.com', 48197))
    finally:
      process.terminate()
      try: process.wait(timeout=15)
      except subprocess.TimeoutExpired: process.kill(); process.wait()
      (out / 'transport.json').write_text(json.dumps(result, indent=2))
  print(json.dumps(result, indent=2))


if __name__ == '__main__':
  main(Path(sys.argv[1]))
