# Step by step guide

Run the Microgrid IEMS on your own computer, with recorded data first and with
your own meter later.

| step | page | time |
|---|---|---|
| 1 | [What you need](01_requirements.md) | 15 min to install Docker |
| 2 | [Download the files](02_download.md) | 2 min |
| 3 | [Configure](03_configure.md) | 5 min plus image download |
| 4 | [Start the system](04_start.md) | 10 to 25 min the first time |
| 5 | [Check it and use it](05_use.md) | |
| 6 | [Demo scenarios, outages and other cases](06_demo_scenarios.md) | |
| 7 | [Connect real hardware](07_live_hardware.md) | |
| 8 | [Troubleshooting](08_troubleshooting.md) | |
| 9 | [Stop, update and remove](09_stop_update_remove.md) | |

The short version, once Docker is installed and you have an AnyLog license.

macOS and Linux.

```bash
git clone --branch new-guide https://github.com/royshadmon/Microgrid-UCSC.git
cd Microgrid-UCSC
./scripts/setup.sh
./scripts/start.sh
```

Windows PowerShell.

```powershell
git clone --branch new-guide https://github.com/royshadmon/Microgrid-UCSC.git
cd Microgrid-UCSC
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

Then open http://localhost:47821.
