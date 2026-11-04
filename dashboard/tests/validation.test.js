'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { validateEvent, validateStatus } = require('../lib/validate-event');
const { createState, acceptStored, restoreHistory, snapshot, nextWrite } = require('../lib/state');
const good = { ecu:'A',circuit:1,fault_code:1,active:true,voltage_mv:0,command_on:true,seq:1 };
const topic = 'smartharness/ecu/a/faults';

test('Les quatre circuits commencent UNKNOWN, aucun état sain inventé', () => {
  const s = createState();
  assert.equal(s.circuits.length, 4);
  assert.ok(s.circuits.every(c => c.status === 'UNKNOWN'));
  assert.equal(snapshot(s).gateway, 'unknown');
});
test('Contrat JSON et Buffer, ECU A et B', () => {
  assert.deepEqual(validateEvent(topic, JSON.stringify(good)), good);
  for (const circuit of [1,2,3,4]) {
    const ecu = circuit < 3 ? 'A' : 'B';
    const event = {...good,ecu,circuit};
    assert.deepEqual(validateEvent(`smartharness/ecu/${ecu.toLowerCase()}/faults`, Buffer.from(JSON.stringify(event))), event);
  }
});
test('Rejet JSON invalide, null, liste et taille excessive', () => {
  for (const input of ['{broken', 'null', '[]', 'x'.repeat(4097)]) assert.throws(() => validateEvent(topic, input));
});
test('Champs absents, supplémentaires, types et incohérences rejetés', () => {
  for (const key of Object.keys(good)) {
    const value = {...good}; delete value[key]; assert.throws(() => validateEvent(topic, value));
  }
  for (const change of [{ecu:'B'},{circuit:3},{fault_code:3},{fault_code:0},{active:1},{command_on:'true'},{seq:-1},{seq:65536},{seq:1.1},{voltage_mv:'0'},{voltage_mv:65536},{extra:1}]) {
    assert.throws(() => validateEvent(topic, {...good,...change}), JSON.stringify(change));
  }
  assert.throws(() => validateEvent('smartharness/ecu/a/telemetry', good));
});
test('OFF ne répare pas une panne ; résolution seulement sur événement explicite', () => {
  const s=createState();
  const off=validateEvent(topic,{...good,command_on:false});
  acceptStored(s,off,'2026-11-03T12:00:00Z');
  assert.equal(s.circuits[0].status,'FAULT');
  acceptStored(s,validateEvent(topic,{...good,fault_code:0,active:false,voltage_mv:3300}),'2026-11-03T12:00:01Z');
  assert.equal(s.circuits[0].status,'RECOVERED');
});
test('Séquences 65535 et zéro acceptées, répétitions préservées par validation', () => {
  for (const seq of [65535,0,0]) assert.equal(validateEvent(topic,{...good,seq}).seq,seq);
});
test('Code 2 existant accepté sans inventer de détection', () => {
  assert.equal(validateEvent(topic,{...good,fault_code:2}).fault_code,2);
});
test('Archives restaurées sans transformer UNKNOWN en état courant', () => {
  const s=createState(); restoreHistory(s,[{...good,event_id:1,total_count:1}]);
  assert.equal(s.total,1); assert.equal(s.circuits[0].historical.event_id,1);
  assert.equal(s.circuits[0].status,'UNKNOWN');
});
test('Gateway exact et distinct du broker et des ECU', () => {
  assert.equal(validateStatus('{"status":"online"}'),'online');
  assert.equal(validateStatus('{"status":"offline"}'),'offline');
  assert.throws(()=>validateStatus('{"gateway":"ESP32_GW","status":"ONLINE"}'));
  const s=createState(); s.gateway='online';
  assert.equal(snapshot(s).gateway,'unknown');
  s.mqtt='connected'; assert.equal(snapshot(s).gateway,'online');
  assert.ok(snapshot(s).circuits.every(c=>c.status==='UNKNOWN'));
});
test('Une seule écriture en vol, ordre FIFO même pour séquences réutilisées', () => {
  const s=createState();s.pending.push({seq:65535},{seq:0},{seq:0});
  assert.equal(nextWrite(s),null);
  s.ready=true;assert.equal(nextWrite(s).seq,65535);assert.equal(nextWrite(s),null);
  s.writing=false;assert.equal(nextWrite(s).seq,0);assert.equal(s.pending.length,1);
});
test('Une ancienne lecture asynchrone ne remplace pas un historique plus récent', () => {
  const s=createState();restoreHistory(s,[{...good,event_id:2,total_count:2}]);
  restoreHistory(s,[{...good,event_id:1,total_count:1}]);
  assert.equal(s.total,2);assert.equal(s.history[0].event_id,2);
});
