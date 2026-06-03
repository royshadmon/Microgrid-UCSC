# Grafana Plugin - Simple URL redirect plugin
# This plugin provides access to Grafana dashboards

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import os

# Create the API router
api_router = APIRouter(prefix="/grafana", tags=["Grafana"])

# Default Grafana URL (can be overridden via environment variable)
DEFAULT_GRAFANA_URL = os.getenv("GRAFANA_URL", "http://23.239.12.151:3100/dashboards/f/ddu0qc65783r4a/smart-city")

# Request/Response models
class GrafanaConfig(BaseModel):
    url: str

# API endpoints
@api_router.get("/")
async def grafana_info():
    """Get Grafana URL and information"""
    return {
        "name": "Grafana Plugin",
        "version": "1.0.0",
        "url": DEFAULT_GRAFANA_URL,
        "description": "Access to Grafana dashboards"
    }

@api_router.get("/url")
async def get_grafana_url():
    """Get the Grafana URL"""
    return {
        "url": DEFAULT_GRAFANA_URL
    }
