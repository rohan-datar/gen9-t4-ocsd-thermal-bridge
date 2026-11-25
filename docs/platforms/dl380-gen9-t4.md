# DL380 Gen9 + Tesla T4 (`dl380-gen9-t4`)

The original platform, tested by Josh Murphy. This is the default profile and
behaves exactly as the first release did.

| | |
|---|---|
| Chassis | HPE ProLiant DL380 Gen9 |
| Firmware | iLO 4 v2.82, System ROM P89, BIOS `OptimalCooling` |
| Fans | chassis high-performance fans |
| GPU | NVIDIA Tesla T4 at `00000000:05:00.0` (OCSD bus 5, device 0) |
| OCSD layout | 2 native records (buses 2, 3); the GPU uses record 2, count 2 -> 3 |
| iLO sensor | `21-PCI 1`, reading about GPU + 15 C |
| iLO check | 5 s IPMI timeout, 2 consecutive misses |
| Python | 3.6 |

## Observed

During a five-request sustained inference test the T4 peaked at 65 C, about
71 W and 98% utilization; fans 4-6 rose to roughly 56/70/70%, with no NVIDIA
thermal slowdown. Reboot, publisher crash recovery, the response to stale
data, a controlled idle shutdown and a warm stop were also exercised. Stale
data drove the fans to 100%. One natural 16-bit counter wrap passed without a
change in iLO's behavior.

The public code itself passed an idle manual start, sensor confirmation and
a controlled stop and restore on this chassis. GPU load, fault injection and
a counter wrap were exercised with the separately installed publisher, not
the public copy. Dated logs are in [QUALIFICATION.md](../../QUALIFICATION.md).
