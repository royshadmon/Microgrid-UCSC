# IEMS overlay on AnyLog remote-gui 2.1.2-beta.
#
# Adds one plugin -- frontend page plus backend router -- and changes nothing
# else.  Every upstream plugin, router and asset stays exactly as shipped; the
# two config files that gate plugin discovery are merged, never replaced.
#
# The runtime image has no node, so the Vite bundle is rebuilt in a builder
# stage from the image's own frontend source with the IEMS page added, and only
# the finished bundle is copied back.

# ── Stage 1: rebuild the frontend bundle with the IEMS page compiled in ──────
FROM node:20-slim AS fe

WORKDIR /fe

# The image ships its own frontend source, so the plugin is added to upstream's
# tree rather than to a fork of it.
COPY --from=anylogco/remote-gui:2.1.2-beta /app/CLI/local-cli-fe-full/ /fe/

COPY frontend/iems/ /fe/src/plugins/iems/

# AppleDouble files survive a tar made on macOS, and ._IemsPage.js matches the
# plugin glob './*/**Page.js' -- it would register as a second, broken plugin.
RUN find /fe/src/plugins/iems -name '._*' -delete \
 && rm -rf /fe/build

# dexie-encrypted@2 declares a peer on dexie@^3 while package.json pins
# dexie@^4, so a strict install fails on a conflict that predates this overlay.
RUN npm ci --legacy-peer-deps

ENV NODE_OPTIONS=--max-old-space-size=3072

RUN npx vite build \
 && test -d /fe/build/assets \
 && grep -rl 'iems-dash-root' /fe/build/assets >/dev/null \
 && echo "IEMS page is present in the bundle"

# ── Stage 2: upstream image + the rebuilt bundle + the backend router ────────
FROM anylogco/remote-gui:2.1.2-beta

USER root

COPY --from=fe /fe/build/ /tmp/iems-build/
COPY frontend/iems/ /app/CLI/local-cli-fe-full/src/plugins/iems/
COPY backend/iems/ /app/CLI/local-cli-backend/plugins/iems/
COPY enable_iems.py /tmp/enable_iems.py

# Replace the bundle outright rather than copying over it, so no stale
# index-<hash>.js from the base image is left behind beside the new one.
RUN rm -rf /app/CLI/local-cli-fe-full/build \
 && mv /tmp/iems-build /app/CLI/local-cli-fe-full/build \
 && python3 /tmp/enable_iems.py \
 && rm -f /tmp/enable_iems.py \
 && find /app/CLI -name '._*' -delete \
 && chown -R anylog:anylog \
      /app/CLI/local-cli-fe-full/build \
      /app/CLI/local-cli-fe-full/src/plugins/iems \
      /app/CLI/local-cli-backend/plugins/iems \
      /app/CLI/local-cli-backend/feature_config.json

USER anylog

# Where the IEMS engine and the IEMS dashboard live, as seen from this
# container.  Both are overridable from compose.
ENV IEMS_BACKEND_URL="http://host.docker.internal:8009" \
    IEMS_DASH_URL="http://host.docker.internal:47821"
