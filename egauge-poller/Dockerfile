FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN adduser --disabled-password --gecos "" --no-create-home --uid 10001 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY egauge_poller.py healthcheck.py ./
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD python healthcheck.py || exit 1

CMD ["python", "egauge_poller.py"]
