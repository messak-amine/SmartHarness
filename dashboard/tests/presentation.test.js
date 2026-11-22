'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createState } = require('../lib/state');

async function component() {
  const { default: ui } = await import('../ui/dashboard.mjs');
  const vm = { ...ui.data(), msg: { payload: createState() } };
  for (const [key, method] of Object.entries(ui.methods)) vm[key] = method.bind(vm);
  for (const [key, computed] of Object.entries(ui.computed)) Object.defineProperty(vm, key, { get: () => computed.call(vm) });
  return vm;
}

test('Présentation : archives séparées de UNKNOWN, graphiques vides sans valeurs inventées', async () => {
  const vm = await component();
  vm.data.history = [{ event_id: 1, circuit: 1, ecu: 'A', fault_code: 0 }];
  assert.deepEqual(vm.summary, { fault: 0, recovered: 0, unknown: 4 });
  assert.equal(vm.typeCounts[1].count, 1);
  vm.data.history = [];
  assert.ok(vm.circuitCounts.every(c => c.count === 0 && c.percent === 0));
  assert.equal(vm.donutBackground, 'var(--border)');
});

test('Présentation : filtres combinés, répétitions conservées et graphiques indépendants des filtres', async () => {
  const vm = await component();
  vm.data.history = [
    { event_id: 4, circuit: 1, ecu: 'A', fault_code: 1, seq: 0 },
    { event_id: 3, circuit: 1, ecu: 'A', fault_code: 1, seq: 0 },
    { event_id: 2, circuit: 1, ecu: 'A', fault_code: 0 },
    { event_id: 1, circuit: 4, ecu: 'B', fault_code: 2 }
  ];
  vm.selectCircuit(1); vm.ecuFilter = 'A'; vm.typeFilter = '1';
  assert.deepEqual(vm.rows.map(r => r.event_id), [4, 3]);
  assert.deepEqual(vm.typeCounts.map(t => t.count), [2, 1, 1]);
  assert.deepEqual(vm.circuitCounts.map(c => c.count), [3, 0, 0, 1]);
  vm.ecuFilter = 'B'; assert.equal(vm.rows.length, 0);
  vm.resetFilters(); assert.equal(vm.rows.length, 4);
});

test('Présentation : panne et intermittence actives, résolution sans affirmation de santé', async () => {
  const vm = await component();
  ['FAULT', 'INTERMITTENT', 'RECOVERED', 'UNKNOWN'].forEach((status, i) => { vm.data.circuits[i].status = status; });
  assert.deepEqual(vm.summary, { fault: 2, recovered: 1, unknown: 1 });
  assert.equal(vm.tone(vm.data.circuits[1]), 'fault');
  assert.equal(vm.label('RECOVERED'), 'RÉSOLUTION REÇUE');
  vm.data.gateway = 'offline'; assert.equal(vm.gatewayLabel, 'Hors ligne');
  assert.equal(vm.summary.recovered, 1);
});

test('Réception visuelle : archives silencieuses, doublons reconnus par leur ID SQLite', async () => {
  const vm = await component();
  const archive = [{ event_id: 10, circuit: 1, seq: 0 }];
  vm.markNewReceptions(archive, undefined);
  vm.markNewReceptions(archive, []);
  assert.deepEqual(vm.activity, {});
  vm.data.circuits[0].last = { seq: 0 };
  const repeated = [{ event_id: 11, circuit: 1, seq: 0 }, ...archive];
  vm.markNewReceptions(repeated, archive);
  assert.equal(vm.activity[1], 11);
  vm.markNewReceptions(repeated, repeated);
  assert.deepEqual(vm.activity, { 1: 11 });
});

test('Routage : liens directs validés et valeurs inconnues ramenées à la vue initiale', async () => {
  const vm = await component();
  assert.deepEqual(vm.routeValues({ shView:'history', shCircuit:'3', shEcu:'B', shType:'0' }),
    { section:'history', filter:'3', ecuFilter:'B', typeFilter:'0' });
  assert.deepEqual(vm.routeValues({ shView:'invalid', shCircuit:['1','2'], shEcu:'C', shType:'8' }),
    { section:'overview', filter:'all', ecuFilter:'all', typeFilter:'all' });
  vm.$route = { query: { unrelated:'kept', shCircuit:'4' } };
  assert.deepEqual(vm.routeQuery('analytics'), { unrelated:'kept', shView:'analytics' });
});
