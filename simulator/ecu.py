
class ECU:
    def __init__(self, name, circuits):
        self.name = name
        self.circuits = circuits
        self.active_faults = {
            circuit.circuit_id: False for circuit in circuits
        }
        self.sequence = 0

    def scan(self):
        events = []

        for circuit in self.circuits:
            if not circuit.command_on:
                continue

            voltage = circuit.read_voltage_mv()
            fault_detected = voltage < 1000
            previous_fault = self.active_faults[circuit.circuit_id]

            if fault_detected == previous_fault:
                continue

            self.active_faults[circuit.circuit_id] = fault_detected
            self.sequence = (self.sequence + 1) % 65536

            event = {
                "ecu": self.name,
                "circuit": circuit.circuit_id,
                "fault_code": 1 if fault_detected else 0,
                "active": fault_detected,
                "voltage_mv": voltage,
                "command_on": circuit.command_on,
                "seq": self.sequence
            }

            events.append(event)

        return events
