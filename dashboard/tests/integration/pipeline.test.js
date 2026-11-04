'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const net=require('node:net');
const {spawn}=require('node:child_process');
const mqtt=require('mqtt');
const {DatabaseSync}=require('node:sqlite');
const root=path.resolve(__dirname,'../..');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function port() { const s=net.createServer(); await new Promise(resolve=>s.listen(0,'127.0.0.1',resolve)); const p=s.address().port; await new Promise(resolve=>s.close(resolve)); return p; }
async function until(fn,label,timeout=20000) {
  const end=Date.now()+timeout; let last;
  while(Date.now()<end) { try { const value=await fn(); if(value) return value; } catch(e) { last=e; } await delay(100); }
  throw new Error(`Timeout: ${label}${last?' — '+last.message:''}`);
}
async function stop(child) {
  if(!child || child.exitCode!==null || child.signalCode!==null) return;
  const done=new Promise(resolve=>child.once('exit',resolve)); child.kill(); await done;
}

test('Chaîne réelle Mosquitto → Node-RED → SQLite, reprise et erreurs', {timeout:180000}, async t=>{
  const dir=fs.mkdtempSync(path.join(fs.mkdirSync(path.join(root,'.test-runtime'),{recursive:true})||path.join(root,'.test-runtime'),'pipeline-'));
  const mqttPort=await port(), httpPort=await port();
  const dbPath=path.join(dir,'events.sqlite');
  const brokerExe=process.env.MOSQUITTO_BIN||(process.platform==='win32'?'C:/Program Files/Mosquitto/mosquitto.exe':'mosquitto');
  const config=path.join(dir,'mosquitto.conf');
  fs.writeFileSync(config,`listener ${mqttPort} 127.0.0.1\nallow_anonymous true\npersistence false\n`);
  let broker,red,client; let log='';
  function launch(command,args,env={}) {
    const child=spawn(command,args,{cwd:root,env:{...process.env,...env},windowsHide:true,stdio:['ignore','pipe','pipe']});
    child.stdout.on('data',b=>{log+=b.toString();}); child.stderr.on('data',b=>{log+=b.toString();});
    child.on('error',e=>{log+=e.stack;}); return child;
  }
  async function startBroker() {
    broker=launch(brokerExe,['-c',config]);
    await until(()=>new Promise(resolve=>{const s=net.connect(mqttPort,'127.0.0.1');s.once('connect',()=>{s.destroy();resolve(true);});s.once('error',()=>resolve(false));}),'broker');
  }
  async function startRed() {
    red=launch(process.execPath,['scripts/start.js'],{PORT:String(httpPort),MQTT_HOST:'127.0.0.1',MQTT_PORT:String(mqttPort),SH_DB_PATH:dbPath,SH_RUNTIME_DIR:path.join(dir,'runtime')});
    await until(async()=>{const s=await snapshot();return s.ready&&s.mqtt==='connected';},'Node-RED et SQLite',60000);
  }
  async function snapshot() { const r=await fetch(`http://127.0.0.1:${httpPort}/api/snapshot`); return r.json(); }
  async function publish(event,topic=`smartharness/ecu/${event.ecu.toLowerCase()}/faults`) {
    await client.publishAsync(topic,JSON.stringify(event),{qos:1,retain:false});
  }
  const event=(circuit,seq,active=true)=>({ecu:circuit<3?'A':'B',circuit,fault_code:active?1:0,active,voltage_mv:active?0:3300,command_on:true,seq});
  t.after(async()=>{if(client)await client.endAsync(true);await stop(red);await stop(broker);fs.writeFileSync(path.join(dir,'process.log'),log);});
  try {
    await startBroker(); await startRed();
    client=await mqtt.connectAsync(`mqtt://127.0.0.1:${mqttPort}`,{reconnectPeriod:200,connectTimeout:3000});
    await t.test('Démarrage UNKNOWN et Dashboard servi',async()=>{
      const s=await snapshot();assert.ok(s.circuits.every(c=>c.status==='UNKNOWN'));assert.equal(s.total,0);
      const response=await fetch(`http://127.0.0.1:${httpPort}/dashboard/monitoring`);assert.equal(response.status,200);
    });
    await t.test('Pannes puis résolutions des quatre circuits, huit insertions',async()=>{
      await client.publishAsync('smartharness/gateway/status','{"status":"online"}',{qos:1,retain:true});
      for(const c of [1,2,3,4])await publish(event(c,1));
      await until(async()=>{const s=await snapshot();return s.total===4&&s.circuits.every(c=>c.status==='FAULT');},'quatre pannes');
      for(const c of [1,2,3,4])await publish(event(c,2,false));
      const s=await until(async()=>{const s=await snapshot();return s.total===8&&s.circuits.every(c=>c.status==='RECOVERED')&&s;},'quatre résolutions');
      assert.equal(s.gateway,'online');assert.ok(s.history.every(row=>!Number.isNaN(Date.parse(row.received_at))));
    });
    await t.test('JSON invalide et champs incohérents : aucun enregistrement',async()=>{
      for(const value of ['{bad',JSON.stringify({...event(1,3),circuit:3}),JSON.stringify({ecu:'A'}),JSON.stringify({...event(1,3),active:'true'})])await client.publishAsync('smartharness/ecu/a/faults',value,{qos:1});
      const s=await until(async()=>{const s=await snapshot();return s.rejected===4&&s;},'quatre rejets');assert.equal(s.total,8);
    });
    await t.test('Doublons et rollover conservés, OFF ne résout rien',async()=>{
      for(const seq of [65535,0,0])await publish({...event(1,seq),command_on:false});
      const s=await until(async()=>{const s=await snapshot();return s.total===11&&s;},'répétitions');
      assert.deepEqual(s.history.slice(0,3).map(r=>r.seq),[0,0,65535]);assert.equal(s.circuits[0].status,'FAULT');
    });
    await t.test('Erreur SQLite explicite sans faux succès',async()=>{
      const db=new DatabaseSync(dbPath); db.exec("CREATE TRIGGER reject_test BEFORE INSERT ON fault_events WHEN NEW.seq=4242 BEGIN SELECT RAISE(ABORT,'test storage failure'); END");db.close();
      await publish(event(2,4242));
      const s=await until(async()=>{const s=await snapshot();return s.failed_writes===1&&s;},'erreur SQLite');
      assert.equal(s.total,11);assert.equal(s.database,'error');assert.equal(s.circuits[1].status,'RECOVERED');
      const cleanup=new DatabaseSync(dbPath);cleanup.exec('DROP TRIGGER reject_test');cleanup.close();
    });
    await t.test('Coupure broker et reconnexion avec nouvelle réception',async()=>{
      await stop(broker);
      await until(async()=>{const s=await snapshot();return s.mqtt==='disconnected'&&s.gateway==='unknown';},'déconnexion');
      await startBroker();
      await until(async()=>client.connected&&(await snapshot()).mqtt==='connected','reconnexion');
      await delay(300); await publish(event(3,3));
      await until(async()=>(await snapshot()).total===12,'réception après reconnexion');
    });
    await t.test('Redémarrage Node-RED : historique persistant, état courant UNKNOWN',async()=>{
      await stop(red);await startRed();
      const s=await until(async()=>{const s=await snapshot();return s.total===12&&s;},'restauration');
      assert.ok(s.circuits.every(c=>c.status==='UNKNOWN'));assert.ok(s.circuits.every(c=>c.historical));
      await publish(event(4,4,false));await until(async()=>(await snapshot()).total===13,'insertion après redémarrage');
    });
    await t.test('Simulation Gateway originale → huit événements persistés', {skip:!process.env.SH_GATEWAY_DIR||!process.env.SH_PYTHON}, async()=>{
      const before=(await snapshot()).total;
      const gateway=spawn(process.env.SH_PYTHON,['-B','-m','simulator.mqtt_demo','--host','127.0.0.1','--port',String(mqttPort)],{cwd:process.env.SH_GATEWAY_DIR,windowsHide:true,stdio:['ignore','pipe','pipe']});
      gateway.stdout.on('data',b=>{log+=b.toString();});gateway.stderr.on('data',b=>{log+=b.toString();});
      const code=await new Promise((resolve,reject)=>{gateway.once('error',reject);gateway.once('exit',resolve);});
      assert.equal(code,0);
      const s=await until(async()=>{const s=await snapshot();return s.total===before+8&&!s.writing&&s.pending===0&&s;},'Gateway réel');
      const rows=s.history.slice(0,8);
      assert.equal(rows.filter(row=>row.fault_code===1).length,4);
      assert.equal(rows.filter(row=>row.fault_code===0).length,4);
      assert.ok(s.circuits.every(c=>c.status==='RECOVERED'));
    });
    await t.test('Rafale de 100 transitions : ordre de réception conservé',async()=>{
      const before=(await snapshot()).total;
      for(let seq=100;seq<200;seq++)await publish(event(1,seq,seq%2===0));
      const s=await until(async()=>{const s=await snapshot();return s.total===before+100&&!s.writing&&s.pending===0&&s;},'rafale sérialisée');
      assert.equal(s.circuits[0].status,'RECOVERED');assert.equal(s.circuits[0].last.seq,199);
      assert.deepEqual(s.history.slice(0,100).map(row=>row.seq),Array.from({length:100},(_,i)=>199-i));
    });
    await t.test('Navigateur : quatre circuits, historique, filtre et écran mobile', {skip:!process.env.SH_PLAYWRIGHT_MODULE}, async()=>{
      const {chromium}=require(process.env.SH_PLAYWRIGHT_MODULE);
      const browser=await chromium.launch({headless:true,...(process.env.SH_BROWSER_CHANNEL?{channel:process.env.SH_BROWSER_CHANNEL}:{})});
      try {
        const page=await browser.newPage({viewport:{width:1440,height:1000}});
        const errors=[];page.on('pageerror',e=>errors.push(e.message));
        await page.goto(`http://127.0.0.1:${httpPort}/dashboard/monitoring`);
        await page.locator('.sh .circuit').last().waitFor();
        assert.equal(await page.locator('.sh .circuit').count(),4);
        assert.match(await page.locator('.sh').innerText(),/Historique des diagnostics/);
        await page.locator('.history select').selectOption('1');
        await until(async()=>{
          const values=await page.locator('tbody tr td:nth-child(3)').allTextContents();
          return values.length>0&&values.every(value=>value==='A / 1');
        },'filtre circuit');
        await page.locator('.history select').selectOption('all');
        await page.screenshot({path:path.join(dir,'dashboard-desktop.png'),fullPage:true});
        await page.setViewportSize({width:390,height:844});
        await page.screenshot({path:path.join(dir,'dashboard-mobile.png'),fullPage:true});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
        const mobileBounds=await page.locator('.sh, .sh .circuit, .sh .pill, .sh .history').evaluateAll(elements=>elements.map(e=>({name:e.className,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right})));
        assert.ok(mobileBounds.every(b=>b.left>=0&&b.right<=390),JSON.stringify(mobileBounds));
        assert.deepEqual(errors,[]);
      } finally { await browser.close(); }
    });
    t.diagnostic(`Preuves et base SQLite : ${dir}`);
  } catch(error) { console.error(log.slice(-14000));throw error; }
});
