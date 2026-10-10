# Ollama-API bridge in front of a NIM / vLLM Nemotron endpoint. Stdlib only.
FROM python:3.11-slim
WORKDIR /app
COPY ollama_bridge.py .
EXPOSE 11434
CMD ["python", "-u", "ollama_bridge.py"]
