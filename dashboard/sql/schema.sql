CREATE TABLE IF NOT EXISTS fault_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  received_at TEXT NOT NULL,
  topic TEXT NOT NULL CHECK (topic IN ('smartharness/ecu/a/faults', 'smartharness/ecu/b/faults')),
  ecu TEXT NOT NULL CHECK (ecu IN ('A', 'B')),
  circuit INTEGER NOT NULL CHECK (circuit BETWEEN 1 AND 4),
  fault_code INTEGER NOT NULL CHECK (fault_code IN (0, 1, 2)),
  active INTEGER NOT NULL CHECK (active IN (0, 1)),
  voltage_mv INTEGER NOT NULL CHECK (voltage_mv BETWEEN 0 AND 65535),
  command_on INTEGER NOT NULL CHECK (command_on IN (0, 1)),
  seq INTEGER NOT NULL CHECK (seq BETWEEN 0 AND 65535),
  CHECK ((ecu = 'A' AND circuit IN (1, 2) AND topic = 'smartharness/ecu/a/faults')
      OR (ecu = 'B' AND circuit IN (3, 4) AND topic = 'smartharness/ecu/b/faults')),
  CHECK ((fault_code = 0 AND active = 0) OR (fault_code IN (1, 2) AND active = 1))
);
CREATE INDEX IF NOT EXISTS idx_fault_events_circuit_id ON fault_events(circuit, event_id DESC);
CREATE INDEX IF NOT EXISTS idx_fault_events_received_at ON fault_events(received_at);
