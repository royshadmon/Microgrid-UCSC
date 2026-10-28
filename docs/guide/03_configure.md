# 3. Configure

[Guide home](README.md) · back [2. Download](02_download.md) · next [4. Start](04_start.md)

All settings live in one file called `.env` in the project folder. The setup
script creates it for you and checks your computer at the same time.

## Step 1, run the setup script

macOS and Linux.

```bash
./scripts/setup.sh
```

Windows.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

It does four things and prints `[ok]`, `[warn]` or `[fail]` for each.

1. Checks that Docker is running, is new enough and has enough memory.
2. Copies `.env.example` to `.env` if there is no `.env` yet, and asks for your
   AnyLog license so you can paste it straight in.
3. Checks that the ports the system needs are free.
4. Downloads the ready made images. This is the slow part the first time, a few
   GB.

You can run it again whenever you like. It never overwrites an existing `.env`.

## Step 2, the AnyLog license

If you skipped the question in step 1, open `.env` in any text editor and fill
in the line

```
ANYLOG_LICENSE='paste-the-whole-key-here'
```

Keep the single quotes. Some keys end with a part in curly braces such as
`{"company": "...", "expiration": "..."}`, and that part belongs inside the
quotes too.

If setup printed **Docker Hub refused the AnyLog image**, log in with the
account the AnyLog team gave you and run setup again.

```
docker login
```

## Step 3, choose what runs

The line `COMPOSE_PROFILES` in `.env` decides which optional parts start.

| value | what you get |
|---|---|
| `demo` | the default. Plays a recorded day through the whole system, no hardware needed |
| `live` | reads a real eGauge meter and Solar Assistant, see [7. Real hardware](07_live_hardware.md) |
| `gui` | adds the AnyLog Remote GUI with the IEMS page on port 3001 |
| `tools` | adds Kafka UI on port 8080 |

Combine them with commas, for example `COMPOSE_PROFILES=demo,gui`.

## Step 4, the rest of `.env`

Everything else has a working default. The file explains each line. The ones
people change most are these.

| setting | when to change it |
|---|---|
| `DEMO_SCENARIO` | to play a different recorded case, such as `grid_outage_islanded` |
| `HOUSE_LAT`, `HOUSE_LON`, `HOUSE_TZ` | for a house somewhere else. These drive the sun and weather features |
| `OLLAMA_MODEL` | on a 16 GB machine `qwen2.5:3b-instruct` writes better answers in Ask |
| `DASHBOARD_PORT` and the other ports in section 7 | when setup reports one as busy |

Keep `.env` private. It is listed in `.gitignore` so Git never uploads it.

Next, [4. Start](04_start.md).
