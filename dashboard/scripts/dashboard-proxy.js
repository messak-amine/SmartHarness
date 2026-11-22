'use strict';

const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs');
const { Server } = require('socket.io');
const { io: connect } = require('socket.io-client');

const loopback = '127.0.0.1';
const socketPath = '/dashboard/socket.io/';
const widget = 'dashboard-ui';
const dist = path.join(path.dirname(require.resolve('@flowfuse/node-red-dashboard/package.json')), 'dist');
const routes = new Set(['/dashboard/monitoring', '/dashboard/_setup', '/dashboard/manifest.webmanifest',
  '/dashboard/favicon.ico', '/dashboard/favicon.svg', '/dashboard/apple-touch-icon.png',
  '/dashboard/pwa-64x64.png', '/dashboard/pwa-192x192.png', '/dashboard/pwa-512x512.png']);
// Match the pinned Dashboard's entry points and the lazy resources this view uses.
const html = fs.readFileSync(path.join(dist, 'index.html'), 'utf8');
for (const match of html.matchAll(/(?:src|href)="\.\/(assets\/[\w.-]+)"/g)) routes.add('/dashboard/' + match[1]);
for (const file of fs.readdirSync(path.join(dist, 'assets'))) {
  if (/^(?:workbox-window\.prod\.es5-[\w-]+\.js|materialdesignicons-webfont-[\w-]+\.woff2|disconnected-[\w-]+\.png)$/.test(file)) {
    routes.add('/dashboard/assets/' + file);
  }
}

function createProxy({ upstreamPort = 1880, dnsName = '', accessHostname = '' } = {}) {
  if (dnsName && !/^[a-z0-9-]+\.[a-z0-9-]+\.ts\.net$/.test(dnsName)) throw Error('Nom MagicDNS invalide');
  if (accessHostname && (accessHostname.length > 253 ||
      !/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(accessHostname) ||
      accessHostname.endsWith('.ts.net'))) throw Error('Nom DNS Cloudflare invalide');
  const upstream = 'http://' + loopback + ':' + upstreamPort;
  const transport = http.createServer();
  const io = new Server(transport, { path: socketPath, serveClient: false, maxHttpBufferSize: 8192 });
  // A new local connection with no client-supplied query, credentials or events.
  io.on('connection', viewer => {
    const source = connect(upstream, { path: socketPath, forceNew: true, reconnection: false, autoConnect: false });
    source.on('ui-config', (id, config) => viewer.emit('ui-config', id, config));
    for (const name of ['widget-load:', 'msg-input:']) {
      source.on(name + widget, (...args) => viewer.emit(name + widget, ...args));
    }
    viewer.on('widget-load', id => {
      if (id === widget && source.connected) source.emit('widget-load', widget);
    });
    source.on('connect_error', () => viewer.conn.close());
    source.on('disconnect', () => viewer.conn.close());
    viewer.on('disconnect', () => source.disconnect());
    source.connect();
  });

  function permittedPeer(req) {
    const port = server.address().port;
    // cloudflared authenticates each request before forwarding this exact Host.
    // Never infer an external origin from a forwarded header.
    if (accessHostname && [accessHostname, accessHostname + ':443'].includes(req.headers.host)) {
      return req.headers.origin === undefined || req.headers.origin === 'https://' + accessHostname;
    }
    const localHosts = [loopback + ':' + port, 'localhost:' + port];
    const hosts = dnsName ? [...localHosts, dnsName, dnsName + ':443'] : localHosts;
    const origins = localHosts.map(host => 'http://' + host);
    if (dnsName) origins.push('https://' + dnsName);
    return hosts.includes(req.headers.host) && (!req.headers.origin || origins.includes(req.headers.origin));
  }
  function socketRoute(req) {
    const [rawPath, query] = req.url.split('?');
    if (rawPath !== socketPath || !query) return false;
    const params = new URLSearchParams(query);
    const keys = [...params.keys()];
    return new Set(keys).size === keys.length && keys.every(k => ['EIO','transport','sid','t','clientId','b64'].includes(k))
      && params.get('EIO') === '4' && ['websocket','polling'].includes(params.get('transport'));
  }
  const server = http.createServer((req, res) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('X-Frame-Options', 'DENY');
    if (!permittedPeer(req)) { res.writeHead(403).end(); return; }
    if (socketRoute(req) && ['POST','GET'].includes(req.method)) {
      transport.emit('request', req, res);
      return;
    }
    if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405).end(); return; }
    const pathname = req.url.split('?')[0];
    if (['/', '/dashboard', '/dashboard/'].includes(pathname)) {
      res.writeHead(302, { Location: '/dashboard/monitoring' }).end();
      return;
    }
    if (pathname === '/dashboard/sw.js') {
      // FlowFuse registers a worker. The private viewer needs no offline cache.
      res.writeHead(200, { 'Content-Type': 'text/javascript' }).end('// Online dashboard only.');
      return;
    }
    if (!routes.has(pathname)) { res.writeHead(404).end(); return; }
    const target = http.request({ hostname: loopback, port: upstreamPort, path: pathname, method: req.method }, reply => {
      if (reply.statusCode !== 200) { reply.resume(); res.writeHead(502).end(); return; }
      res.writeHead(200, { 'Content-Type': reply.headers['content-type'] || 'application/octet-stream' });
      reply.on('error', () => res.destroy());
      reply.pipe(res);
    });
    target.setTimeout(10000, () => target.destroy());
    target.on('error', () => { if (!res.headersSent) res.writeHead(502); res.end(); });
    res.on('close', () => target.destroy());
    target.end();
  });
  server.on('upgrade', (req, socket, head) => {
    if (req.method === 'GET' && permittedPeer(req) && socketRoute(req)) transport.emit('upgrade', req, socket, head);
    else socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n');
  });
  server.on('close', () => io.close());
  return server;
}

module.exports = { createProxy };
if (require.main === module) {
  createProxy({ dnsName: process.env.SH_TAILSCALE_DNS, accessHostname: process.env.SH_ACCESS_HOSTNAME }).listen(1881, loopback, () => {
    console.log('SmartHarness en lecture seule sur http://127.0.0.1:1881/dashboard/monitoring');
  });
}
