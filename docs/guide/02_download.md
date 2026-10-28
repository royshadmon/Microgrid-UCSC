# 2. Download the files

[Guide home](README.md) · back [1. What you need](01_requirements.md) · next [3. Configure](03_configure.md)

Pick a folder for the project, for example your home folder or Documents. The
commands below create a folder called `Microgrid-UCSC` inside it.

## With Git (recommended, makes updating easy)

macOS and Linux, in Terminal.

```bash
cd ~
git clone --branch new-guide https://github.com/royshadmon/Microgrid-UCSC.git
cd Microgrid-UCSC
```

Windows, in PowerShell.

```powershell
cd $HOME
git clone --branch new-guide https://github.com/royshadmon/Microgrid-UCSC.git
cd Microgrid-UCSC
```

The download is about 150 MB because it includes the trained models.

## Without Git

1. Open https://github.com/royshadmon/Microgrid-UCSC/tree/new-guide
2. Click **Code**, then **Download ZIP**.
3. Unzip it, and rename the folder to `Microgrid-UCSC` if it is called
   `Microgrid-UCSC-new-guide`.
4. Open a terminal (PowerShell on Windows) in that folder.

On macOS and Linux a ZIP download loses the permission that makes the scripts
runnable. Restore it once with

```bash
chmod +x scripts/*.sh
```

## Windows, keep the files on the C drive

Put the folder somewhere under `C:\Users\<you>`. Network drives and cloud synced
folders such as OneDrive can stop Docker from reading the files.

## What you downloaded

| folder | what is inside |
|---|---|
| `scripts/` | setup, start, stop, status and logs, for macOS and Linux (`.sh`) and Windows (`.ps1`) |
| `docker-compose.yaml` | every service and how they connect |
| `.env.example` | the settings you will copy to `.env` |
| `services/` | the appliance models, the engine, the dashboard and the AnyLog GUI page |
| `streaming/` | the meter, solar and demo feeds, Kafka, Postgres and AnyLog configuration |
| `tests/scenarios/` | recorded scenarios the demo plays, including power outages |
| `config/` | small files the containers read, such as your Home Assistant token |
| `docs/guide/` | this guide |
| `docs/reference/` | in depth notes on every part of the system |

Next, [3. Configure](03_configure.md).
