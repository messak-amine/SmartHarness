#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include "fault_detector.h"

static int total = 0, failures = 0;
#define CHECK(label, x) do { ++total; if (x) printf("[PASS] %s\n", label); \
  else { ++failures; printf("[FAIL] %s\n", label); } } while (0)
#define UPDATE(d,on,v,t) sh_fault_detector_update(&(d), (on), (v), (t))

int main(void)
{
    sh_fault_detector_t d;
    sh_fault_detector_init(&d);
    CHECK("initial normal", d.state == SH_FAULT_NORMAL);
    CHECK("normal sample", UPDATE(d,true,3300,0) == SH_EVENT_NONE);
    CHECK("off low does not fault", UPDATE(d,false,0,100) == SH_EVENT_NONE);
    CHECK("bad #1 no event", UPDATE(d,true,0,200) == SH_EVENT_NONE);
    CHECK("bad #2 no event", UPDATE(d,true,0,300) == SH_EVENT_NONE);
    CHECK("good resets bad count", UPDATE(d,true,3300,400) == SH_EVENT_NONE);
    CHECK("low must restart confirmation", UPDATE(d,true,0,500) == SH_EVENT_NONE);
    CHECK("second low", UPDATE(d,true,0,600) == SH_EVENT_NONE);
    CHECK("third low signals open", UPDATE(d,true,0,700) == SH_EVENT_OPEN_DETECTED);
    CHECK("state is open", d.state == SH_FAULT_OPEN);
    CHECK("no duplicate alert", UPDATE(d,true,0,800) == SH_EVENT_NONE);
    CHECK("good #1 no recovery", UPDATE(d,true,3300,900) == SH_EVENT_NONE);
    CHECK("bad resets good count", UPDATE(d,true,0,1000) == SH_EVENT_NONE);
    CHECK("OFF preserves latched fault", UPDATE(d,false,0,1100) == SH_EVENT_NONE && d.state == SH_FAULT_OPEN);
    CHECK("recovery good #1", UPDATE(d,true,3300,1200) == SH_EVENT_NONE);
    CHECK("recovery good #2", UPDATE(d,true,3300,1300) == SH_EVENT_NONE);
    CHECK("recovery good #3", UPDATE(d,true,3300,1400) == SH_EVENT_RECOVERED);
    CHECK("state restored normal", d.state == SH_FAULT_NORMAL);
    CHECK("no duplicate recovery", UPDATE(d,true,3300,1500) == SH_EVENT_NONE);
    CHECK("low #1 repeat", UPDATE(d,true,0,1600) == SH_EVENT_NONE);
    CHECK("low #2 repeat", UPDATE(d,true,0,1700) == SH_EVENT_NONE);
    CHECK("second confirmed fault => intermittent", UPDATE(d,true,0,1800) == SH_EVENT_INTERMITTENT_DETECTED);
    CHECK("intermittent latched", d.state == SH_FAULT_INTERMITTENT);
    CHECK("no duplicate intermittent", UPDATE(d,true,0,1900) == SH_EVENT_NONE);
    UPDATE(d,true,3300,2000); UPDATE(d,true,3300,2100);
    CHECK("intermittent recovery", UPDATE(d,true,3300,2200) == SH_EVENT_RECOVERED);

    /* After 30 seconds without confirmed faults, treat it as a new open. */
    UPDATE(d,true,0,33000); UPDATE(d,true,0,33100);
    CHECK("outside time window => open", UPDATE(d,true,0,33200) == SH_EVENT_OPEN_DETECTED);
    CHECK("threshold above cutoff", SH_FAULT_MIN_OK_MV == 2500U);

    sh_fault_detector_t second;
    sh_fault_detector_init(&second);
    CHECK("separate circuit remains independent", second.state == SH_FAULT_NORMAL);
    UPDATE(second,true,0,0); UPDATE(second,true,0,100);
    CHECK("different circuit can fault", UPDATE(second,true,0,200) == SH_EVENT_OPEN_DETECTED);

    /* uint32 elapsed time wraps; subtraction must still work. */
    sh_fault_detector_t wrap;
    sh_fault_detector_init(&wrap);
    UPDATE(wrap,true,0,UINT32_MAX-2U);
    UPDATE(wrap,true,0,UINT32_MAX-1U);
    CHECK("first fault near timer wrap", UPDATE(wrap,true,0,UINT32_MAX) == SH_EVENT_OPEN_DETECTED);
    UPDATE(wrap,true,3300,0); UPDATE(wrap,true,3300,1);
    CHECK("recovery after timer wrap", UPDATE(wrap,true,3300,2) == SH_EVENT_RECOVERED);
    UPDATE(wrap,true,0,3); UPDATE(wrap,true,0,4);
    CHECK("repeat inside window across wrap", UPDATE(wrap,true,0,5) == SH_EVENT_INTERMITTENT_DETECTED);

    printf("\nTests: %d/%d passed\n",total-failures,total);
    return failures == 0 ? 0 : 1;
}
