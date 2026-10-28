# IEMS engine API (FastAPI) and Ask, built on top of the inference image.
# Built from the repository root by docker-compose.yaml. The iems-base context
# is the iems-inference image, so the models and the iems package are shared.
FROM iems-base
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic
COPY services/iems/backend/iems_router.py /app/iems_router.py
COPY services/iems/backend/iems_ask.py /app/iems_ask.py
COPY services/iems/backend/main_api.py /app/main_api.py
# Site knowledge the base image does not carry, the appliance spec and the
# breaker and leg mapping. /iems/ask reads these to ground its answers.
COPY config/appliance_data_updated.txt /app/appliance_data_updated.txt
COPY analysis/inventory/breaker_ratings.yaml /app/services/iems/detect/breaker_ratings.yaml
ENV PYTHONPATH=/app:/app/services \
    IEMS_DASH_URL=http://iems-dashboard:47821 \
    IEMS_ASK_MODEL=qwen2.5:1.5b-instruct \
    IEMS_REPO=/app/services
WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["python3"]
CMD ["-m","uvicorn","main_api:app","--host","0.0.0.0","--port","8000"]
