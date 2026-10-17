
class Circuit:
    def __init__(self, circuit_id, name):
        self.circuit_id = circuit_id
        self.name = name
        self.command_on = False
        self.connected = True

    def read_voltage_mv(self):
        if self.command_on and self.connected:
            return 3300

        return 0
