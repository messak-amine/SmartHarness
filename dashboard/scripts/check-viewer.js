'use strict';

// Smoke test the running restricted proxy. No MQTT publication or database write.
const http = require('node:http');
const { randomBytes } = require('node:crypto');
const [external, tailscale] = process.argv[2].split('|');
const dashboard = '/dashboard/monitoring';

function check(path, headers, expected) {
  return new Promise((resolve, reject) => {
    const req = http.get({hostname:'127.0.0.1', port:1881, path, headers}, res => {
      res.resume();
      finish(res.statusCode);
    });
    function finish(status) {
      if (status === expected) resolve();
      else reject(new Error(path + ' : HTTP ' + status + ', attendu ' + expected));
    }
    req.setTimeout(5000, () => req.destroy(new Error('Timeout ' + path)));
    req.on('upgrade', (res, socket) => { socket.destroy(); finish(res.statusCode); });
    req.on('error', reject);
  });
}

async function verify() {
  await check(dashboard, {}, 200);
  if (tailscale) await check(dashboard, {Host:tailscale, Origin:'https://' + tailscale}, 200);
  const host = external || '127.0.0.1:1881';
  const origin = (external ? 'https://' : 'http://') + host;
  await check(dashboard, {Host:host, Origin:origin}, 200);
  await check(dashboard, {Host:'unauthorized-test.trycloudflare.com'}, 403);
  for (const path of ['/editor/', '/editor/flows', '/api/snapshot', '/data/events.sqlite', '/dashboard/_debug/datastore/dashboard-ui']) {
    await check(path, {Host:host}, 404);
  }
  const headers = {Host:host, Origin:origin, Connection:'Upgrade', Upgrade:'websocket',
    'Sec-WebSocket-Version':'13', 'Sec-WebSocket-Key':randomBytes(16).toString('base64')};
  const socketPath = '/dashboard/socket.io/?EIO=4&transport=websocket';
  await check(socketPath, headers, 101);
  await check(socketPath, {...headers, Origin:'https://other.invalid'}, 403);
}
verify().catch(error => { console.error(error.message); process.exitCode = 1; });
