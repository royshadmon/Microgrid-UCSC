FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir paho-mqtt requests
COPY solar_producer.py .
CMD ["python", "-u", "solar_producer.py"]
