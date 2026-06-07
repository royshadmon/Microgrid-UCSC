# IEMS NILM inference loop — runs continuously, every ~30s pulls a window
# from AnyLog, runs all three per-panel ONNX models, reconciles with the
# rules engine, and writes one row per appliance back to nilm_disaggregated.
#
# Built from the repo root so the build context can COPY services/iems/.

FROM python:3.11-slim

# Minimal system deps for psycopg2 and ONNX Runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq-dev curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so they cache across code changes
COPY services/iems/inference/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir --upgrade pip wheel \
    && pip install --no-cache-dir -r /tmp/req.txt

# Copy the IEMS package (models, inference, training utils used by inference)
# Note: data/, test_results/, .venv-training/ are excluded via .dockerignore
COPY services/iems /app/services/iems

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/services \
    TZ=America/Los_Angeles

# Default tick = 30s (matches launchd agent on the dev laptop).
# Override at runtime with: command: ["--tick","60"]
ENTRYPOINT ["python", "-m", "iems.inference.inference_loop"]
CMD ["--tick", "30"]
