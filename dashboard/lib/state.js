'use strict';

const names = ['Phares', 'Clignotants', 'Feux stop', 'Ventilation'];
function createState() {
  return {
    started_at: new Date().toISOString(), ready: false, mqtt: 'disconnected', gateway: 'unknown',
    gateway_received_at: null, database: 'initializing', last_error: null,
    rejected: 0, failed_writes: 0, pending: [], writing: false, history: [], total: 0,
    circuits: names.map((name, i) => ({ circuit: i + 1, ecu: i < 2 ? 'A' : 'B', name,
      status: 'UNKNOWN', fresh: false, historical: null, last: null }))
  };
}

function snapshot(state) {
  return {
    started_at: state.started_at, ready: state.ready, mqtt: state.mqtt,
    gateway: state.mqtt === 'connected' ? state.gateway : 'unknown',
    gateway_received_at: state.gateway_received_at,
    database: state.database, last_error: state.last_error, rejected: state.rejected,
    failed_writes: state.failed_writes, pending: state.pending.length, writing: state.writing,
    total: state.total, history: state.history,
    circuits: state.circuits.map(c => ({ ...c, stale: !c.fresh || state.mqtt !== 'connected' || state.gateway !== 'online' }))
  };
}

function acceptStored(state, event, receivedAt) {
  const circuit = state.circuits[event.circuit - 1];
  circuit.last = { ...event, received_at: receivedAt };
  circuit.fresh = true;
  circuit.status = event.active ? (event.fault_code === 2 ? 'INTERMITTENT' : 'FAULT') : 'RECOVERED';
}

function restoreHistory(state, rows) {
  // Asynchronous reads may finish after a newer refresh. History is append-only.
  const total = rows.length ? rows[0].total_count : 0;
  if (total < state.total) return;
  state.history = rows.slice(0, 200);
  state.total = total;
  for (const circuit of state.circuits) {
    circuit.historical = rows.find(row => row.circuit === circuit.circuit) || circuit.historical;
  }
}

function nextWrite(state) {
  if (!state.ready || state.writing || !state.pending.length) return null;
  state.writing = true;
  return state.pending.shift();
}

module.exports = { createState, snapshot, acceptStored, restoreHistory, nextWrite };
