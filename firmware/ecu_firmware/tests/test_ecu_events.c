#include <stdint.h>
#include <stdio.h>
#include "ecu_events.h"
static int total=0,failures=0;
#define CHECK(label,x) do { ++total; if(x) printf("[PASS] %s\n",label); \
 else {++failures;printf("[FAIL] %s\n",label);} }while(0)
int main(void)
{
  uint16_t seq = 37;
  sh_ecu_event_t e={0};
  CHECK("none is ignored", !sh_ecu_event_build('A',1,SH_EVENT_NONE,3300,true,&seq,&e));
  CHECK("seq unchanged on no event", seq==37);
  CHECK("open event accepted", sh_ecu_event_build('A',1,SH_EVENT_OPEN_DETECTED,0,true,&seq,&e));
  CHECK("open contract fields", e.ecu_role=='A' && e.circuit_id==1 && e.fault_code==1 && e.fault_active && e.command_on && e.voltage_mv==0 && e.sequence==37);
  CHECK("sequence increment", seq==38);
  CHECK("recovery accepted", sh_ecu_event_build('A',1,SH_EVENT_RECOVERED,3300,true,&seq,&e));
  CHECK("recovery code and flag", e.fault_code==0 && !e.fault_active && e.sequence==38);
  CHECK("intermittent prepared", sh_ecu_event_build('B',3,SH_EVENT_INTERMITTENT_DETECTED,0,true,&seq,&e));
  CHECK("intermittent code 2", e.fault_code==2 && e.fault_active && e.ecu_role=='B');
  CHECK("reject ECU A circuit 3", !sh_ecu_event_build('A',3,SH_EVENT_OPEN_DETECTED,0,true,&seq,&e));
  CHECK("reject invalid ECU", !sh_ecu_event_build('X',1,SH_EVENT_OPEN_DETECTED,0,true,&seq,&e));
  CHECK("reject null output", !sh_ecu_event_build('A',1,SH_EVENT_OPEN_DETECTED,0,true,&seq,0));
  CHECK("reject null sequence", !sh_ecu_event_build('A',1,SH_EVENT_OPEN_DETECTED,0,true,0,&e));
  seq=UINT16_MAX;
  CHECK("sequence max sent", sh_ecu_event_build('B',4,SH_EVENT_OPEN_DETECTED,0,true,&seq,&e) && e.sequence==UINT16_MAX);
  CHECK("sequence wraps", seq==0);
  printf("\nTests: %d/%d passed\n",total-failures,total);
  return failures==0?0:1;
}
