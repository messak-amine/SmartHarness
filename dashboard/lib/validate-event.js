'use strict';

const TOPICS = Object.freeze({
  'smartharness/ecu/a/faults': 'A',
  'smartharness/ecu/b/faults': 'B'
});
const FIELDS = ['ecu', 'circuit', 'fault_code', 'active', 'voltage_mv', 'command_on', 'seq'];

function parse(payload) {
  if (Buffer.isBuffer(payload)) payload = payload.toString('utf8');
  if (typeof payload === 'string') {
    if (Buffer.byteLength(payload) > 4096) throw new Error('Message trop volumineux');
    try { payload = JSON.parse(payload); } catch { throw new Error('JSON invalide'); }
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('Objet JSON attendu');
  return payload;
}

function validateEvent(topic, input) {
  if (!Object.hasOwn(TOPICS, topic)) throw new Error('Topic de diagnostic inconnu');
  const event = parse(input);
  if (Object.keys(event).length !== FIELDS.length || !FIELDS.every(k => Object.hasOwn(event, k))) {
    throw new Error('Les sept champs du contrat sont requis, sans champ supplémentaire');
  }
  if (event.ecu !== TOPICS[topic]) throw new Error('ECU incompatible avec le topic');
  const allowed = event.ecu === 'A' ? [1, 2] : [3, 4];
  if (!allowed.includes(event.circuit)) throw new Error('Circuit incompatible avec ECU');
  if (![0, 1, 2].includes(event.fault_code)) throw new Error('Code de panne inconnu');
  if (typeof event.active !== 'boolean' || typeof event.command_on !== 'boolean') throw new Error('Booléens requis');
  if (event.active !== (event.fault_code !== 0)) throw new Error('Code de panne et état actif incohérents');
  for (const key of ['voltage_mv', 'seq']) {
    if (!Number.isInteger(event[key]) || event[key] < 0 || event[key] > 65535) throw new Error(`${key}: entier uint16 requis`);
  }
  return Object.fromEntries(FIELDS.map(key => [key, event[key]]));
}

function validateStatus(input) {
  const value = parse(input);
  if (Object.keys(value).length !== 1 || !['online', 'offline'].includes(value.status)) throw new Error('Statut Gateway invalide');
  return value.status;
}

module.exports = { TOPICS, validateEvent, validateStatus };
