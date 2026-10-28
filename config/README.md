# config

Files the containers read at run time.

| file | used by | notes |
|---|---|---|
| `appliance_data_updated.txt` | `iems-backend` (Ask) | the appliance catalogue for the house, baked into the image |
| `ha_token.txt` | `iems-dashboard` | your Home Assistant long lived access token, one line. Not committed. Create it only if you use Home Assistant |
