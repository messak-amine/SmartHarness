'use strict';

const path = require('node:path');
const fs = require('node:fs');
const state = require('./lib/state');
const runtime = path.resolve(process.env.SH_RUNTIME_DIR || path.join(__dirname, '.runtime'));
fs.mkdirSync(runtime, { recursive: true });
module.exports = {
  uiHost: '127.0.0.1',
  uiPort: Number(process.env.PORT || 1880),
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
