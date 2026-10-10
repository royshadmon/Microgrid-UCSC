# Replay producer: Pat's real eGauge + Solar Assistant data, played into Kafka
# with live timestamps. Multi-arch base, runs natively on the GX10 (arm64).
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir confluent-kafka requests tzdata
COPY replay_producer.py .
EXPOSE 8099
CMD ["python", "-u", "replay_producer.py"]
