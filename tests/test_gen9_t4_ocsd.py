import importlib
import json
import os
import sys
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gen9_t4_ocsd as ocsd
import gen9_t4_ocsd_register as register


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_profile(name, **env):
    """Re-import the daemon under OCSD_PROFILE=name (plus any extra env)."""
    values = {"OCSD_PROFILE": name, **env}
    with mock.patch.dict(os.environ, values):
        importlib.reload(ocsd)


def load_default():
    with mock.patch.dict(os.environ, {}, clear=False):
        for key in ("OCSD_PROFILE", "OCSD_ILO_SENSOR", "OCSD_PUBLISH_OFFSET_C", "OCSD_ILO_OFFSET_C"):
            os.environ.pop(key, None)
        importlib.reload(ocsd)


class ProfileCase(unittest.TestCase):
    PROFILE = "dl380-gen9-t4"

    @classmethod
    def setUpClass(cls):
        load_profile(cls.PROFILE)

    @classmethod
    def tearDownClass(cls):
        load_default()


def synthetic_snapshot(address):
    memory = bytearray(0x4000)
    header = bytearray(64)
    header[0] = 2
    struct.pack_into("<H", header, 4, 0x4000)
    header[8] = 102
    header[12] = ocsd.RECORD_SIZE
    struct.pack_into("<I", header, 16, address + 64)
    header[32] = 5
    header[56] = ocsd.NATIVE_COUNT
    struct.pack_into("<I", header, 60, ocsd.checksum_header(header))
    memory[:64] = header
    for index, bus in enumerate(ocsd.NATIVE_BUSES):
        native = bytearray(64)
        native[0] = 1
        native[4] = bus
        struct.pack_into("<I", native, 60,
                         (-sum(struct.unpack_from("<15I", native))) & 0xffffffff)
        offset = 64 + index * ocsd.RECORD_SIZE
        memory[offset:offset + 64] = native
    return bytes(memory)


class ProtocolTests:
    """Protocol suite, run once per profile by the subclasses below."""

    def setUp(self):
        self.address = 0x70000000
        self.snapshot = synthetic_snapshot(self.address)

    def test_synthetic_gen9_snapshot(self):
        self.assertEqual(len(self.snapshot), 0x4000)
        ocsd.validate_header(self.snapshot[:64], self.address)
        ocsd.validate_native_headers(self.snapshot)
        self.assertEqual(self.snapshot[56], ocsd.NATIVE_COUNT)
        self.assertFalse(any(self.snapshot[ocsd.RECORD_OFFSET:
                                           ocsd.RECORD_OFFSET + ocsd.RECORD_SIZE]))

    def test_example_service_is_manual_only(self):
        examples = Path(__file__).resolve().parent.parent / "examples" / "systemd"
        publisher = (examples / "gen9-t4-ocsd.service").read_text("ascii")
        self.assertNotIn("[Install]", publisher)
        self.assertFalse((examples / "gen9-t4-ocsd-register.service").exists())

    def test_header_rejects_corruption(self):
        header = self.snapshot[:64]
        enabled = ocsd.header_with_count(header, ocsd.OWNED_COUNT)
        ocsd.validate_header(enabled, self.address)
        self.assertEqual(ocsd.header_with_count(enabled, ocsd.NATIVE_COUNT), header)
        corrupt = bytearray(enabled)
        corrupt[16] ^= 1
        with self.assertRaises(ValueError):
            ocsd.validate_header(corrupt, self.address)

    def test_claim_rejects_occupied_slot_without_writing(self):
        memory = bytearray(self.snapshot)
        memory[ocsd.RECORD_OFFSET] = 1
        before = bytes(memory)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(ocsd, "STATE", Path(directory) / "ownership.json"):
            with self.assertRaisesRegex(ValueError, "not empty"):
                ocsd.claim(memory, self.address)
        self.assertEqual(bytes(memory), before)

    def test_claim_rejects_corrupt_native_record_without_writing(self):
        memory = bytearray(self.snapshot)
        memory[64 + 4] = 9
        before = bytes(memory)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(ocsd, "STATE", Path(directory) / "ownership.json"):
            with self.assertRaisesRegex(ValueError, "native OCSD"):
                ocsd.claim(memory, self.address)
        self.assertEqual(bytes(memory), before)

    def test_ownership_and_sensor_checksum(self):
        record = ocsd.make_record(65, 65535)
        self.assertTrue(ocsd.owned_record(record))
        self.assertEqual(record[84], 65)
        self.assertEqual(struct.unpack_from("<H", record, 88)[0], 65535)
        corrupt = bytearray(record)
        corrupt[84] = 66
        self.assertFalse(ocsd.owned_record(corrupt))
        self.assertTrue(ocsd.owned_record(ocsd.make_record(38, 0)))

    def test_discover_unique_smbios_allocation(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / "229-0"
            entry.mkdir()
            raw = bytes((229, 20, 0x83, 0)) + b"$OCS" + struct.pack(
                "<QI", self.address, 0x4000) + b"\0\0"
            (entry / "raw").write_bytes(raw)
            self.assertEqual(ocsd.discover_ocsd(Path(directory)), self.address)
            (entry / "raw").write_bytes(raw[:8] + struct.pack(
                "<QI", self.address, 0x2000) + b"\0\0")
            with self.assertRaises(ValueError):
                ocsd.discover_ocsd(Path(directory))

    def test_ilo_reading_parser(self):
        sample = "Sensor ID : 21-PCI 1\n Sensor Reading        : 53 (+/- 0) degrees C\n"
        self.assertEqual(ocsd.parse_ilo_temperature(sample), 53)
        self.assertIsNone(ocsd.parse_ilo_temperature(" Sensor Reading : Disabled\n"))

    def test_gpu_telemetry_rejects_wrong_pci_identity(self):
        with mock.patch.object(ocsd.subprocess, "check_output",
                               return_value=b"00000000:06:00.0, 58\n"):
            with self.assertRaisesRegex(ValueError, "PCI identity mismatch"):
                ocsd.gpu_temperature()

    def test_ilo_parser_rejects_unavailable_reading(self):
        self.assertIsNone(ocsd.parse_ilo_temperature(" Sensor Reading : Not Available\n"))

    def test_registration_never_resets_ilo_without_opt_in(self):
        with mock.patch.object(register, "publisher_record_present", return_value=True), \
                mock.patch.object(register, "sensor_matches_gpu", return_value=False), \
                mock.patch.object(ocsd, "validate_workload_units") as configured, \
                mock.patch.object(register.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "requires --allow-ilo-reset"):
                register.main()
        configured.assert_not_called()
        run.assert_not_called()

    def test_registration_opt_in_still_requires_idle_workloads(self):
        with mock.patch.object(register, "publisher_record_present", return_value=True), \
                mock.patch.object(register, "sensor_matches_gpu", return_value=False), \
                mock.patch.object(ocsd, "validate_workload_units"), \
                mock.patch.object(ocsd, "workloads_active", return_value=True), \
                mock.patch.object(register.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "GPU workload is active"):
                register.main(allow_ilo_reset=True)
        run.assert_not_called()

    def test_registration_opt_in_requires_configured_workloads(self):
        with mock.patch.object(register, "publisher_record_present", return_value=True), \
                mock.patch.object(register, "sensor_matches_gpu", return_value=False), \
                mock.patch.object(ocsd, "validate_workload_units",
                                  side_effect=ValueError("units not configured")), \
                mock.patch.object(register.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "units not configured"):
                register.main(allow_ilo_reset=True)
        run.assert_not_called()

    def test_registration_opt_in_refuses_hot_gpu(self):
        with mock.patch.object(register, "publisher_record_present", return_value=True), \
                mock.patch.object(register, "sensor_matches_gpu", return_value=False), \
                mock.patch.object(ocsd, "validate_workload_units"), \
                mock.patch.object(ocsd, "workloads_active", return_value=False), \
                mock.patch.object(ocsd, "gpu_temperature", return_value=70), \
                mock.patch.object(register.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "GPU is not cool"):
                register.main(allow_ilo_reset=True)
        run.assert_not_called()

    def test_registration_opt_in_resets_once_only_when_cool_and_idle(self):
        with mock.patch.object(register, "publisher_record_present", return_value=True), \
                mock.patch.object(register, "sensor_matches_gpu",
                                  side_effect=[False, True]), \
                mock.patch.object(ocsd, "validate_workload_units"), \
                mock.patch.object(ocsd, "workloads_active", return_value=False), \
                mock.patch.object(ocsd, "gpu_temperature", return_value=45), \
                mock.patch.object(register.time, "sleep"), \
                mock.patch.object(register.subprocess, "run") as run:
            register.main(allow_ilo_reset=True)
        run.assert_called_once()
        self.assertEqual(run.call_args[0][0], ["/usr/sbin/ilorest", "iloreset"])

    def test_workload_units_must_be_real_services(self):
        with mock.patch.object(ocsd, "WORKLOAD_UNITS", ()):
            with self.assertRaisesRegex(ValueError, "OCSD_WORKLOAD_UNITS"):
                ocsd.validate_workload_units()
        with mock.patch.object(ocsd, "WORKLOAD_UNITS", ("--unsafe.service",)):
            with self.assertRaisesRegex(ValueError, "invalid GPU workload"):
                ocsd.validate_workload_units()
        with mock.patch.object(ocsd, "WORKLOAD_UNITS", ("gpu-worker.service",)), \
                mock.patch.object(ocsd.subprocess, "check_output", return_value=b"loaded\n"):
            ocsd.validate_workload_units()
        with mock.patch.object(ocsd, "WORKLOAD_UNITS", ("missing.service",)), \
                mock.patch.object(ocsd.subprocess, "check_output", return_value=b"not-found\n"):
            with self.assertRaisesRegex(ValueError, "not loaded"):
                ocsd.validate_workload_units()

    def test_hot_gpu_retries_stop_while_workload_remains_active(self):
        with mock.patch.object(ocsd, "workloads_active", side_effect=[True, False]), \
                mock.patch.object(ocsd, "stop_workloads") as stop:
            self.assertTrue(ocsd.request_thermal_stop(82, False, False))
            self.assertTrue(ocsd.request_thermal_stop(83, False, True))
            self.assertTrue(ocsd.request_thermal_stop(84, False, True))
            self.assertFalse(ocsd.request_thermal_stop(60, False, True))
            self.assertEqual(stop.call_count, 2)
        with mock.patch.object(ocsd, "stop_workloads") as stop:
            self.assertTrue(ocsd.request_thermal_stop(85, True, False))
            stop.assert_called_once()

    def test_claim_publishes_fail_high_before_stop_request(self):
        memory = bytearray(self.snapshot)
        observed = []

        def inspect_stop():
            record = bytes(memory[ocsd.RECORD_OFFSET:
                                  ocsd.RECORD_OFFSET + ocsd.RECORD_SIZE])
            observed.append((memory[56], record[84], ocsd.owned_record(record)))
            return False

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(ocsd, "STATE", Path(directory) / "ownership.json"), \
                mock.patch.object(ocsd, "boot_id", return_value="boot-one"), \
                mock.patch.object(ocsd, "gpu_temperature", side_effect=RuntimeError("NVML")), \
                mock.patch.object(ocsd, "stop_workloads", side_effect=inspect_stop):
            ocsd.claim(memory, self.address)
        self.assertEqual(observed, [(ocsd.OWNED_COUNT, 85, True)])

    def test_claim_write_failure_still_requests_workload_stop(self):
        class FailingMemory(bytearray):
            def __setitem__(self, key, value):
                if (isinstance(key, slice) and key.start == ocsd.RECORD_OFFSET
                        and getattr(self, "fail_once", True)):
                    self.fail_once = False
                    raise RuntimeError("OCSD write failed")
                return super().__setitem__(key, value)

        memory = FailingMemory(self.snapshot)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(ocsd, "STATE", Path(directory) / "ownership.json"), \
                mock.patch.object(ocsd, "boot_id", return_value="boot-one"), \
                mock.patch.object(ocsd, "gpu_temperature", return_value=45), \
                mock.patch.object(ocsd, "stop_workloads", return_value=False) as stop:
            with self.assertRaisesRegex(RuntimeError, "OCSD write failed"):
                ocsd.claim(memory, self.address)
            stop.assert_called_once()
            self.assertFalse(ocsd.STATE.exists())
        self.assertEqual(bytes(memory), self.snapshot)

    def test_update_publishes_fail_high_before_failed_status_check(self):
        memory = bytearray(self.snapshot)
        active = ocsd.header_with_count(memory[:64], ocsd.OWNED_COUNT)
        memory[:64] = active
        observed = []

        def inspect_status():
            record = bytes(memory[ocsd.RECORD_OFFSET:
                                  ocsd.RECORD_OFFSET + ocsd.RECORD_SIZE])
            observed.append((record[84], ocsd.owned_record(record)))
            raise subprocess.TimeoutExpired("systemctl", 5)

        with mock.patch.object(ocsd, "workloads_active", side_effect=inspect_status), \
                mock.patch.object(ocsd, "stop_workloads", return_value=False) as stop:
            counter, warning = ocsd.publish_and_guard(
                memory, active, 1, 85, True, True)
        self.assertEqual((counter, warning), (2, True))
        self.assertEqual(observed, [(85, True)])
        stop.assert_called_once()

    def test_update_counter_wraps_in_synthetic_record(self):
        memory = bytearray(self.snapshot)
        active = ocsd.header_with_count(memory[:64], ocsd.OWNED_COUNT)
        memory[:64] = active
        counter, warning = ocsd.publish_and_guard(
            memory, active, 65535, 45, False, False)
        record = bytes(memory[ocsd.RECORD_OFFSET:
                              ocsd.RECORD_OFFSET + ocsd.RECORD_SIZE])
        self.assertEqual((counter, warning), (0, False))
        self.assertEqual(struct.unpack_from("<H", record, 88)[0], 0)
        self.assertTrue(ocsd.owned_record(record))

    def test_update_header_mismatch_requests_workload_stop(self):
        memory = bytearray(self.snapshot)
        active = ocsd.header_with_count(memory[:64], ocsd.OWNED_COUNT)
        memory[:64] = active
        with mock.patch.object(ocsd, "stop_workloads", return_value=False) as stop:
            with self.assertRaisesRegex(RuntimeError, "header changed"):
                ocsd.publish_and_guard(memory, self.snapshot[:64], 1, 45, False, False)
            stop.assert_called_once()

    def test_stop_timeout_is_nonfatal(self):
        with mock.patch.object(ocsd.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("systemctl", 5)):
            self.assertFalse(ocsd.stop_workloads())

    def test_ownership_recovers_after_crash_and_new_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "ownership.json"
            memory = bytearray(self.snapshot)
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "gpu_temperature", return_value=38), mock.patch.object(
                    ocsd, "boot_id", return_value="boot-one"):
                original, active, counter = ocsd.claim(memory, self.address)
                self.assertEqual(counter, 1)
                self.assertEqual(memory[56], ocsd.OWNED_COUNT)
                original, active, counter = ocsd.claim(memory, self.address)
                self.assertEqual(counter, 2)
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "gpu_temperature", return_value=39), mock.patch.object(
                    ocsd, "boot_id", return_value="boot-two"):
                original, active, counter = ocsd.claim(memory, self.address)
                self.assertEqual(counter, 3)
                self.assertIn("boot-two", state.read_text())
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "workloads_active", return_value=False), mock.patch.object(
                    ocsd, "gpu_temperature", return_value=39), mock.patch.object(
                    ocsd.time, "sleep", return_value=None):
                ocsd.restore(memory, original, active)
            self.assertEqual(bytes(memory), self.snapshot)
            self.assertFalse(state.exists())

    def test_restore_waits_for_cool_gpu(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "ownership.json"
            memory = bytearray(self.snapshot)
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "gpu_temperature", return_value=70), mock.patch.object(
                    ocsd, "boot_id", return_value="boot-one"):
                original, active, _ = ocsd.claim(memory, self.address)
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "workloads_active", return_value=False), mock.patch.object(
                    ocsd, "gpu_temperature", side_effect=[70, 64, 55, 54, 53]), mock.patch.object(
                    ocsd.time, "sleep", return_value=None) as sleep:
                ocsd.restore(memory, original, active)
            self.assertEqual(sleep.call_count, 4)
            self.assertEqual(bytes(memory), self.snapshot)
            self.assertFalse(state.exists())

    def test_restore_keeps_sensor_if_telemetry_stays_hot(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "ownership.json"
            memory = bytearray(self.snapshot)
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "gpu_temperature", return_value=70), mock.patch.object(
                    ocsd, "boot_id", return_value="boot-one"):
                original, active, _ = ocsd.claim(memory, self.address)
            times = iter([0, 0, 0, 91])
            with mock.patch.object(ocsd, "STATE", state), mock.patch.object(
                    ocsd, "workloads_active", return_value=False), mock.patch.object(
                    ocsd, "gpu_temperature", return_value=70), mock.patch.object(
                    ocsd.time, "monotonic", side_effect=lambda: next(times)), mock.patch.object(
                    ocsd.time, "sleep", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "retaining OCSD sensor"):
                    ocsd.restore(memory, original, active)
            self.assertEqual(memory[56], ocsd.OWNED_COUNT)
            self.assertTrue(ocsd.owned_record(memory[ocsd.RECORD_OFFSET:
                                                      ocsd.RECORD_OFFSET + ocsd.RECORD_SIZE]))
            self.assertTrue(state.exists())


class DL380ProtocolTests(ProtocolTests, ProfileCase):
    PROFILE = "dl380-gen9-t4"


class ML350ProtocolTests(ProtocolTests, ProfileCase):
    PROFILE = "ml350-gen9-p100"


class ProfileSelectionTests(unittest.TestCase):
    def tearDown(self):
        load_default()

    def test_default_is_the_original_dl380_t4(self):
        load_default()
        self.assertEqual(ocsd.PROFILE_NAME, "dl380-gen9-t4")
        self.assertEqual(ocsd.EXPECTED_PRODUCT, "ProLiant DL380 Gen9")
        self.assertEqual((ocsd.GPU_PCI, ocsd.BUS, ocsd.DEVICE), ("00000000:05:00.0", 5, 0))
        self.assertEqual((ocsd.NATIVE_COUNT, ocsd.OWNED_COUNT, ocsd.RECORD_OFFSET), (2, 3, 384))
        self.assertEqual(ocsd.ILO_SENSOR, "21-PCI 1")
        self.assertEqual((ocsd.ILO_TIMEOUT_S, ocsd.ILO_MISS_LIMIT), (5, 2))

    def test_ml350_p100_profile(self):
        load_profile("ml350-gen9-p100")
        self.assertEqual(ocsd.EXPECTED_PRODUCT, "ProLiant ML350 Gen9")
        self.assertEqual((ocsd.GPU_PCI, ocsd.BUS, ocsd.DEVICE), ("00000000:0a:00.0", 10, 0))
        self.assertEqual(ocsd.NATIVE_BUSES, (4, 2, 3))
        self.assertEqual((ocsd.NATIVE_COUNT, ocsd.OWNED_COUNT, ocsd.RECORD_OFFSET), (3, 4, 544))
        self.assertEqual(ocsd.ILO_SENSOR, "27-PCI 3")
        self.assertEqual((ocsd.ILO_TIMEOUT_S, ocsd.ILO_MISS_LIMIT), (15, 6))

    def test_sensor_name_can_be_overridden(self):
        load_profile("dl380-gen9-t4", OCSD_ILO_SENSOR="22-PCI 2")
        self.assertEqual(ocsd.ILO_SENSOR, "22-PCI 2")

    def test_unknown_profile_is_rejected(self):
        with mock.patch.dict(os.environ, {"OCSD_PROFILE": "dl360-gen9-a2"}):
            with self.assertRaisesRegex(ValueError, "unknown OCSD_PROFILE"):
                importlib.reload(ocsd)

    def test_profile_is_checked_against_dmi(self):
        load_profile("dl380-gen9-t4")
        with mock.patch.object(ocsd.Path, "read_text", return_value="ProLiant ML350 Gen9\n"):
            with self.assertRaisesRegex(ValueError, "is not a ProLiant DL380 Gen9"):
                ocsd.run()


class UpstreamCompatibilityTests(ProfileCase):
    """The default profile must behave byte-for-byte like upstream 1c65a38."""

    PROFILE = "dl380-gen9-t4"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fixture = json.loads((FIXTURES / "upstream-1c65a38.json").read_text())

    def test_constants_match(self):
        constants = self.fixture["constants"]
        self.assertEqual(ocsd.EXPECTED_PRODUCT, constants["EXPECTED_PRODUCT"])
        self.assertEqual(ocsd.GPU_PCI, constants["GPU_PCI"])
        self.assertEqual((ocsd.BUS, ocsd.DEVICE), (constants["BUS"], constants["DEVICE"]))
        self.assertEqual(ocsd.RECORD_OFFSET, constants["RECORD_OFFSET"])
        self.assertEqual(list(ocsd.NATIVE_BUSES), self.fixture["native_buses"])

    def test_records_match(self):
        for key, expected in self.fixture["records"].items():
            temperature, counter = map(int, key.split(":"))
            with self.subTest(temperature=temperature, counter=counter):
                self.assertEqual(ocsd.make_record(temperature, counter).hex(), expected)

    def test_headers_match(self):
        snapshot = synthetic_snapshot(self.fixture["address"])
        self.assertEqual(snapshot[:64].hex(), self.fixture["snapshot_header"])
        self.assertEqual(ocsd.header_with_count(snapshot[:64], ocsd.OWNED_COUNT).hex(),
                         self.fixture["owned_header"])

    def test_claim_and_restore_match(self):
        address = self.fixture["address"]
        snapshot = synthetic_snapshot(address)
        memory = bytearray(snapshot)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(ocsd, "STATE", Path(directory) / "ownership.json"), \
                mock.patch.object(ocsd, "boot_id", return_value="boot-one"), \
                mock.patch.object(ocsd, "gpu_temperature", return_value=45):
            original, active, counter = ocsd.claim(memory, address)
            claim = self.fixture["claim"]
            self.assertEqual(counter, claim["counter"])
            self.assertEqual(bytes(memory[:64]).hex(), claim["header"])
            self.assertEqual(bytes(memory[ocsd.RECORD_OFFSET:
                                          ocsd.RECORD_OFFSET + ocsd.RECORD_SIZE]).hex(),
                             claim["record"])
            self.assertEqual(json.loads(ocsd.STATE.read_text()), claim["state"])
            with mock.patch.object(ocsd, "workloads_active", return_value=False), \
                    mock.patch.object(ocsd.time, "sleep", return_value=None):
                ocsd.restore(memory, original, active)
        self.assertTrue(self.fixture["restored_equals_snapshot"])
        self.assertEqual(bytes(memory), snapshot)


if __name__ == "__main__":
    unittest.main()
