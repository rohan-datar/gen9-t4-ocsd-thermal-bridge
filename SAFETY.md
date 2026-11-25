# Safety and recovery

This code writes a reverse-engineered record into physical memory as root.
It has been demonstrated on the platforms listed in the README, not certified
by HPE. Use it only if you can recover the machine locally and accept the
risk of management-controller misbehavior or inadequate cooling.

## Before the first write

- Keep stock iLO firmware and the complete, correct air path: fans, baffles,
  blanking panels.
- Check the exact product, GPU PCI location, firmware and fan hardware against
  the profile. A "Gen9" label alone says nothing about compatibility.
- Confirm there is one SMBIOS type-229 OCSD allocation, that its header and
  native records match the profile, that the GPU record slot is empty, and
  that nothing else is publishing.
- Save the original allocation somewhere **private**. Raw physical-memory
  contents never belong in an issue or repository.
- Plan a maintenance window with console access and a known way to stop the
  GPU work. A remote-only recovery plan is not enough.
- Configure the real GPU workload services. A missing or wrong unit means the
  thermal stop does nothing.

## What the daemon guarantees, and what it does not

The daemon writes only its own record and the header's count. It verifies
each write, checks ownership on restart, and never takes over a record it did
not create. If GPU telemetry fails it publishes 85 C and asks the workloads to
stop; at 82 C it asks them to stop; if iLO stops tracking the sensor it asks
them to stop and exits. Run it under a systemd watchdog so a hung publisher is
restarted before iLO treats the data as stale.

These reduce risk; they are **not** guarantees. On both tested chassis stale
data made iLO run the fans at 100%, but other firmware may differ. Watch the
real GPU and fan readings rather than the service state.

## Stopping and rollback

On stop, the daemon asks the workloads to stop and keeps publishing while the
GPU cools. Only after three readings at or below 55 C does it restore the
original header and empty record. If the GPU stays hot for 90 seconds,
telemetry is lost, ownership has changed or the restore cannot be verified,
it leaves its record in place rather than write over an unknown state. That
needs an operator and a planned recovery; do not improvise `/dev/mem` writes.

## Resetting iLO

The registration helper only checks registration unless run with
`--allow-ilo-reset`. With it, the helper first checks that the configured
workload services are loaded and inactive, takes three cool GPU readings, and
confirms the daemon's record exists and the sensor is missing; then it resets
**iLO only**. It cannot see GPU processes outside those services. A reset
interrupts management access, so do it only with an independent way back in.

## Starting at boot

The example unit in `examples/systemd` has no `[Install]` section: start it
by hand until you have tested manual start, load, telemetry loss, restart,
stop and restore on your own hardware. After a power cycle iLO may need a
reset before it shows the sensor, so boot automation still needs someone, or
a tested procedure, to complete registration. Keep GPU work stopped until the
sensor and fan response are confirmed.

The NixOS module does start the daemon at boot. That was chosen for the
`ml350-gen9-p100` platform after the testing in
[docs/platforms/ml350-gen9-p100.md](docs/platforms/ml350-gen9-p100.md), with
an iLO reset done by hand after each power cycle.
