'use strict';
// Synthetic MQTT inputs: uses the real contract, not physical measurements.
const mqtt=require('mqtt');
async function main() {
  const client=await mqtt.connectAsync(`mqtt://${process.env.MQTT_HOST||'127.0.0.1'}:${process.env.MQTT_PORT||1883}`, {reconnectPeriod:0,connectTimeout:5000});
  try {
    await client.publishAsync('smartharness/gateway/status',JSON.stringify({status:'online'}),{qos:1,retain:true});
    const seq={A:0,B:0};
    for(const active of [true,false]) for(const circuit of [1,2,3,4]) {
      const ecu=circuit<3?'A':'B';
      const event={ecu,circuit,fault_code:active?1:0,active,voltage_mv:active?0:3300,command_on:true,seq:++seq[ecu]};
      await client.publishAsync(`smartharness/ecu/${ecu.toLowerCase()}/faults`,JSON.stringify(event),{qos:1,retain:false});
      console.log('SIMULATION MQTT',JSON.stringify(event));
      await new Promise(resolve=>setTimeout(resolve,500));
    }
    await client.publishAsync('smartharness/gateway/status','{"status":"offline"}',{qos:1,retain:true});
  } finally { await client.endAsync(); }
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
