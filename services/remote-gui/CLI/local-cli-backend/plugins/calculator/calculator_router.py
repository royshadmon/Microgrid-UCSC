# Example Plugin - Simple Calculator
# This demonstrates how easy it is to create a plugin

from fastapi import APIRouter
from pydantic import BaseModel

# Create the API router
api_router = APIRouter(prefix="/calculator", tags=["Calculator"])

# Request model
class CalculationRequest(BaseModel):
    operation: str
    a: float
    b: float

# API endpoints
@api_router.get("/")
async def calculator_info():
    """Get calculator information"""
    return {
        "name": "Simple Calculator Plugin",
        "version": "1.0.0",
        "operations": ["add", "subtract", "multiply", "divide"]
    }

@api_router.post("/calculate")
async def calculate(request: CalculationRequest):
    """Perform a calculation"""
    try:
        if request.operation == "add":
            result = request.a + request.b
        elif request.operation == "subtract":
            result = request.a - request.b
        elif request.operation == "multiply":
            result = request.a * request.b
        elif request.operation == "divide":
            if request.b == 0:
                return {"error": "Division by zero"}
            result = request.a / request.b
        else:
            return {"error": "Invalid operation"}
        
        return {
            "operation": request.operation,
            "a": request.a,
            "b": request.b,
            "result": result
        }
    except Exception as e:
        return {"error": str(e)}
