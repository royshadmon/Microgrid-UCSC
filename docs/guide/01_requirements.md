# 1. What you need

[Guide home](README.md) · next [2. Download](02_download.md)

## A computer

| | minimum | comfortable |
|---|---|---|
| memory | 8 GB | 16 GB |
| free disk | 25 GB | 40 GB |
| processor | any 64 bit Intel, AMD or Apple Silicon | 4 cores or more |
| system | Windows 10 or 11, macOS 12 or newer, Ubuntu 22.04 or another recent Linux | |

The whole system runs inside Docker, so nothing else is installed on the
computer itself. It works the same on Intel and Apple Silicon machines.

## Software

1. **Git**, to download the files. Optional, because you can also download a ZIP.
   Windows: https://git-scm.com/download/win. macOS: run `git --version` in
   Terminal and accept the offer to install the developer tools. Linux:
   `sudo apt install git`.
2. **Docker** with **Docker Compose 2.24 or newer**.
   Windows and macOS: install Docker Desktop from
   https://www.docker.com/products/docker-desktop/ and start it once. On
   Windows let it use the WSL 2 backend when it asks. Linux: install Docker
   Engine and the compose plugin by following
   https://docs.docker.com/engine/install/, then add yourself to the docker group
   with `sudo usermod -aG docker $USER` and log out and back in.
3. Give Docker enough memory. Docker Desktop, Settings, Resources, Memory, set it
   to at least 6 GB, 8 GB or more is better.

Check both from a terminal (PowerShell on Windows).

```
git --version
docker --version
docker compose version
```

The last line must say v2.24 or higher.

## An AnyLog license

The data layer is AnyLog, which needs a license key to start. Ask the AnyLog
team at https://anylog.network for an evaluation license. They also tell you how
to get access to the `anylogco/anylog-network` image on Docker Hub, which
usually means a Docker Hub login that you enter with `docker login`.

Keep both at hand for [3. Configure](03_configure.md).

## Optional hardware

None of this is needed to try the system. Without it the stack runs in demo
mode on recorded data.

| device | what it adds |
|---|---|
| eGauge energy meter on the house sub-panels | live power for the appliance models |
| Solar Assistant on the inverter | live solar, battery and grid figures |
| Home Assistant with a thermostat | thermostat readings and controls on the dashboard |

[7. Real hardware](07_live_hardware.md) explains how to connect them.
