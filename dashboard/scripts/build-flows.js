'use strict';
// Generate the importable flow from readable code and the Vue template.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const flow = [{ id: 'mission4', type: 'tab', label: 'SmartHarness · Mission 4', disabled: false, info: 'Use dashboard/settings.js. No ECU commands or invented telemetry.' }];
function node(id, type, name, props = {}, wires = []) {
  flow.push({ id, type, z: 'mission4', name, x: 240 + (flow.length % 4) * 240, y: 60 + Math.floor(flow.length / 4) * 90, ...props, wires });
}
function fn(id, name, func, wires, outputs = 1) { node(id, 'function', name, { func, outputs, noerr: 0, initialize: '', finalize: '', libs: [] }, wires); }
const ctx = "const s=global.get('shState'); const sh=global.get('sh');\n";
node('broker', 'mqtt-broker', 'Mosquitto local', { broker: '${MQTT_HOST}', port: '${MQTT_PORT}', clientid: '', autoConnect: true, usetls: false, protocolVersion: '4', keepalive: '15', cleansession: true, autoUnsubscribe: true });
node('db', 'sqlitedb', 'Historique persistant', { db: '${SH_DB_PATH}', mode: 'RWC' });
for (const ecu of ['a', 'b']) node(`mqtt-${ecu}`, 'mqtt in', `Pannes ECU ${ecu.toUpperCase()}`, { topic: `smartharness/ecu/${ecu}/faults`, qos: '1', datatype: 'utf8', broker: 'broker', nl: false, rap: true, rh: 0, inputs: 0 }, [['validate']]);
node('mqtt-gateway', 'mqtt in', 'Statut Gateway', { topic: 'smartharness/gateway/status', qos: '1', datatype: 'utf8', broker: 'broker', nl: false, rap: true, rh: 0, inputs: 0 }, [['gateway-status']]);
fn('validate', 'Valider et dater la réception', ctx + `
try { msg.event=sh.validateEvent(msg.topic,msg.payload); }
catch(e) { s.rejected++; s.last_error=e.message; node.warn(e.message); return null; }
msg.received_at=new Date().toISOString();
msg.params={$received_at:msg.received_at,$topic:msg.topic};
for(const [key,value] of Object.entries(msg.event)) msg.params['$'+key]=typeof value==='boolean'?Number(value):value;
if(s.pending.length>=256) {
  s.failed_writes++; s.last_error='File SQLite pleine : réception non enregistrée'; node.warn(s.last_error);
  return null;
}
s.pending.push(msg);
return sh.nextWrite(s);`, [['insert']]);
fn('gateway-status', 'Statut du Gateway uniquement', ctx + `
try { s.gateway=sh.validateStatus(msg.payload); s.gateway_received_at=new Date().toISOString(); if(s.gateway==='offline') s.circuits.forEach(c=>c.fresh=false); }
catch(e) { s.rejected++; s.last_error=e.message; node.warn(e.message); }
return null;`, []);
node('mqtt-state', 'status', 'Connexion au broker', { scope: ['mqtt-a'] }, [['mqtt-state-update']]);
fn('mqtt-state-update', 'Ne pas confondre MQTT et ECU', ctx + `
const connected=msg.status.text==='node-red:common.status.connected'||msg.status.text==='connected';
s.mqtt=connected?'connected':'disconnected';
if(!connected) { s.gateway='unknown'; s.circuits.forEach(c=>c.fresh=false); }
return null;`, []);
node('initialize', 'inject', 'Créer le schéma au démarrage', { props: [{p:'payload'}], repeat: '', once: true, onceDelay: 0.5, payload: '', payloadType: 'date' }, [['schema']]);
fn('schema', 'Schéma SQLite', "msg.topic=global.get('shSchema'); return msg;", [['schema-db']]);
node('schema-db', 'sqlite', 'Initialiser SQLite', { mydb: 'db', sqlquery: 'batch', sql: '' }, [['initialized']]);
fn('initialized', 'Base prête, vider la file de démarrage', ctx + `
s.ready=true; s.database='ready';
return [sh.nextWrite(s),{}];`, [['insert'], ['read-history']], 2);
node('insert', 'sqlite', 'Enregistrer chaque réception', { mydb: 'db', sqlquery: 'prepared', sql: 'INSERT INTO fault_events (received_at,topic,ecu,circuit,fault_code,active,voltage_mv,command_on,seq) VALUES ($received_at,$topic,$ecu,$circuit,$fault_code,$active,$voltage_mv,$command_on,$seq)' }, [['stored']]);
fn('stored', 'Confirmer seulement après écriture', ctx + `
s.database='ready'; sh.acceptStored(s,msg.event,msg.received_at); s.writing=false;
return [sh.nextWrite(s),{}];`, [['insert'], ['read-history']], 2);
node('read-history', 'sqlite', 'Relire les archives et le total', { mydb: 'db', sqlquery: 'fixed', sql: 'SELECT *, (SELECT COUNT(*) FROM fault_events) AS total_count FROM fault_events WHERE event_id IN (SELECT event_id FROM fault_events ORDER BY event_id DESC LIMIT 200) OR event_id IN (SELECT MAX(event_id) FROM fault_events GROUP BY circuit) ORDER BY event_id DESC' }, [['history']]);
fn('history', 'Archives distinctes de l’état actuel', ctx + `sh.restoreHistory(s,msg.payload); return null;`, []);
node('db-errors', 'catch', 'Erreurs SQLite', { scope: ['schema-db','insert','read-history'], uncaught: false }, [['db-error']]);
fn('db-error', 'Signaler les erreurs de stockage', ctx + `
s.database='error'; s.last_error='SQLite : '+(msg.error?.message||'erreur inconnue');
node.warn(s.last_error);
if(msg.error?.source?.id==='insert') { s.failed_writes++; s.writing=false; return sh.nextWrite(s); }
return null;`, [['insert']]);
node('tick', 'inject', 'Actualiser l’affichage', { props: [{p:'payload'}], repeat: '1', once: true, onceDelay: 1, payload: '', payloadType: 'date' }, [['snapshot']]);
fn('snapshot', 'État de supervision', ctx + 'msg.payload=sh.snapshot(s); return msg;', [['dashboard-ui']]);
node('api', 'http in', 'État local en JSON (lecture seule)', { url: '/api/snapshot', method: 'get', upload: false, swaggerDoc: '' }, [['api-snapshot']]);
fn('api-snapshot', 'Instantané pour vérification', ctx + "msg.payload=sh.snapshot(s); msg.headers={'Content-Type':'application/json','Cache-Control':'no-store'}; return msg;", [['api-response']]);
node('api-response', 'http response', 'Réponse', { statusCode: '', headers: {} });
node('ui-base', 'ui-base', 'SmartHarness', { path: '/dashboard', appIcon: '', includeClientData: true, acceptsClientConfig: [], showPathInSidebar: false, headerContent: 'page', navigationStyle: 'none', titleBarStyle: 'default', showReconnectNotification: true, notificationDisplayTime: 5 });
node('ui-theme', 'ui-theme', 'SmartHarness clair', { colors: { surface:'#ffffff',primary:'#246f64',bgPage:'#f4f7fa',groupBg:'#f4f7fa',groupOutline:'#f4f7fa' }, sizes: { density:'default',pagePadding:'16px',groupGap:'16px',groupBorderRadius:'8px',widgetGap:'12px' } });
node('ui-page', 'ui-page', 'Supervision', { ui:'ui-base',path:'/monitoring',icon:'car',layout:'grid',theme:'ui-theme',order:1,className:'',visible:true,disabled:false,breakpoints:[{name:'Default',px:0,cols:12}] });
node('ui-group', 'ui-group', 'Diagnostic', { page:'ui-page',width:12,height:1,order:1,showTitle:false,className:'',visible:true,disabled:false,groupType:'default' });
node('dashboard-ui', 'ui-template', 'Circuits et historique', { group:'ui-group',page:'',ui:'',order:1,width:12,height:0,head:'',format:fs.readFileSync(path.join(root,'ui/dashboard.html'),'utf8'),storeOutMessages:true,passthru:false,resendOnRefresh:true,templateScope:'local',className:'' });
fs.writeFileSync(path.join(root, 'flows.json'), JSON.stringify(flow, null, 2) + '\n');
