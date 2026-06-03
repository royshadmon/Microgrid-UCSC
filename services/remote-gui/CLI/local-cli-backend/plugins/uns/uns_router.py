# UNS Plugin - Unified Namespace
# Provides filesystem-like interface for blockchain metadata

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from plugins.utils import make_request
from parsers import parse_response

# Create the API router
api_router = APIRouter(prefix="/uns", tags=["UNS"])

# Request models
class BlockchainQueryRequest(BaseModel):
    conn: str
    item_id: Optional[str] = None
    include_children: bool = False

class GetRootRequest(BaseModel):
    conn: str
    query: Optional[str] = "blockchain get *"  # Default to blockchain get * if not provided

class QueryTableRequest(BaseModel):
    conn: str
    dbms: str
    table: str
    time_value: float = 5.0  # Time range value
    time_unit: str = "minute"  # Time unit: minute, hour, day, etc.

class QueryCustomRequest(BaseModel):
    conn: str
    dbms: str
    sql_query: str  # Custom SQL query

# API endpoints
@api_router.get("/")
async def uns_info():
    """Get UNS plugin information"""
    return {
        "name": "Unified Namespace Plugin",
        "version": "1.0.0",
        "description": "Filesystem-like interface for blockchain metadata"
    }

@api_router.post("/get-root")
async def get_root(request: GetRootRequest):
    """Get root items using configurable query"""
    try:
        command = request.query or "blockchain get *"
        print(f"UNS: Executing command: {command}")
        print(f"UNS: Connection: {request.conn}")
        print(f"UNS: Query: {request.query}")
        response = make_request(request.conn, "GET", command)
        parsed = parse_response(response)
        
        # Extract data from response
        if isinstance(parsed, dict) and "data" in parsed:
            data = parsed["data"]
        elif isinstance(parsed, list):
            data = parsed
        else:
            data = parsed
        
        # Ensure data is a list
        if not isinstance(data, list):
            data = [data] if data else []
        
        # Log first item structure for debugging
        if data and len(data) > 0:
            print(f"UNS: First root item structure: {data[0]}")
        
        return {
            "success": True,
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get root items: {str(e)}")

@api_router.post("/get-item")
async def get_item(request: BlockchainQueryRequest):
    """Get a specific item by ID"""
    try:
        if not request.item_id:
            raise HTTPException(status_code=400, detail="item_id is required")
        
        command = f'blockchain get * where [id] = "{request.item_id}"'
        print(f"UNS: Executing command: {command}")
        print(f"UNS: Connection: {request.conn}")
        print(f"UNS: Item ID: {request.item_id}")
        response = make_request(request.conn, "GET", command)
        parsed = parse_response(response)
        
        # Extract data from response
        if isinstance(parsed, dict) and "data" in parsed:
            data = parsed["data"]
        elif isinstance(parsed, list):
            data = parsed
        else:
            data = parsed
        
        return {
            "success": True,
            "data": data if isinstance(data, list) else [data] if data else []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get item: {str(e)}")

@api_router.post("/get-children")
async def get_children(request: BlockchainQueryRequest):
    """Get children of a specific item"""
    try:
        if not request.item_id:
            raise HTTPException(status_code=400, detail="item_id is required")
        
        command = f'blockchain get * where [id] = "{request.item_id}" bring.children'
        print(f"UNS: Executing command: {command}")
        print(f"UNS: Connection: {request.conn}")
        print(f"UNS: Item ID: {request.item_id}")
        response = make_request(request.conn, "GET", command)
        parsed = parse_response(response)

        
        # Extract data from response
        if isinstance(parsed, dict) and "data" in parsed:
            data = parsed["data"]
        elif isinstance(parsed, list):
            data = parsed
        else:
            data = parsed
        
        return {
            "success": True,
            "data": data if isinstance(data, list) else [data] if data else []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get children: {str(e)}")

@api_router.post("/query-table")
async def query_table(request: QueryTableRequest):
    """Query table data for the last N hours"""
    try:
        if not request.dbms or not request.table:
            raise HTTPException(status_code=400, detail="dbms and table are required")
        
        # Build SQL query: SELECT * FROM table WHERE period(unit, value, NOW(), insert_timestamp)
        time_value = request.time_value or 5.0
        time_unit = request.time_unit or "minute"
        
        # Convert to int if it's a whole number, otherwise keep as float
        time_value_str = str(int(time_value)) if time_value == int(time_value) else str(time_value)
        
        # Use the time unit directly in the period function
        sql_query = f'SELECT * FROM {request.table} WHERE period({time_unit}, {time_value_str}, NOW(), insert_timestamp)'
        # Use the exact format that works in the client dashboard
        command = f'run client () sql {request.dbms} format = table "{sql_query}"'
        
        print(f"UNS: Executing SQL command: {command}")
        print(f"UNS: Connection: {request.conn}")
        print(f"UNS: DBMS: {request.dbms}, Table: {request.table}, Time: {time_value} {time_unit}")
        print(f"UNS: Full command string: {repr(command)}")
        
        # Use GET method like the client dashboard does
        response = make_request(request.conn, "GET", command)   
        print("response", response)
        # print(f"UNS: Raw response type: {type(response)}")
        # print(f"UNS: Raw response length: {len(str(response)) if response else 0}")
        # print(f"UNS: Raw response preview (first 1000 chars): {str(response)[:1000] if response else 'None'}")
        
        parsed = parse_response(response)
        print("parsed", parsed)
        # print(f"UNS: Parsed response type: {type(parsed)}")
        # print(f"UNS: Parsed response keys: {parsed.keys() if isinstance(parsed, dict) else 'N/A'}")
        
        # Extract data from response
        if isinstance(parsed, dict) and "data" in parsed:
            data = parsed["data"]
            # print(f"UNS: Extracted data from parsed['data'], type: {type(data)}, length: {len(data) if isinstance(data, list) else 'N/A'}")
        elif isinstance(parsed, list):
            data = parsed
            # print(f"UNS: Parsed is list, length: {len(data)}")
        elif isinstance(parsed, dict) and "type" in parsed:
            # Check if it's an error response
            if parsed.get("type") == "error":
                return {
                    "success": False,
                    "error": parsed.get("data", "Unknown error occurred"),
                    "data": None
                }
            data = parsed.get("data", parsed)
            # print(f"UNS: Extracted from parsed dict, type: {type(data)}, length: {len(data) if isinstance(data, list) else 'N/A'}")
        else:
            data = parsed
            # print(f"UNS: Using parsed directly, type: {type(data)}")
        
        # Handle case where data might be a string (JSON string)
        if isinstance(data, str):
            try:
                import json
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                pass
        
        # Ensure data is a list
        if not isinstance(data, list):
            data = [data] if data else []
        
        # print(f"UNS: Data before filtering - type: {type(data)}, length: {len(data) if isinstance(data, list) else 'N/A'}")
        if isinstance(data, list) and len(data) > 0:
            print(len(data))
            print(f"UNS: First row sample: {data[0]}")
            print(f"UNS: Last row sample: {data[-1]}")
        
        # Filter out internal columns (row_id, tsd_name, tsd_id) from each row
        filtered_data = []
        columns_to_exclude = {'row_id', 'tsd_name', 'tsd_id'}
        
        for row in data:
            if isinstance(row, dict):
                # Filter out the internal columns
                filtered_row = {k: v for k, v in row.items() if k not in columns_to_exclude}
                filtered_data.append(filtered_row)
            elif isinstance(row, list):
                # If it's a list (table format), we need to handle it differently
                # For now, keep it as is if it's not a dict
                filtered_data.append(row)
            else:
                filtered_data.append(row)
        
        # print(f"UNS: Filtered data length: {len(filtered_data)}")
        # print(f"UNS: Returning {len(filtered_data)} rows to frontend")
        
        return {
            "success": True,
            "data": filtered_data,
            "error": None
        }
    except Exception as e:
        error_msg = str(e)
        print(f"UNS: SQL query error: {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "data": None
        }

@api_router.post("/query-custom")
async def query_custom(request: QueryCustomRequest):
    """Execute a custom SQL query"""
    try:
        if not request.dbms or not request.sql_query:
            raise HTTPException(status_code=400, detail="dbms and sql_query are required")
        
        # Use the exact format that works in the client dashboard
        command = f'run client () sql {request.dbms} format = table "{request.sql_query}"'
        
        print(f"UNS: Executing custom SQL command: {command}")
        print(f"UNS: Connection: {request.conn}")
        print(f"UNS: DBMS: {request.dbms}")
        print(f"UNS: SQL Query: {request.sql_query}")
        
        # Use GET method like the client dashboard does
        response = make_request(request.conn, "GET", command)
        print("UNS: Custom query response", response)
        
        parsed = parse_response(response)
        print("UNS: Custom query parsed", parsed)
        
        # Extract data from response
        if isinstance(parsed, dict) and "data" in parsed:
            data = parsed["data"]
        elif isinstance(parsed, list):
            data = parsed
        elif isinstance(parsed, dict) and "type" in parsed:
            # Check if it's an error response
            if parsed.get("type") == "error":
                return {
                    "success": False,
                    "error": parsed.get("data", "Unknown error occurred"),
                    "data": None
                }
            data = parsed.get("data", parsed)
        else:
            data = parsed
        
        # Handle case where data might be a string (JSON string)
        if isinstance(data, str):
            try:
                import json
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                pass
        
        # Ensure data is a list
        if not isinstance(data, list):
            data = [data] if data else []
        
        if isinstance(data, list) and len(data) > 0:
            print(f"UNS: Custom query returned {len(data)} rows")
            print(f"UNS: First row sample: {data[0]}")
            print(f"UNS: Last row sample: {data[-1]}")
        
        # Filter out internal columns (row_id, tsd_name, tsd_id) from each row
        filtered_data = []
        columns_to_exclude = {'row_id', 'tsd_name', 'tsd_id'}
        
        for row in data:
            if isinstance(row, dict):
                # Filter out the internal columns
                filtered_row = {k: v for k, v in row.items() if k not in columns_to_exclude}
                filtered_data.append(filtered_row)
            elif isinstance(row, list):
                # If it's a list (table format), we need to handle it differently
                # For now, keep it as is if it's not a dict
                filtered_data.append(row)
            else:
                filtered_data.append(row)
        
        return {
            "success": True,
            "data": filtered_data,
            "error": None
        }
    except Exception as e:
        error_msg = str(e)
        print(f"UNS: Custom SQL query error: {error_msg}")
        return {
            "success": False,
            "error": error_msg,
            "data": None
        }

