# 4. Start the system

[Guide home](README.md) · back [3. Configure](03_configure.md) · next [5. Check it and use it](05_use.md)

Make sure Docker Desktop is running (the whale icon in the menu bar or task
tray), then from the project folder run

macOS and Linux.

```bash
./scripts/start.sh
```

Windows.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

## What happens

| step | what the script does | first time | later |
|---|---|---|---|
| 1 | builds the local images (inference, engine, dashboard, feeds) | 5 to 15 min | seconds |
| 2 | starts every container for the profiles in `.env` | 1 min | 1 min |
| 3 | waits for the AnyLog operator and makes sure its operator process runs | 1 to 2 min | under 1 min |
| 4 | downloads the language model for Ask | 1 to 5 min, about 1 GB | skipped |
| 5 | waits for the dashboard | seconds | seconds |

On a brand new install you will see `first start, restarting operator1 once`.
That is expected. AnyLog writes its node policy during its very first boot, and
one restart lets the operator pick it up.

When it finishes it prints the addresses.

```
Ready
  Dashboard       http://localhost:47821
  Engine API      http://localhost:8009/docs
  AnyLog REST     http://localhost:32149
```

Open the dashboard address in a browser. The first appliance results appear
after about 10 minutes, because each model looks at a 10 minute window of power
readings. Battery, solar and grid figures appear within a minute.

## Starting it next time

The containers restart on their own when Docker starts, so after a reboot you
normally only need to open Docker Desktop. Running the start script again is
always safe. Add `--no-build` (macOS and Linux) or `-NoBuild` (Windows) to skip
the image build when you have not changed any code.

## Starting it by hand

The scripts are a convenience. Everything they do is plain Docker Compose.

```bash
docker compose up -d --build     # start or update
docker compose ps                # what is running
docker compose logs -f iems-inference
docker compose exec ollama ollama pull qwen2.5:1.5b-instruct
```

Next, [5. Check it and use it](05_use.md).
