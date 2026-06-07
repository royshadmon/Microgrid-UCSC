# IEMS live dashboard — single-file zero-dependency Node server.
# Renders KPIs, NILM ON/OFF grid, derived solar, modeled battery SOC, DSS.
#
# Built from the repo root.

FROM node:20-alpine

WORKDIR /app

# server.js uses only Node built-ins (http). No npm install needed.
COPY services/iems/web/server.js /app/server.js

ENV NODE_ENV=production \
    PORT=47821

EXPOSE 47821
CMD ["node", "/app/server.js"]
