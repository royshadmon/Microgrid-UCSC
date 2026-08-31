FROM microgrid-ucsc-dev_fin-iems-inference
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic 2>/dev/null || pip install --no-cache-dir --break-system-packages fastapi "uvicorn[standard]" pydantic
COPY iems_router.py /app/iems_router.py
COPY iems_ask.py /app/iems_ask.py
COPY main_api.py /app/main_api.py
# Site knowledge the base image does not carry: the canonical appliance spec
# and the breaker/leg mapping. /iems/ask reads these to ground its answers.
COPY appliance_data_updated.txt /app/appliance_data_updated.txt
COPY breaker_ratings.yaml /app/services/iems/detect/breaker_ratings.yaml
ENV PYTHONPATH=/app:/app/services \
    IEMS_DASH_URL=http://host.docker.internal:47821 \
    IEMS_ASK_MODEL=qwen2.5:3b-instruct \
    IEMS_REPO=/app/services
WORKDIR /app
ENTRYPOINT ["python3"]
CMD ["-m","uvicorn","main_api:app","--host","0.0.0.0","--port","8000"]
