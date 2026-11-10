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
async function until(fn,label,timeout=20000,child) {
  const end=Date.now()+timeout; let last;
  while(Date.now()<end) {
    if (child && (!child.pid || child.exitCode !== null || child.signalCode !== null)) {
      throw new Error(`${label} : processus indisponible (code=${child.exitCode}, signal=${child.signalCode})`);
    }
    try { const value=await fn(); if(value) return value; } catch(e) { last=e; }
    await delay(100);
  }
  throw new Error(`Timeout: ${label}${last?' — '+last.message:''}`);
}
async function stop(child) {
  if(!child || child.exitCode!==null || child.signalCode!==null) return;
  const done=new Promise(resolve=>child.once('exit',resolve)); child.kill(); await done;
}

test('Chaîne réelle Mosquitto → Node-RED → SQLite, reprise et erreurs', {timeout:180000}, async t=>{
  const runtime=path.join(root,'.test-runtime');
  fs.mkdirSync(runtime,{recursive:true});
  const dir=fs.mkdtempSync(path.join(runtime,'pipeline-'));
  const mqttPort=await port(), httpPort=await port();
  const dbPath=path.join(dir,'events.sqlite');
  const brokerExe=process.env.MOSQUITTO_BIN||(process.platform==='win32'?'C:/Program Files/Mosquitto/mosquitto.exe':'mosquitto');
  const config=process.env.SH_TEST_MOSQUITTO_CONFIG || path.join(dir,'mosquitto.conf');
  const configText=`listener ${mqttPort} 127.0.0.1\nallow_anonymous true\npersistence false\n`;
  fs.writeFileSync(config,configText,{mode:0o600});
  let broker,red,client; let log='';
  function launch(command,args,env={}) {
    const child=spawn(command,args,{cwd:root,env:{...process.env,...env},windowsHide:true,stdio:['ignore','pipe','pipe']});
    child.stdout.on('data',b=>{log+=b.toString();}); child.stderr.on('data',b=>{log+=b.toString();});
    child.on('error',e=>{log+=e.stack;}); return child;
  }
  async function startBroker() {
    assert.equal(fs.readFileSync(config,'utf8'),configText,`Configuration Mosquitto : ${config}`);
    broker=launch(brokerExe,['-c',config]);
    await until(()=>new Promise(resolve=>{const s=net.connect(mqttPort,'127.0.0.1');s.once('connect',()=>{s.destroy();resolve(true);});s.once('error',()=>resolve(false));}),`Mosquitto -c ${config}`,20000,broker);
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
    await t.test('Navigateur : quatre vues, routage, données partagées et mobile', {skip:!process.env.SH_PLAYWRIGHT_MODULE}, async()=>{
      const {chromium}=require(process.env.SH_PLAYWRIGHT_MODULE);
      const browser=await chromium.launch({headless:true,...(process.env.SH_BROWSER_CHANNEL?{channel:process.env.SH_BROWSER_CHANNEL}:{})});
      try {
        const page=await browser.newPage({viewport:{width:1920,height:1080}});
        const errors=[];
        let sockets=0;
        page.on('pageerror',e=>errors.push(e.message));
        page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
        page.on('websocket',()=>sockets++);
        const base='http://127.0.0.1:'+httpPort+'/dashboard/monitoring';
        const names={overview:'Vue d’ensemble',circuits:'Circuits',analytics:'Analyses',history:'Historique'};
        async function checkView(view) {
          await until(async()=>await page.locator('[data-view="'+view+'"]:visible').count()===1,'vue '+view);
          assert.equal(await page.locator('[data-view]:visible').count(),1);
          assert.equal(await page.locator('nav [aria-current="location"]').count(),1);
          assert.equal(await page.locator('nav [aria-current="location"]').getAttribute('aria-label'),names[view]);
        }
        async function navigate(view) {
          await page.getByRole('button',{name:names[view],exact:true}).click();
          await checkView(view);
          await until(()=>new URL(page.url()).searchParams.get('shView')===view,'URL '+view);
          assert.ok(await page.evaluate(()=>window.scrollY<5));
        }
        await page.goto(base);
        await checkView('overview');
          assert.equal(await page.locator('.brand-copy small').innerText(),'AUTOMOTIVE DIAGNOSTIC SYSTEM');
          assert.equal(await page.locator('h1').textContent(),'Automotive Diagnostic Command Center');
          assert.doesNotMatch(await page.locator('.sh-v2').innerText(), /mission\s*0?4|\bM04\b|démonstration locale/i);
        assert.equal(await page.locator('.circuit:visible').count(),0);
        const before=await snapshot();
        const initialSockets=sockets;
        for(const view of ['circuits','analytics','history','overview'])await navigate(view);
        await page.goBack();await checkView('history');
        await page.goBack();await checkView('analytics');
        await page.goForward();await checkView('history');
        await navigate('overview');
        await page.locator('.marker').first().click();await checkView('circuits');
        await until(()=>new URL(page.url()).searchParams.get('shCircuit')==='1','sélection dans URL');
        assert.equal(await page.locator('.circuit.chosen').count(),1);
        await page.getByRole('button',{name:'Historique du circuit 1',exact:true}).click();await checkView('history');
        assert.equal(await page.getByLabel('Filtrer par circuit',{exact:true}).inputValue(),'1');
        assert.ok((await page.locator('tbody tr td:nth-child(3)').allTextContents()).every(t=>t==='A / 1'));
        await page.getByLabel('Filtrer par ECU',{exact:true}).selectOption('B');
        assert.match(await page.locator('tbody').innerText(),/Aucun événement/);
        await page.getByRole('button',{name:'Réinitialiser',exact:true}).click();
        assert.equal(await page.getByRole('button',{name:'Réinitialiser',exact:true}).isDisabled(),true);
        await navigate('analytics');
        for(const circuit of [1,2,3,4]) {
          const bar=page.locator('.bar-row').nth(circuit-1);
          assert.equal(Number(await bar.locator('strong').innerText()),before.history.filter(r=>r.circuit===circuit).length);
          await bar.focus();await bar.press('Enter');await checkView('history');
          assert.equal(await page.getByLabel('Filtrer par circuit',{exact:true}).inputValue(),String(circuit));
          await navigate('analytics');
        }
        await page.getByRole('button',{name:'Consulter les réceptions : Déconnexions'}).click();await checkView('history');
        assert.equal(await page.getByLabel('Filtrer par diagnostic').inputValue(),'1');
        await page.getByRole('button',{name:'Réinitialiser',exact:true}).click();
        // Receive real MQTT events while the circuit cards are hidden.
        await navigate('analytics');
        await publish(event(2,201));
        await until(async()=> (await snapshot()).total===before.total+1,'écriture hors vue circuits');
        await navigate('circuits');
        await until(async()=> (await page.locator('.circuit').nth(1).getAttribute('class')).includes('fault'),'panne partagée');
        await page.screenshot({path:path.join(dir,'dashboard-fault.png'),fullPage:true});
        await navigate('history');
        await publish(event(2,202,false));
        await until(async()=> (await snapshot()).total===before.total+2,'résolution hors vue circuits');
        await until(async()=>await page.locator('tbody tr').first().locator('td').nth(6).innerText()==='202','historique temps réel');
        await navigate('circuits');
        await until(async()=> (await page.locator('.circuit').nth(1).getAttribute('class')).includes('recovered'),'résolution partagée');
        await until(async()=>await page.locator('.circuit').nth(1).locator('.reception-flash').count()===1,'signal réception');
        const db=new DatabaseSync(dbPath,{readOnly:true});
        assert.deepEqual(db.prepare('SELECT fault_code,seq FROM fault_events ORDER BY event_id DESC LIMIT 2').all().map(r=>[r.fault_code,r.seq]),[[0,202],[1,201]]);
        db.close();
        assert.equal((await snapshot()).started_at,before.started_at);
        assert.equal((await snapshot()).total,before.total+2);
        assert.equal(sockets,initialSockets,'navigation conserves the Dashboard socket');
        await page.getByRole('button',{name:'Réduire la navigation',exact:true}).click();
        const nav=page.getByRole('button',{name:'Historique',exact:true});
        await nav.focus();assert.equal(await page.locator('.sh').getByRole('tooltip').isVisible(),true);
        await nav.press('Escape');assert.equal(await page.locator('.sh').getByRole('tooltip').count(),0);
        await nav.press('Enter');await checkView('history');
        await page.getByRole('button',{name:'Développer la navigation',exact:true}).click();
        // Direct loading and reload retain the selected workspace and filters.
        await page.goto(base+'?shView=history&shCircuit=2&shType=0');await checkView('history');
        assert.equal(await page.getByLabel('Filtrer par circuit',{exact:true}).inputValue(),'2');
        await page.reload();await checkView('history');
        assert.equal(await page.getByLabel('Filtrer par diagnostic').inputValue(),'0');
        await page.getByRole('button',{name:'Réinitialiser',exact:true}).click();
        for(const width of [5120,3440,1920,1440,1024,768,390]) {
          await page.setViewportSize({width,height:1080});await page.emulateMedia({reducedMotion:'reduce'});
          for(const view of ['overview','circuits','analytics','history']) {
            await navigate(view);
            assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'overflow '+width+' '+view);
            assert.ok(await page.locator('.reception-flash').evaluateAll(es=>es.every(e=>getComputedStyle(e).animationName==='none')));
          }
        }
          // Scroll both the document and the history table, then reach every item.
          for(const [width,height] of [[1920,1080],[3440,720],[1366,600],[1280,320],[1024,400],[768,500],[390,844],[667,375]]) {
            await page.setViewportSize({width,height});
            for(const collapsed of (width>1200?[false,true]:[false])) {
              const toggle=page.locator('.sidebar-toggle');
              if(await toggle.isVisible() && (await toggle.getAttribute('aria-expanded')==='false')!==collapsed)await toggle.click();
              for(const view of ['overview','circuits','analytics','history']) {
                await navigate(view);
                await page.evaluate(()=>{ const table=document.querySelector('.table-scroll');if(table)table.scrollTop=table.scrollHeight;window.scrollTo(0,document.documentElement.scrollHeight); });
                await page.waitForTimeout(60);
                const geometry=await page.locator('.sidebar').evaluate(el=>{
                  const r=el.getBoundingClientRect();const w=document.querySelector('.workspace').getBoundingClientRect();
                  return {top:r.top,bottom:r.bottom,overlap:innerWidth>800 && r.right>w.left+1,overflow:document.documentElement.scrollWidth>innerWidth};
                });
                assert.ok(geometry.top>=-1 && geometry.bottom<=height+1,JSON.stringify({width,height,view,geometry}));
                assert.equal(geometry.overlap,false);assert.equal(geometry.overflow,false);
                for(const name of Object.values(names)) {
                  const button=page.getByRole('button',{name,exact:true});
                  await button.focus();
                  if(width<=800)assert.equal(await button.locator('.nav-label').isVisible(),true,'mobile labels survive collapsed desktop');
                  assert.ok(await button.evaluate(el=>{
                    const r=el.getBoundingClientRect();const n=el.closest('nav').getBoundingClientRect();const icon=el.querySelector('svg').getBoundingClientRect();
                    return r.top>=Math.max(0,n.top)-1 && r.bottom<=Math.min(innerHeight,n.bottom)+1 && icon.left>=n.left && icon.right<=n.right && document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.closest('button')===el;
                  }),name+' accessible '+width+'x'+height);
                }
              }
            }
          }
          await page.setViewportSize({width:1920,height:1080});
        for(const view of ['overview','circuits','analytics','history']) {
          await navigate(view);
          const close=page.getByRole('button',{name:'Close',exact:true});if(await close.isVisible())await close.click();
          await page.screenshot({path:path.join(dir,'dashboard-'+view+'.png'),fullPage:true});
        }
        await page.setViewportSize({width:390,height:844});await navigate('overview');
        await page.screenshot({path:path.join(dir,'dashboard-mobile.png'),fullPage:true});
        assert.equal((await snapshot()).total,before.total+2);
        assert.deepEqual(errors,[]);
      } finally { await browser.close(); }
    });
    t.diagnostic(`Preuves et base SQLite : ${dir}`);
  } catch(error) { console.error(log.slice(-14000));throw error; }
});
