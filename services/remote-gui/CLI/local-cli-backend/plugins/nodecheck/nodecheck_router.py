from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .nodechecks import (
    get_status,
    get_processes,
    get_connections,
    run_all_checks
)

# Create the API router
api_router = APIRouter(prefix="/nodecheck", tags=["Node Check"])

# Request/Response models
class NodeRequest(BaseModel):
    connection: str

# API endpoints
@api_router.get("/")
async def nodecheck_info():
    """Get nodecheck information"""
    return {
        "name": "Node Check Plugin",
        "version": "1.0.0",
        "description": "Check the status and health of nodes in the network",
        "endpoints": [
            "/status - Get comprehensive node status",
            "/processes - Get running processes",
            "/connections - Get network connections",
            "/run-all-checks - Run all checks"
        ]
    }

@api_router.post("/status")
async def get_node_status(request: NodeRequest):
    """Get comprehensive node status"""
    try:
        result = get_status(request.connection)
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=500, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get node status: {str(e)}")

@api_router.post("/processes")
async def get_processes_endpoint(request: NodeRequest):
    """Get running processes information"""
    try:
        result = get_processes(request.connection)
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=500, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get processes: {str(e)}")

@api_router.post("/connections")
async def get_connections_endpoint(request: NodeRequest):
    """Get network connections information"""
    try:
        result = get_connections(request.connection)
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=500, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get connections: {str(e)}")

@api_router.post("/run-all-checks")
async def run_all_checks_endpoint(request: NodeRequest):
    """Run all available checks and return comprehensive results"""
    try:
        result = run_all_checks(request.connection)
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=500, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run all checks: {str(e)}")