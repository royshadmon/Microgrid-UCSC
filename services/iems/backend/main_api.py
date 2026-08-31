import sys
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/services")
from fastapi import FastAPI
from iems_router import api_router
from iems_ask import ask_router

app = FastAPI(title="IEMS Backend")
app.include_router(api_router)
app.include_router(ask_router)

@app.get("/")
def root():
    return {"ok": True, "service": "iems-backend"}
