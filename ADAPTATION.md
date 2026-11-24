# ML350 Gen9 / Tesla P100 adaptation

Fork of [oceanmedianow/gen9-t4-ocsd-thermal-bridge](https://github.com/oceanmedianow/gen9-t4-ocsd-thermal-bridge)
(MIT, (c) Josh Murphy), adapted from a DL380 Gen9 + Tesla T4 to a
**ProLiant ML350 Gen9 + Tesla P100 PCIe 16GB** on iLO 4 v2.82.

## Layout differences (verified by owner-run dmidecode + /dev/mem read, 2026-11-23)

- The ML350 exposes the same single 16 KiB `$OCS` SMBIOS type-229 allocation
  (physical 0x791F6000 on the qualified host) with the identical header layout
  (version 2, marker 102, record size 160, interval 5).
- The ML350 has **three native records** (bus 4 = 560SFP+, bus 2 = BCM5719,
  bus 3 = P440ar) instead of the DL380's two, so the publisher claims
  **record slot 3** and holds the header count at 4 while owned.
- The P100 sits at PCI `00000000:0a:00.0` (bus 10, device 0).

## Code changes vs upstream

- `OCSD_PUBLISH_OFFSET_C` (default 0): publish the GPU temperature shifted by N
  degrees so iLO's fan curve engages earlier — the fans never saturated
  (~47% duty at peak) and the Q3_K_M benchmark case climbed past 78 C at both
  160 W and 140 W caps. The caution/continuous record thresholds shift equally;
  the workload-stop (82 C) and restore-cooldown (55 C) guards stay on raw GPU
  temperatures. Set the ready-check `OCSD_ILO_OFFSET_C` to 15 + N when used.
- `EXPECTED_PRODUCT`, `GPU_PCI`, `BUS/DEVICE` repinned for the ML350/P100.
- `NATIVE_BUSES`/`NATIVE_COUNT`/`OWNED_COUNT`/`RECORD_INDEX` introduced;
  all count checks derived from them (upstream hardcoded 2/3).
- Executable paths and iLO sensor identity overridable via environment
  (`OCSD_NVIDIA_SMI`, `OCSD_IPMITOOL`, `OCSD_SYSTEMCTL`, `OCSD_ILO_SENSOR`,
  `OCSD_ILO_OFFSET_C`) — NixOS has no FHS `/usr/bin`; the systemd unit must
  supply store paths. Defaults preserve upstream behaviour.
- Test fixtures extended to the 3-native-record layout; the recovery-path
  test caught (and this fork fixes) a native-count check that must follow
  `NATIVE_COUNT`.

## Qualification status

- Offline test suite: 31/31 pass (Python 3.14).
- **NOT live-qualified on hardware yet.** Before first live use: read
  SAFETY.md, take a private backup of the OCSD region, arrange a
  console-attended maintenance window, and verify the unknowns below.

## Open items for live qualification

1. iLO sensor name for our published record (upstream saw `21-PCI 1`;
   with three native records ours may number differently) — set
   `OCSD_ILO_SENSOR` accordingly.
2. iLO display offset (upstream observed +15 C on the T4; confirm on the
   P100) — set `OCSD_ILO_OFFSET_C` accordingly.
3. Whether iLO accepts a two-digit PCI bus value (only single-digit
   native buses observed).
4. Whether iLO needs the `ilorest` registration reset to discover the
   published sensor.
