# Gen9 OCSD Thermal Bridge

Experimental reference implementation by **Josh Murphy (Ocean Media Now)**,
[oceanmedianow.com](https://www.oceanmedianow.com).
[Original repository](https://github.com/oceanmedianow/gen9-t4-ocsd-thermal-bridge) | [MIT license](LICENSE)

HPE iLO 4 cannot read the temperature of a third-party GPU, so a ProLiant
Gen9 does not raise its fans for one. This daemon reads the GPU temperature
with `nvidia-smi` and publishes it in the firmware's OCSD option-card table,
in host memory. Stock iLO 4 picks it up as a PCI temperature sensor and cools
the card with its own fan algorithm.

```text
nvidia-smi -> OCSD record (host memory) -> iLO 4 PCI sensor -> HPE fan control
```

It does **not** set fan speeds, patch iLO firmware or need a custom iLO.

> **Warning.** This is not an HPE-supported integration and is not affiliated
> with HPE or NVIDIA. It writes a reverse-engineered record to `/dev/mem` as
> root; a wrong write can disturb the running management controller. It runs
> only on the exact platforms below, and refuses to start on anything else.
> Read [SAFETY.md](SAFETY.md) before trying it.

## Supported platforms

Each platform is a profile in `gen9_t4_ocsd.py`, selected with
`OCSD_PROFILE`. A profile pins the chassis, GPU location, OCSD layout and iLO
sensor; the daemon checks the chassis against DMI and the layout against the
live table, and stops on any mismatch.

| Profile | Chassis | GPU (PCI) | iLO sensor | Tested by | Details |
|---|---|---|---|---|---|
| `dl380-gen9-t4` (default) | ProLiant DL380 Gen9, iLO 4 v2.82 | Tesla T4 (`05:00.0`) | `21-PCI 1` | Josh Murphy | [docs/platforms/dl380-gen9-t4.md](docs/platforms/dl380-gen9-t4.md) |
| `ml350-gen9-p100` | ProLiant ML350 Gen9, iLO 4 v2.82 | Tesla P100 16 GB (`0a:00.0`) | `27-PCI 3` | Rohan Datar | [docs/platforms/ml350-gen9-p100.md](docs/platforms/ml350-gen9-p100.md) |

Results on these machines do not certify other firmware revisions, slots,
GPUs or cooling hardware. To add a platform, see
[docs/adding-a-platform.md](docs/adding-a-platform.md).

## How it works

The firmware describes a 16 KiB OCSD allocation in an SMBIOS type-229 entry.
It holds a 64-byte header and 160-byte option-card records, the first few
filled by the server's own cards. The daemon:

1. finds the allocation, checks the header and every native record against
   the profile, and requires the next record to be empty;
2. writes a GPU record there and raises the header's card count by one;
3. updates the record's temperature and counter once a second;
4. checks every 5 seconds that iLO's sensor tracks the GPU (with the
   platform's display offset), and fails if iLO stops tracking it;
5. on shutdown, keeps publishing until the GPU has cooled, then restores the
   original header and empty record.

If `nvidia-smi` fails it publishes 85 C, so iLO errs towards more cooling.
At 82 C, or on telemetry loss, it asks the configured GPU workload services
to stop. [PROTOCOL.md](PROTOCOL.md) documents the layout and checksums.

## Requirements

- One of the platforms above, with stock iLO 4 firmware and the full air path.
- Linux with systemd, Python 3.6 or newer (standard library only).
- `nvidia-smi`, `ipmitool` (in-band IPMI), and root access to `/dev/mem`.
- One or more systemd services that run the GPU work, for the daemon to stop
  on a thermal trip. It refuses to start if they are not loaded.
- `ilorest`, only if you use the guarded iLO-reset helper.

## Install

Use a maintenance window with console access, and keep a private copy of the
OCSD allocation before the first write. See [SAFETY.md](SAFETY.md).

### systemd

1. Copy `gen9_t4_ocsd.py` and `gen9_t4_ocsd_register.py` to
   `/opt/gen9-t4-ocsd/`.
2. Create `/etc/gen9-t4-ocsd.conf` (root-owned, mode 0600) from
   [examples/gen9-t4-ocsd.conf.example](examples/gen9-t4-ocsd.conf.example):
   set `OCSD_PROFILE` and list **every** GPU workload service in
   `OCSD_WORKLOAD_UNITS`.
3. Install [examples/systemd/gen9-t4-ocsd.service](examples/systemd/gen9-t4-ocsd.service)
   and start it by hand: `systemctl start --no-block gen9-t4-ocsd`. The
   example unit is `Type=notify` and has no `[Install]` section: it becomes
   ready only once iLO shows the sensor, and is not enabled at boot.
4. If the sensor does not appear (`ipmitool sdr list`), iLO usually needs a
   reset to discover it; see [Registering the sensor](#registering-the-sensor).

### NixOS

The flake provides `packages.x86_64-linux.default` (building it runs the
test suite) and `nixosModules.default`:

```nix
# flake.nix
inputs.gen9-t4-ocsd = {
  url = "github:oceanmedianow/gen9-t4-ocsd-thermal-bridge";
  inputs.nixpkgs.follows = "nixpkgs";
};

# host configuration
imports = [ inputs.gen9-t4-ocsd.nixosModules.default ];
services.gen9-t4-ocsd = {
  enable = true;
  profile = "ml350-gen9-p100";
  workloadUnits = [ "ollama.service" ];
};
```

The module runs the daemon with a hardened unit, a 60 s watchdog and
`Restart=on-failure`, and **does** start it at boot. It uses `Type=exec`
rather than `Type=notify`, because after a power cycle iLO only shows the
sensor once it has been reset; with `notify`, boot and `nixos-rebuild switch`
would wait on that. The daemon publishes from the start either way, and
`systemctl status` reports when iLO has confirmed the sensor. An empty
`workloadUnits` installs a no-op placeholder, for GPU work that is not a
host service (for example Kubernetes pods). Options: `profile`,
`workloadUnits`, `publishOffset`, `iloDisplayOffset`, `iloSensor`,
`nvidiaSmi`, `package`.

## Configuration

All settings are environment variables.

| Variable | Default | Meaning |
|---|---|---|
| `OCSD_PROFILE` | `dl380-gen9-t4` | Platform profile. |
| `OCSD_WORKLOAD_UNITS` | (required) | Space-separated systemd services to stop on a thermal trip and before releasing the slot. |
| `OCSD_PUBLISH_OFFSET_C` | `0` | Publish the GPU temperature this much higher (0-15) so iLO's fan curve engages earlier. The workload stop and shutdown cool-down still use the real temperature. |
| `OCSD_ILO_OFFSET_C` | `15` | Expected difference between iLO's reading and the GPU temperature. Set it to the platform's display offset plus `OCSD_PUBLISH_OFFSET_C`. |
| `OCSD_ILO_SENSOR` | from profile | iLO sensor name, if yours differs. |
| `OCSD_NVIDIA_SMI`, `OCSD_IPMITOOL`, `OCSD_SYSTEMCTL` | `/usr/bin/...` | Tool paths. |
| `OCSD_ILOREST` | `/usr/sbin/ilorest` | `ilorest` path for the registration helper. |

## Registering the sensor

iLO may not show the new sensor until it is reset. `gen9_t4_ocsd_register.py`
checks whether iLO tracks the GPU and, only with `--allow-ilo-reset`, resets
iLO (not the host) once. It refuses while a configured workload service is
active or the GPU is warm. It cannot see GPU processes outside those services,
so confirm the GPU is idle yourself first:

```sh
sudo env OCSD_PROFILE=dl380-gen9-t4 OCSD_WORKLOAD_UNITS="your-llm.service" \
  /usr/bin/python3 /opt/gen9-t4-ocsd/gen9_t4_ocsd_register.py --allow-ilo-reset
```

A reset from the iLO web interface (Information > Diagnostics > Reset iLO)
works too.

## Verify

Under a bounded GPU load, watch `nvidia-smi`, `ipmitool sdr list` (the
profile's sensor and all fans) and the iLO event log together. The sensor
should read the GPU temperature plus the offset, the fans serving that slot
should rise and fall with it, and stopping the service should cool the GPU
and restore the table.

## Limits

- Not a substitute for the correct fan kit, baffles, blanking panels,
  firmware, power budget or independent thermal monitoring.
- The daemon stops only the configured systemd services. It cannot stop other
  GPU processes or guarantee the GPU cools after a stop request.
- A stopped publisher leaves stale data; on both tested chassis iLO then ran
  the fans at 100%.
- Sensor names, display offsets, PCI locations and the 85 C fail-high value
  are platform observations, not general rules.
- The update counter is 16-bit and wraps after about 18 hours. One natural
  wrap was observed on the DL380 (see [QUALIFICATION.md](QUALIFICATION.md)).

## Repository

- `gen9_t4_ocsd.py`: the publisher and its platform profiles.
- `gen9_t4_ocsd_register.py`: sensor registration check and guarded iLO reset.
- `ocsd_discovery.py`: read-only discovery for new platforms
  ([docs/OCSD_DISCOVERY.md](docs/OCSD_DISCOVERY.md)).
- `examples/`: systemd unit and configuration (not installed by anything).
- `nix/`, `flake.nix`: Nix package and NixOS module.
- `tests/`: offline tests on synthetic tables, run once per profile, plus
  fixtures from the original release that the default profile must match
  byte for byte. Run them with `python3 -m unittest discover -s tests -v`;
  no GPU or iLO is needed.

## Prior work and acknowledgments

This project builds on earlier community reverse-engineering of HPE iLO 4 and
OCSD. In particular:

- [/u/phoenixdev's original "Silence of the Fans" work](https://www.reddit.com/r/homelab/comments/dc7dbc/silence_of_the_fans_preliminary_success_with/)
  helped establish practical control and understanding of iLO 4 fan behavior.
- [Kendall Goto's `ilo4_unlock`](https://github.com/kendallgoto/ilo4_unlock)
  exposed and documented previously inaccessible iLO 4 utilities, including
  fan and OCSD-related functionality.
- [`conroy-cheers/ocsd`](https://github.com/conroy-cheers/ocsd) demonstrated
  host-side reporting of option-card temperature data into the OCSD buffer so
  iLO can use that data for monitoring and fan control.

Those projects established important parts of the iLO 4 / OCSD path that made
this implementation possible. This repository's contribution is narrower: it
publishes a GPU temperature through the host OCSD record so the stock HPE
controller can respond without patched iLO firmware or direct PWM/fan
overrides, with model-specific guards, fail-high behavior, workload-stop
handling and the qualification work documented here.

## Contributing

Platform reports, fixes and documentation are welcome; see
[CONTRIBUTING.md](CONTRIBUTING.md). Keep the copyright and MIT notice as the
license requires. Credit in blog posts, videos or forum threads is
appreciated but not a license condition.
