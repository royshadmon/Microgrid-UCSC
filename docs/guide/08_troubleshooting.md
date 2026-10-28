# 8. Troubleshooting

[Guide home](README.md) · back [7. Real hardware](07_live_hardware.md) · next [9. Stop, update, remove](09_stop_update_remove.md)

Start with the status script, then look at the logs of whatever it flags.

```bash
./scripts/status.sh
./scripts/logs.sh operator1        # or iems-inference, demo-replay, anylog-consumer ...
```

On Windows use `.\scripts\status.ps1` and `.\scripts\logs.ps1 operator1`.

| what you see | cause | what to do |
|---|---|---|
| `Docker is installed but not running` | Docker Desktop is closed | open Docker Desktop and wait until it says it is running |
| `Docker Compose ... is too old` | an old Docker Desktop or compose plugin | update Docker Desktop, or on Linux `sudo apt install docker-compose-plugin` |
| `Set ANYLOG_LICENSE in .env` | the license line is empty | see [3. Configure](03_configure.md), step 2 |
| `pull access denied for anylogco/anylog-network` | Docker Hub needs the AnyLog account | `docker login`, then run setup again |
| `port 5432 is already in use` | another Postgres, or an older copy of this stack | stop the other program. The AnyLog, Kafka and Postgres ports cannot be moved |
| `port 47821 is already in use` | something else on that port | change `DASHBOARD_PORT` in `.env` (and likewise for the other ports in section 7) |
| `operator process is not running yet` | AnyLog has not finished its first start | wait a minute and run the start script again |
| every row count stays at 0 | the operator is not storing data | `./scripts/logs.sh operator1` and look for `license` or `Failed`. An expired license stops AnyLog |
| `energy_readings` 0 but `egauge_kafka` is not | the Kafka to AnyLog bridge is stuck | `docker compose restart kafka`, wait 20 s, then `docker compose restart anylog-consumer` |
| `solar_data` 0 in demo mode | `demo-replay` cannot reach the AnyLog broker | `./scripts/logs.sh demo-replay`, then `docker compose restart demo-replay` |
| `nilm_disaggregated` 0 after 10 minutes | the inference loop has no window yet | `./scripts/logs.sh iems-inference`. `tick complete` lines mean it is working |
| `Ask model not ready` | the model download did not finish | run the start script again, or `docker compose exec ollama ollama pull qwen2.5:1.5b-instruct` |
| Ask answers slowly the first time | the model is loading into memory | normal, later answers take a few seconds |
| the computer becomes slow | Docker is short of memory | give Docker more memory, or use the 1.5b model |
| Windows says `cannot be loaded because running scripts is disabled` | PowerShell execution policy | start the script with `powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1` |
| `bash: ./scripts/start.sh: Permission denied` | the ZIP download dropped the executable bit | `chmod +x scripts/*.sh` |
| `$'\r': command not found` in a container log | files were saved with Windows line endings | `git config --global core.autocrlf false`, then download again. The repository's `.gitattributes` normally prevents this |

## Starting completely fresh

This deletes all stored data and the downloaded model, then starts again.

```bash
./scripts/stop.sh --wipe
./scripts/start.sh
```

## More detail

[`docs/reference/07_streaming_storage.md`](../reference/07_streaming_storage.md)
has the full ingestion triage, and
[`docs/reference/05_inference_runtime.md`](../reference/05_inference_runtime.md)
explains how the models read the data.

Next, [9. Stop, update, remove](09_stop_update_remove.md).
