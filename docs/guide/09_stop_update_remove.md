# 9. Stop, update and remove

[Guide home](README.md) · back [8. Troubleshooting](08_troubleshooting.md)

## Stop

```bash
./scripts/stop.sh            # keeps all data
```

Windows `.\scripts\stop.ps1`. Start again any time with the start script.

## Update to the newest version

With Git.

```bash
git pull
./scripts/start.sh
```

The start script rebuilds whatever changed. Your `.env` and your data are kept.
If `.env.example` gained new settings, copy those lines into your `.env`.

Without Git, download the ZIP again, copy your old `.env` and
`config/ha_token.txt` into the new folder, and run the start script there.

## Remove everything

```bash
docker compose --profile '*' down -v --rmi local    # containers, stored data and the images built here
docker image prune                                  # other images that nothing uses any more
```

The downloaded images for AnyLog, Postgres, Kafka and Ollama stay until you
remove them in Docker Desktop, Images, or with `docker image rm`.

Then delete the project folder.
