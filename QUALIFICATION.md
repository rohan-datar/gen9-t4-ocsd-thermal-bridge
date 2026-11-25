# Qualification log

Dated, sanitized test records for each platform: no raw OCSD memory, host
addresses, serial numbers, workload data or credentials.

## DL380 Gen9 + Tesla T4 (`dl380-gen9-t4`)

This log distinguishes the public reference code from the separately installed
publisher. It contains only sanitized observations; no raw OCSD memory, host
address, serial number, workload data, or credentials are included.

### 2026-09-25: Manual idle lifecycle

- Tested public commit `7f38276` on a ProLiant DL380 Gen9 with iLO 4 v2.82,
  System ROM P89, Tesla T4 at PCI `00000000:05:00.0`, and Python 3.6.15.
- All 26 synthetic tests passed on the host. The example service passed
  `systemd-analyze verify` and remained a static, manual-start unit.
- Before the swap, the T4 was idle at 39 C and iLO `21-PCI 1` read 54 C.
  The live OCSD layout and two native records validated against the public
  parser. A private prewrite snapshot was kept off-repository.
- The separately installed publisher stopped and restored header count 2
  with an empty record 2. The public publisher then claimed record 2 and
  reached systemd ready after iLO sensor confirmation, without an iLO reset.
- During the public run, the valid record counter advanced 50, 56, 61;
  T4 remained at 39 C and iLO at 54 C. Fans 4-6 were approximately 12-13%.
- Stopping the public publisher restored header count 2 and an empty record
  2. The separately installed publisher resumed and confirmed the iLO sensor.

This was an **idle lifecycle test**, not a sustained GPU-load or fault-injection
test. The public service was stopped afterward. Natural 16-bit rollover, boot
registration, fail-high fan response, and long-run stability of this exact
public build remain unqualified. The separately installed publisher's natural
rollover was subsequently observed on 2026-09-26, as recorded below.

### 2026-09-26: Installed publisher natural rollover

- This was a read-only observation of the separately installed publisher on
  the same DL380 Gen9, not a live rollover run of the public reference code.
- The publisher stayed active with the same PID and zero systemd restarts.
  OCSD record 2 and its header/native records validated throughout the test.
- A pre-wrap sample had counter 65300, T4 41 C, iLO `21-PCI 1` at 56 C,
  and all six fans at approximately 12-16% duty.
- The monitor directly observed counter 65535 followed by 0. At 0, the
  record remained valid, the T4 was 41 C, iLO still read 56 C, and all six
  fans were approximately 9-12%. A later read reached counter 18 and remained
  valid.
- Observation used `os.O_RDONLY` and `mmap.ACCESS_READ` for `/dev/mem`.
  No GPU load, iLO reset, service action, or Asterisk action was performed.

**Result: pass for one natural 16-bit rollover of the installed publisher and
stock iLO 4 v2.82 on this chassis.** It supports the OCSD/iLO control path,
but does not establish sustained-load rollover behavior, public-copy long-run
stability, unattended boot recovery, or compatibility with other systems.

## ML350 Gen9 + Tesla P100 (`ml350-gen9-p100`)

Hardware and firmware are listed in
[docs/platforms/ml350-gen9-p100.md](docs/platforms/ml350-gen9-p100.md). Load
tests used `llama.cpp` benchmark jobs with their own 78 C (later 80 C) abort.

### 2026-11-23 and 24 (UTC): Layout, first publication, power cycle

- A private copy of the 16 KiB allocation was kept off-repository. The header
  validated (version 2, marker 102, record size 160, interval 5, count 3), with
  native records for buses 4, 2 and 3 and an empty fourth record.
- The daemon claimed record 3 and raised the count to 4. iLO showed no new
  sensor until it was reset from its web interface; then `27-PCI 3` read
  56 C with the GPU at 41 C.
- A 10-minute single-model load at 160 W peaked at 77 C and settled at
  67-72 C, with the two slot-3 fans in lockstep and no thermal slowdown.
  Without the daemon the same load had aborted at 78 C.
- A host power cycle removed the sensor. After boot the daemon claimed the
  slot afresh, and the sensor came back only after another iLO reset.

### 2026-11-24 (UTC): Full benchmark sweeps

- At 160 W and again at 140 W, with no publish offset, a full sweep aborted
  at 78 C in the same model's case. The slot-3 fans peaked at about 47%.
- With `OCSD_PUBLISH_OFFSET_C=10` at 140 W, both arms of the sweep (about
  62 minutes) completed with no abort: peaks 52-77 C, 70 C in the case that
  had aborted before, no thermal slowdown.
- During that run the daemon exited twice with "iLO stopped tracking": in-band
  IPMI queries were timing out under the 5 s / 2-miss check. With no
  publisher, iLO ran the fans at 100% until it was restarted by hand. On one
  of those exits the GPU had not cooled within 90 s, so the daemon kept its
  record instead of restoring the table; the next start recovered it. A later
  `SIGKILL` under load was recovered the same way. The profile now uses 15 s
  and 6 misses.
- A `SIGTERM` at idle restored the original header and empty record.

**Result:** the bridge held this GPU under sustained load at 140 W with a
10 C publish offset. Not yet shown on this host: registration after a power
cycle without a manual iLO reset, a counter wrap, and runs longer than a few
hours.
