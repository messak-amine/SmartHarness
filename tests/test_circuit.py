
import unittest
from simulator.circuit import Circuit


class TestCircuit(unittest.TestCase):

    def test_initial_state(self):
        circuit = Circuit(1, "Headlights")

        self.assertFalse(circuit.command_on)
        self.assertTrue(circuit.connected)

    def test_voltage_when_on_and_connected(self):
        circuit = Circuit(1, "Headlights")

        circuit.command_on = True

        voltage = circuit.read_voltage_mv()

        self.assertEqual(voltage, 3300)

    def test_voltage_when_disconnected(self):
        circuit = Circuit(1, "Headlights")

        circuit.command_on = True
        circuit.connected = False

        voltage = circuit.read_voltage_mv()

        self.assertEqual(voltage, 0)

    def test_voltage_when_off_and_connected(self):
        circuit = Circuit(1, "Headlights")

        circuit.command_on = False
        circuit.connected = True

        voltage = circuit.read_voltage_mv()

        self.assertEqual(voltage, 0)

    def test_voltage_when_off_and_disconnected(self):
        circuit = Circuit(1, "Headlights")

        circuit.command_on = False
        circuit.connected = False

        voltage = circuit.read_voltage_mv()

        self.assertEqual(voltage, 0)
