'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {DatabaseSync}=require('node:sqlite');
test('Schéma SQLite : répétitions, rollover, contraintes et paramètres',()=>{
  const db=new DatabaseSync(':memory:');
  try {
    db.exec(fs.readFileSync(path.join(__dirname,'../sql/schema.sql'),'utf8'));
    const insert=db.prepare('INSERT INTO fault_events(received_at,topic,ecu,circuit,fault_code,active,voltage_mv,command_on,seq) VALUES(?,?,?,?,?,?,?,?,?)');
    for(const seq of [65535,0,0]) insert.run('2026-11-03T12:00:00Z','smartharness/ecu/a/faults','A',1,1,1,0,1,seq);
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM fault_events').get().n,3);
    assert.throws(()=>insert.run('now','smartharness/ecu/a/faults','A',3,1,1,0,1,1));
    assert.throws(()=>insert.run('now','smartharness/ecu/a/faults','A',1,0,1,0,1,1));
    insert.run("'; DROP TABLE fault_events; --",'smartharness/ecu/a/faults','A',1,0,0,3300,1,1);
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM fault_events').get().n,4);
  } finally { db.close(); }
});
