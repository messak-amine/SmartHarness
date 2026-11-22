'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { once } = require('node:events');
const { Server } = require('socket.io');
const { io } = require('socket.io-client');
const { createProxy } = require('../scripts/dashboard-proxy');

async function listen(server) {
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return server.address().port;
}

test('Proxy privé : routes, origines et événements en lecture seule', {timeout:15000}, async t => {
  const requests = [];
  const upstream = http.createServer((req, res) => {
    requests.push(req.url);
    res.end('fixture');
  });
  const socketPath = '/dashboard/socket.io/';
  const source = new Server(upstream, {path:socketPath});
  const events = [];
  source.on('connection', client => {
    client.onAny((...args) => events.push(args));
    client.on('widget-load', () => client.emit('widget-load:dashboard-ui', {payload:'initial'}));
    client.emit('ui-config', 'ui-base', {});
  });
  const proxy = createProxy({upstreamPort:await listen(upstream), dnsName:'laptop.example.ts.net'});
  const base = 'http://127.0.0.1:' + await listen(proxy);
  t.after(() => { source.close(); proxy.close(); proxy.closeAllConnections(); });
  for (const route of ['/dashboard/monitoring?shView=history','/dashboard/_setup']) {
    assert.equal((await fetch(base + route)).status, 200);
  }
  for (const route of ['/editor','/editor/flows','/flows','/auth/token','/api/snapshot',
    '/dashboard/_debug/datastore/dashboard-ui','/dashboard/assets/missing.js','/comms','/socket.io/']) {
    assert.equal((await fetch(base + route)).status, 404, route);
  }
  assert.equal((await fetch(base+'/dashboard/_setup',{method:'POST'})).status,405);
  assert.equal((await fetch(base+'/dashboard/monitoring',{headers:{Origin:'https://other.example'}})).status,403);
  assert.equal((await fetch(base+'/dashboard/_setup',{headers:{Origin:'https://laptop.example.ts.net'}})).status,200);
  assert.deepEqual(requests,['/dashboard/monitoring','/dashboard/_setup','/dashboard/_setup']);
  const denied = http.request(base+'/editor/comms',{headers:{Connection:'Upgrade',Upgrade:'websocket'}});
  const response = once(denied,'response');
  denied.end();
  assert.equal((await response)[0].statusCode,403);

  const viewer = io(base,{path:socketPath,autoConnect:false,transports:['websocket'],reconnection:false});
  t.after(()=>viewer.disconnect());
  const ready = once(viewer,'ui-config');
  viewer.connect();
  await ready;
  const initial = once(viewer,'widget-load:dashboard-ui');
  viewer.emit('widget-send','dashboard-ui',{payload:'fixture'});
  viewer.emit('widget-load','other-widget');
  viewer.emit('widget-load','dashboard-ui');
  assert.deepEqual(await initial,[{payload:'initial'}]);
  assert.deepEqual(events,[['widget-load','dashboard-ui']]);
  const update = once(viewer,'msg-input:dashboard-ui');
  source.emit('msg-input:dashboard-ui',{payload:'updated'});
  assert.deepEqual(await update,[{payload:'updated'}]);
});

test('Accès externe facultatif : hôte et origine exacts pour HTTP et WebSocket', {timeout:10000}, async t => {
  const host = 'diagnostic.example.org';
  const origin = 'https://' + host;
  assert.throws(() => createProxy({accessHostname:'*.example.org'}), /invalide/);
  const backend = http.createServer((_req, res) => res.end('ok'));
  const upstreamPort = await listen(backend);
  const servers = [backend];
  t.after(() => servers.forEach(server => { server.close(); server.closeAllConnections(); }));
  for (const enabled of [false, true]) {
    const proxy = createProxy({upstreamPort, accessHostname:enabled ? host : ''});
    servers.push(proxy);
    const port = await listen(proxy);
    async function status(path, headers) {
      const req = http.get({hostname:'127.0.0.1', port, path, headers});
      const [res] = await once(req,'response');
      res.resume();
      return res.statusCode;
    }
    assert.equal(await status('/dashboard/_setup', {Host:host, Origin:origin}), enabled ? 200 : 403);
    assert.equal(await status('/dashboard/_setup', {Host:host, Origin:'https://other.example.org'}),403);
    assert.equal(await status('/dashboard/_setup', {Host:'another.example.org','X-Forwarded-Host':host}),403);
    if (!enabled) continue;
    for (const path of ['/editor/flows','/api/snapshot','/dashboard/_debug/datastore/dashboard-ui']) {
      assert.equal(await status(path, {Host:host}),404);
    }
    const socketHeaders = {Host:host, Origin:origin, Connection:'Upgrade', Upgrade:'websocket',
      'Sec-WebSocket-Version':'13','Sec-WebSocket-Key':require('node:crypto').randomBytes(16).toString('base64')};
    const path = '/dashboard/socket.io/?EIO=4&transport=websocket';
    assert.equal(await status(path, {...socketHeaders, Origin:'https://other.example.org'}),403);
    const req = http.get({hostname:'127.0.0.1', port, path, headers:socketHeaders});
    const [res,socket] = await once(req,'upgrade');
    socket.destroy();
    assert.equal(res.statusCode,101);
  }
});
