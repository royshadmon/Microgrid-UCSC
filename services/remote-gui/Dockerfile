# =====================
# Frontend build stage
# =====================
FROM node:18-slim AS frontend-build
WORKDIR /app

# Install system deps for native npm packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential python3 git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy package files and install deps
COPY CLI/local-cli-fe-full/package*.json ./
RUN npm install --legacy-peer-deps --no-audit --progress=false

# Copy frontend source
COPY CLI/local-cli-fe-full ./

# Build-time API URL
ARG REACT_APP_API_URL=http://127.0.0.1:8000
ENV REACT_APP_API_URL=${REACT_APP_API_URL}

# Prevent OOM
ENV NODE_OPTIONS=--max_old_space_size=4096

# Install frontend deps needed for build (mongoose) and build
RUN npm install mongoose && npm run build

# =====================
# Backend build stage
# =====================
FROM python:3.11-slim AS backend-build
WORKDIR /app
ENV DEBIAN_FRONTEND=noninteractive

# Install system deps for virtualenv + build
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-venv build-essential git curl xsel npm \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python3 -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy Python dependencies and install in virtualenv
COPY requirements.txt .
RUN pip install --upgrade pip wheel \
    && pip install --no-cache-dir -r requirements.txt

# Clone AnyLog-API and install into virtualenv
RUN git clone --branch main --depth 1 https://github.com/AnyLog-co/AnyLog-API /tmp/AnyLog-API \
    && cd /tmp/AnyLog-API \
    && python setup.py sdist bdist_wheel \
    && pip install --no-cache-dir dist/*.whl \
    && rm -rf /tmp/AnyLog-API

# Copy backend source and templates
COPY CLI/ CLI/
COPY templates/ templates/
COPY start.sh start.sh
RUN chmod +x start.sh

# =====================
# Final runtime image
# =====================
FROM python:3.11-slim AS final
WORKDIR /app

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV CLI_IP=0.0.0.0
ENV CLI_PORT=8000

# Copy venv from backend-build
COPY --from=backend-build /opt/venv /opt/venv

# Copy backend source + templates + start.sh
COPY --from=backend-build /app/CLI CLI/
COPY --from=backend-build /app/templates templates/
COPY --from=backend-build /app/start.sh start.sh

# Copy frontend build
COPY --from=frontend-build /app/build /app/CLI/local-cli-fe-full/build

# Install runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    npm xsel \
    && npm install -g serve \
    && sed -i 's/\r$//' start.sh \
    && chmod +x start.sh \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8000 3001

ENTRYPOINT ["/app/start.sh"]
