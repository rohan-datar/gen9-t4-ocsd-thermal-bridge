# OCSD layout

What is written here was observed on the tested platforms with stock iLO 4
v2.82. It is not an HPE specification. The code accepts only this layout and
rejects anything else rather than guessing.

## Allocation

SMBIOS type 229 contains one `$OCS` descriptor giving the physical address
and size of a page-aligned 16 KiB allocation. The daemon reads the address at
run time from `/sys/firmware/dmi/entries`; no address is built in.

## Header (64 bytes)

| Offset | Size | Value |
|---|---|---|
| 0 | 1 | version, `2` |
| 4 | 2 | allocation size, `0x4000` |
| 8 | 1 | card capacity marker, `102` |
| 12 | 1 | record size, `160` |
| 16 | 4 | physical address of the first record (allocation + 64) |
| 32 | 1 | polling interval marker, `5` |
| 56 | 1 | number of populated records |
| 60 | 4 | checksum: the two's-complement negation of the sum of the fields above |

## Records (160 bytes each)

The firmware fills the first records with the server's own option cards. Each
native record starts with a 64-byte device header: byte 0 is `1`, byte 4 the
PCI bus, byte 8 the device, and the sixteen 32-bit words sum to zero.

| Profile | Native records (PCI bus) | GPU record | Count while published |
|---|---|---|---|
| `dl380-gen9-t4` | 2: bus 2, bus 3 | index 2, bus 5 / device 0 | 2 -> 3 |
| `ml350-gen9-p100` | 3: bus 4 (560SFP+), bus 2 (BCM5719), bus 3 (P440ar) | index 3, bus 10 / device 0 | 3 -> 4 |

The daemon checks every native record's bus and checksum, requires the record
after them to be completely empty, and refuses to write if anything differs.
In the GPU record, the temperature is the byte at offset 84 and a 16-bit
update counter is at offset 88; the device and sensor checksums are
recomputed on every update.

## iLO's view

iLO shows the record as a PCI temperature sensor and reads it at its own
polling interval:

| Profile | Sensor | iLO reading vs. published value |
|---|---|---|
| `dl380-gen9-t4` | `21-PCI 1` | about +15 C |
| `ml350-gen9-p100` | `27-PCI 3` | +15 C |

On the ML350, iLO showed the sensor only after an iLO reset while the daemon
was publishing, and again after every host power cycle. The DL380 notes say
it may need one as well. On both, stale data (the counter no longer
advancing) drove the fans to 100%. The 16-bit counter wraps after 65,536 updates; one
natural wrap was observed on the DL380 without any change in iLO's behavior.

## Tests

The synthetic tables in `tests/` contain only the fields needed to exercise
these checks. They are not host memory dumps and cannot show that another
machine shares this layout. Before any live write, read and privately back up
the target machine's allocation and compare it field by field.
