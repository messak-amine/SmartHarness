'use strict';

const path = require('node:path');
const fs = require('node:fs');
const root = path.resolve(__dirname, '..');
process.env.MQTT_HOST ||= '127.0.0.1';
process.env.MQTT_PORT ||= '1883';
process.env.SH_DB_PATH = path.resolve(process.env.SH_DB_PATH || path.join(root, 'data/events.sqlite'));
fs.mkdirSync(path.dirname(process.env.SH_DB_PATH), { recursive: true });
process.argv = [process.execPath, require.resolve('node-red/red.js'), '--settings', path.join(root, 'settings.js')];
require('node-red/red.js');
