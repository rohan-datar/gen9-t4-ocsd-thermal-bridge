# Adding a platform

A platform is an entry in `PROFILES` in `gen9_t4_ocsd.py`. Everything in a
profile must be measured on the machine; do not copy values from another
chassis.

## 1. Look without writing

Run the read-only inspector ([OCSD_DISCOVERY.md](OCSD_DISCOVERY.md)) to
confirm a single type-229 `$OCS` allocation and to find the GPU's PCI address.
Then, as root, read (only read) the 64-byte header and the first records of
the allocation, and save a private copy of the whole 16 KiB. Note:

- that the header matches [PROTOCOL.md](../PROTOCOL.md) (version 2, size
  `0x4000`, marker 102, record size 160, interval 5, valid checksum);
- the header's record count and the PCI bus of each native record, in order;
- that the record after the native ones is entirely zero.

## 2. Add the profile

```python
"ml350-gen9-p100": {
    "product": "ProLiant ML350 Gen9",   # /sys/class/dmi/id/product_name
    "gpu": "P100",                       # used in log and status text
    "gpu_pci": "00000000:0a:00.0",       # nvidia-smi's pci.bus_id, lower case
    "native_buses": (4, 2, 3),           # bus of each native record, in order
    "ilo_sensor": "27-PCI 3",            # learnt in step 4
    "ilo_timeout_s": 5,                  # start with 5 s and 2 misses
    "ilo_miss_limit": 2,
},
```

The GPU record goes in the first slot after the native records, and the
header count rises by one while it is published.

## 3. Test offline

Add a test class next to the existing ones in `tests/test_gen9_t4_ocsd.py`:

```python
class MyPlatformProtocolTests(ProtocolTests, ProfileCase):
    PROFILE = "my-platform"
```

This runs the whole protocol suite against a synthetic table with your
layout. Add your values to `ProfileSelectionTests`, and leave the upstream
compatibility test alone: the default profile must keep matching it.

## 4. First live run

In a maintenance window, with console access and the GPU idle:

1. Start the daemon by hand with your profile.
2. Find the new sensor with `ipmitool sdr list`. If it does not appear, reset
   iLO once. Put its name in the profile.
3. Compare iLO's reading with `nvidia-smi` to get the display offset, and set
   `OCSD_ILO_OFFSET_C` if it is not 15.
4. Stop the daemon and check the table is restored.
5. Load the GPU with an independent temperature abort, and watch the
   sensor, the fans and the iLO event log. If the daemon exits with "iLO
   stopped tracking" while iLO still shows the sensor, raise the timeout and
   miss limit.

## 5. Document it

Add `docs/platforms/<profile>.md` with the hardware, firmware, layout,
sensor, offsets, results and what is still unknown. Add a dated entry to
[QUALIFICATION.md](../QUALIFICATION.md) and a row to the README table.
Remove serial numbers, addresses and memory contents first.
