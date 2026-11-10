'use strict';

const path = require('node:path');
const fs = require('node:fs');
const state = require('./lib/state');
const runtime = path.resolve(process.env.SH_RUNTIME_DIR || path.join(__dirname, '.runtime'));
fs.mkdirSync(runtime, { recursive: true });
// Keep a private runtime's MQTT identity across Node-RED and broker restarts.
const crypto = require('node:crypto');
const identityFile = path.join(runtime, 'mqtt-instance-id');
if (!fs.existsSync(identityFile)) {
  try {
    fs.writeFileSync(identityFile, crypto.randomUUID(), { flag: 'wx', mode: 0o600 });
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
  }
}
const identity = fs.readFileSync(identityFile, 'utf8');
if (!/^[a-f0-9-]{36}$/.test(identity)) throw new Error('Invalid MQTT identity in ' + identityFile);
const uiPort = Number(process.env.PORT || 1880);
const digest = crypto.createHash('sha256').update(identity + '/' + uiPort).digest('hex');
process.env.SH_DASHBOARD_SESSION_ID = 'sh' + digest.slice(0, 20);

module.exports = {
  uiHost: '127.0.0.1',
  uiPort,
  userDir: runtime,
  flowFile: path.join(__dirname, 'flows.json'),
  flowFilePretty: true,
  nodesDir: ['node-red-node-sqlite', '@flowfuse/node-red-dashboard'].map(name => path.join(__dirname, 'node_modules', name)),
  httpAdminRoot: '/editor',
  editorTheme: { projects: { enabled: false } },
  externalModules: { autoInstall: false, palette: { allowInstall: false, allowUpload: false } },
  functionGlobalContext: {
    sh: { ...require('./lib/validate-event'), ...state },
    shState: state.createState(),
    shSchema: fs.readFileSync(path.join(__dirname, 'sql/schema.sql'), 'utf8')
  },
  logging: { console: { level: 'info', metrics: false, audit: false } },
  mqttReconnectTime: 1000
};
