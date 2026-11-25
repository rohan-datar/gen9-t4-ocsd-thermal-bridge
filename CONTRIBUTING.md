# Contributing

Please open an issue with the exact chassis, iLO and System ROM versions,
fan hardware, GPU model and PCI location, OCSD header/record layout summary,
and a bounded test result. Do **not** post raw `/dev/mem` snapshots, serial
numbers, credentials, internal addresses, or private workload data.
Synthetic fixtures and sanitized telemetry are preferred. A pull request
should include offline tests and a clear account of which hardware was
actually exercised. To add a platform, follow
[docs/adding-a-platform.md](docs/adding-a-platform.md): a new profile, a
protocol test class for it, a platform page and a dated qualification entry.
The default profile must keep passing the upstream compatibility tests.

This project was created by **Josh Murphy (Ocean Media Now)**. If you feature
it in a blog, video, or community forum, please credit Josh and link to the
[original repository](https://github.com/oceanmedianow/gen9-t4-ocsd-thermal-bridge).
That extra public credit is appreciated, not required by the MIT license.

Giving back through code, chassis edge cases, documentation, or a pull
request is always welcome. On a lighter note, Josh also welcomes an Overwatch
match; his optional Battletag is `Bamkapowkick`. Neither contribution nor a
game is payment or a condition of using the software.
