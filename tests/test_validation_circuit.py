"""Supplement to the existing tests/test_circuit.py without replacing it."""
import unittest
from simulator.circuit import Circuit

class AdditionalCircuitTests(unittest.TestCase):
    def test_reconnection_restores_voltage_while_on(self):
        circuit = Circuit(1, "Headlights")
        circuit.command_on = True
        circuit.connected = False
        self.assertEqual(circuit.read_voltage_mv(), 0)
        circuit.connected = True
        self.assertEqual(circuit.read_voltage_mv(), 3300)
