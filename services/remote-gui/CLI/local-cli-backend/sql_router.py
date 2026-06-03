from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional
import helpers
from parsers import parse_response

# Create router for SQL endpoints
sql_router = APIRouter(prefix="/sql", tags=["SQL Query Generator"])

# Pydantic models for SQL requests
class SqlConnection(BaseModel):
    conn: str

class SqlDatabaseRequest(BaseModel):
    conn: SqlConnection

class SqlTableRequest(BaseModel):
    conn: SqlConnection
    database: str

class SqlColumnRequest(BaseModel):
    conn: SqlConnection
    database: str
    table: str

@sql_router.post("/get-databases/")
async def get_databases(request: SqlDatabaseRequest):
    """
    Get all databases available on the AnyLog node.
    """
    try:
        print("Getting databases for node:", request.conn.conn)
        databases = helpers.get_databases(request.conn.conn)
        return {"data": databases}
    except Exception as e:
        print(f"Error getting databases: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get databases: {str(e)}")

@sql_router.post("/get-tables/")
async def get_tables(request: SqlTableRequest):
    """
    Get all tables in a specific database.
    """
    try:
        print("Getting tables for database:", request.database, "on node:", request.conn.conn)
        tables = helpers.get_tables(request.conn.conn, request.database)
        return {"data": tables}
    except Exception as e:
        print(f"Error getting tables: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get tables: {str(e)}")

@sql_router.post("/get-columns/")
async def get_columns(request: SqlColumnRequest):
    """
    Get all columns in a specific table.
    """
    try:
        print("Getting columns for table:", request.table, "in database:", request.database, "on node:", request.conn.conn)
        columns = helpers.get_columns(request.conn.conn, request.database, request.table)
        return {"data": columns}
    except Exception as e:
        print(f"Error getting columns: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get columns: {str(e)}") 