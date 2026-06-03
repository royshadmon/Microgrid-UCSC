# (venv) ➜  Remote-GUI git:(bchain-optimz) ✗ uvicorn CLI.local-cli-backend.main:app --reload
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
sys.path.append(BASE_DIR)

from security.security_router import security_router

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Dict

from parsers import parse_response
from classes import *
from sql_router import sql_router
from file_auth_router import file_auth_router
# Import plugin loader
from plugins.loader import load_plugins, get_plugin_order
# Import feature config loader
from feature_config_loader import (
    is_feature_enabled, 
    is_plugin_enabled,
    get_enabled_features,
    get_enabled_plugins,
    load_feature_config
)



# from helpers import make_request, grab_network_nodes, monitor_network, make_policy, send_json_data
from helpers import make_request, grab_network_nodes, monitor_network, make_policy, send_json_data, make_preset_policy
import helpers


app = FastAPI()

FRONTEND_URL = os.getenv('FRONTEND_URL', '*')
# Allow CORS (React frontend -> FastAPI backend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "*"],  # Change this to your React app's URL for security
    allow_credentials=True,
    allow_methods=["*"],  # Allows GET, POST, PUT, DELETE, etc.
    allow_headers=["*"],  # Allows all headers
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Load feature configuration
feature_config = load_feature_config()
print("📋 Feature Configuration Loaded:")
print(f"   Enabled features: {get_enabled_features()}")
print(f"   Enabled plugins: {get_enabled_plugins()}")

# Middleware to block disabled features
@app.middleware("http")
async def feature_check_middleware(request: Request, call_next):
    """Middleware to block access to disabled features"""
    path = request.url.path
    
    # Skip feature checks for static files, docs, and config endpoints
    if (path.startswith("/static/") or 
        path.startswith("/docs") or 
        path.startswith("/openapi.json") or
        path == "/" or
        path == "/feature-config"):
        response = await call_next(request)
        return response
    
    # Map URL paths to feature names
    feature_path_map = {
        "/sql": "sqlquery",
        "/auth": "bookmarks",  # file_auth_router handles both bookmarks and presets
        "/security": "security",
    }
    
    # Check if path matches a feature
    for prefix, feature_name in feature_path_map.items():
        if path.startswith(prefix):
            # Special handling for /auth endpoints
            if prefix == "/auth":
                # Check if it's a bookmark or preset endpoint
                if "bookmark" in path:
                    if not is_feature_enabled("bookmarks"):
                        return Response(
                            content='{"detail": "Feature \'bookmarks\' is disabled"}',
                            status_code=403,
                            media_type="application/json"
                        )
                elif "preset" in path:
                    if not is_feature_enabled("presets"):
                        return Response(
                            content='{"detail": "Feature \'presets\' is disabled"}',
                            status_code=403,
                            media_type="application/json"
                        )
                # If neither, allow if either is enabled (backward compatibility)
                elif not (is_feature_enabled("bookmarks") or is_feature_enabled("presets")):
                    return Response(
                        content='{"detail": "Feature is disabled"}',
                        status_code=403,
                        media_type="application/json"
                    )
            else:
                # Check if feature is enabled
                if not is_feature_enabled(feature_name):
                    return Response(
                        content=f'{{"detail": "Feature \'{feature_name}\' is disabled"}}',
                        status_code=403,
                        media_type="application/json"
                    )
            break
    
    # Check main endpoints
    endpoint_feature_map = {
        "/send-command/": "client",
        "/get-network-nodes/": "client",
        "/monitor/": "monitor",
        "/submit-policy/": "policies",
        "/add-data/": "adddata",
        "/view-blobs/": "viewfiles",
        "/view-streaming/": "viewfiles",
        "/get-preset-policy/": "presets",
    }
    
    if path in endpoint_feature_map:
        feature_name = endpoint_feature_map[path]
        if not is_feature_enabled(feature_name):
            return Response(
                content=f'{{"detail": "Feature \'{feature_name}\' is disabled"}}',
                status_code=403,
                media_type="application/json"
            )
    
    response = await call_next(request)
    return response

# Include routers conditionally based on feature config
if is_feature_enabled("sqlquery"):
    app.include_router(sql_router)
    print("✅ SQL Router enabled")
else:
    print("❌ SQL Router disabled")

# file_auth_router handles both bookmarks and presets
if is_feature_enabled("bookmarks") or is_feature_enabled("presets"):
    app.include_router(file_auth_router)
    print("✅ File Auth Router enabled (bookmarks/presets)")
else:
    print("❌ File Auth Router disabled")

if is_feature_enabled("security"):
    app.include_router(security_router)
    print("✅ Security Router enabled")
else:
    print("❌ Security Router disabled")

# Load plugins (will respect feature config internally)
load_plugins(app)

# Feature configuration endpoint for frontend
@app.get("/feature-config")
def get_feature_config_endpoint():
    """Get the feature configuration for frontend"""
    config = load_feature_config()
    # Return only enabled status for each feature/plugin
    features_status = {
        name: {"enabled": data.get("enabled", True)}
        for name, data in config.get("features", {}).items()
    }
    plugins_status = {
        name: {"enabled": data.get("enabled", True)}
        for name, data in config.get("plugins", {}).items()
    }
    return {
        "features": features_status,
        "plugins": plugins_status,
        "version": config.get("version", "1.0.0")
    }

# Plugin order endpoint for frontend
@app.get("/plugins/order")
def get_plugin_order_endpoint():
    """Get the plugin order configuration for frontend display"""
    plugins_dir = os.path.join(BASE_DIR, 'plugins')
    plugin_order = get_plugin_order(plugins_dir)
    return {
        "plugin_order": plugin_order if plugin_order else [],
        "has_custom_order": plugin_order is not None
    }

# 23.239.12.151:32349
# run client () sql edgex extend=(+node_name, @ip, @port, @dbms_name, @table_name) and format = json and timezone=Europe/Dublin  select  timestamp, file, class, bbox, status  from factory_imgs where timestamp >= now() - 1 hour and timestamp <= NOW() order by timestamp desc --> selection (columns: ip using ip and port using port and dbms using dbms_name and table using table_name and file using file) -->  description (columns: bbox as shape.rect)


@app.get("/")
def list_static_files():
    try:
        files = []
        for root, dirs, filenames in os.walk(STATIC_DIR):
            for filename in filenames:
                rel_dir = os.path.relpath(root, STATIC_DIR)
                rel_file = os.path.join(rel_dir, filename) if rel_dir != '.' else filename
                files.append(rel_file)
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# @app.get("/")
def get_status():
    # print("GET STATUS RUNNING")
    resp = make_request("23.239.12.151:32349", "GET", "blockchain get *")
    return {"status": resp}
    # user = supabase_get_user()
    # return {"data": user}

# File-based authentication endpoints are now handled by file_auth_router



# NODE API ENDPOINTS

@app.post("/send-command/")
def send_command(conn: Connection, command: Command):
    # Feature check (also handled by middleware, but double-check for safety)
    if not is_feature_enabled("client"):
        raise HTTPException(status_code=403, detail="Feature 'client' is disabled")
    try:
        raw_response = make_request(conn.conn, command.type, command.cmd.strip())
        print("raw_response", raw_response)

        # Check if the response is already an error response
        if isinstance(raw_response, dict) and raw_response.get("type") == "error":
            print("=== ERROR RESPONSE DETECTED ===")
            print(f"Full error response: {raw_response}")
            return raw_response

        structured_data = parse_response(raw_response)
        print("structured_data", structured_data)
        return structured_data
    except Exception as e:
        print(f"=== MAIN.PY ERROR ===")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        print(f"Command: {command.cmd}")
        print(f"Connection: {conn.conn}")
        print(f"=== END MAIN.PY ERROR ===")
        
        return {
            "type": "error",
            "data": f"Backend error: {str(e)}",
            "error_details": {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "command": command.cmd,
                "connection": conn.conn,
                "location": "main.py send_command"
            }
        }


@app.post("/get-network-nodes/")
def get_connected_nodes(conn: Connection):
    # Feature check
    if not is_feature_enabled("client"):
        raise HTTPException(status_code=403, detail="Feature 'client' is disabled")
    connected_nodes = grab_network_nodes(conn.conn)
    return {"data": connected_nodes}

@app.post("/monitor/")
def monitor(conn: Connection):
    # Feature check
    if not is_feature_enabled("monitor"):
        raise HTTPException(status_code=403, detail="Feature 'monitor' is disabled")
    monitored_nodes = monitor_network(conn.conn)
    return {"data": monitored_nodes}

@app.post("/submit-policy/")
def submit_policy(conn: Connection, policy: Policy):
    # Feature check
    if not is_feature_enabled("policies"):
        raise HTTPException(status_code=403, detail="Feature 'policies' is disabled")
    print("conn", conn)
    print("policy", policy)
    raw_response = make_policy(conn.conn, policy)

    structured_data = parse_response(raw_response)
    return structured_data


@app.post("/add-data/")
def send_data(conn: Connection, dbconn: DBConnection, data: list[Dict]):
    # Feature check
    if not is_feature_enabled("adddata"):
        raise HTTPException(status_code=403, detail="Feature 'adddata' is disabled")
    print("conn", conn.conn)
    print("db", dbconn.dbms)
    print("table", dbconn.table)
    print("data", type(data))

    raw_response = send_json_data(conn=conn.conn, dbms=dbconn.dbms, table=dbconn.table, data=data)

    structured_data = parse_response(raw_response)
    return structured_data


# Bookmark and preset endpoints are now handled by file_auth_router


# All bookmark and preset endpoints are now handled by file_auth_router


# Preset group endpoints are now handled by file_auth_router


# All preset endpoints are now handled by file_auth_router

@app.post("/get-preset-policy/")
def get_preset_policy():
    """
    Get all presets for a specific group for the authenticated user.
    """
    # Feature check
    if not is_feature_enabled("presets"):
        raise HTTPException(status_code=403, detail="Feature 'presets' is disabled")

    resp = helpers.get_preset_base_policy("23.239.12.151:32349")
    parsed = parse_response(resp)
    lb = parsed['data']['bookmark']['bookmarks']
    print("list of bookmarks:", lb)
    filtered_lb = {key: value for key, value in lb.items() if isinstance(value, dict)}
    
    return {"data": filtered_lb}


def construct_streaming_url(blob, connectInfo):
    """Construct streaming URL for a blob"""
    # Use the blob's node IP and port, not the connected node
    ip = blob.get('ip', '')
    port = blob.get('port', '')
    
    # If blob doesn't have ip/port, fall back to connected node
    if not ip or not port:
        if isinstance(connectInfo, str):
            # If connectInfo is a string like "23.239.12.151:32349", parse it
            if ':' in connectInfo:
                ip, port = connectInfo.split(':', 1)
            else:
                ip = connectInfo
                port = '32349'  # default port
        else:
            # If connectInfo is a dict, extract ip and port
            ip = connectInfo.get('ip', '')
            port = connectInfo.get('port', '')
    
    # Extract blob details
    dbms = blob.get('dbms_name', '')
    table = blob.get('video_table') or blob.get('table_name', '')
    blob_id = blob.get('file', '')  # Use 'file' instead of 'id' as blob_id
    
    # Construct the streaming URL using the blob's node
    streaming_url = f"http://{ip}:{port}/?User-Agent=AnyLog/1.23?command=file retrieve where dbms={dbms} and table={table} and id={blob_id} and stream=true?cb="
    
    return streaming_url

@app.post("/view-streaming/")
def view_streaming_blobs(request: dict):
    # Feature check
    if not is_feature_enabled("viewfiles"):
        raise HTTPException(status_code=403, detail="Feature 'viewfiles' is disabled")
    try:
        print(f"=== STREAMING REQUEST ===")
        print(f"Request type: {type(request)}")
        print(f"Request keys: {request.keys() if isinstance(request, dict) else 'Not a dict'}")
        print(f"Full request: {request}")
        print(f"=== END STREAMING REQUEST ===")
        
        # Extract connection and blob information
        connectInfo = request.get('connectInfo', {})
        blobs = request.get('blobs', {}).get('blobs', [])
        
        print(f"ConnectInfo: {connectInfo} (type: {type(connectInfo)})")
        print(f"Blobs: {blobs} (type: {type(blobs)}, length: {len(blobs) if isinstance(blobs, list) else 'N/A'})")
        
        # Construct streaming URLs for each blob
        streaming_urls = []
        for i, blob in enumerate(blobs):
            print(f"Processing blob {i}: {blob}")
            url = construct_streaming_url(blob, connectInfo)
            streaming_urls.append({
                'id': blob.get('file', ''),  # Use file as id
                'file': blob.get('file', ''),
                'streaming_url': url,
                'dbms': blob.get('dbms_name', ''),
                'table': blob.get('video_table') or blob.get('table_name', ''),
                'ip': blob.get('ip', ''),
                'port': blob.get('port', '')
            })
            print(f"Created streaming URL: {url}")
        
        print(f"Final streaming_urls: {streaming_urls}")
        
        return {
            "type": "streaming_urls",
            "data": streaming_urls
        }
    except Exception as e:
        print(f"=== STREAMING ERROR ===")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        print(f"Request: {request}")
        print(f"=== END STREAMING ERROR ===")
        
        return {
            "type": "error",
            "data": f"Error constructing streaming URLs: {str(e)}",
            "error_details": {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "request": str(request)
            }
        }


@app.post("/view-blobs/")
def view_blobs(conn: Connection, blobs: dict):
    # Feature check
    if not is_feature_enabled("viewfiles"):
        raise HTTPException(status_code=403, detail="Feature 'viewfiles' is disabled")
    print("conn", conn.conn)
    # print("blobs", blobs['blobs'])

    file_list = []
    for blob in blobs['blobs']:
        print("blob", blob)
        # Here you would implement the logic to view the blob

        ip_port = f"{blob['ip']}:{blob['port']}"
        operator_dbms = blob['dbms_name']
        operator_table = blob.get('video_table') or blob.get('table_name', '')
        operator_file = blob['file']
        file_list.append(operator_file)

        # blobs_dir = "/app/Remote-CLI/djangoProject/static/blobs/current/"
        blobs_dir = "/app/CLI/local-cli-backend/static/"
        # if not os.path.exists(blobs_dir): 
        #     print("Blobs directory does not exist")
        #     root = __file__.split("CLI")[0] 
        #     blobs_dir = blobs_dir.replace('/app', root) 
        print("IP:Port", ip_port)

        print("blobs_dir", blobs_dir)


        # cmd = f'run client ({ip_port}) file get !!blockchain_file !blockchain_file'
        # cmd = f'run client ({ip_port}) file get !!blobs_dir/{operator_file} !blobs_dir/{operator_file}'
        

        cmd = f"run client ({ip_port}) file get (dbms = blobs_{operator_dbms} and table = {operator_table} and id = {operator_file}) {blobs_dir}{operator_dbms}.{operator_table}.{operator_file}"  # Add file full path and name for the destination on THIS MACHINE
        raw_response = make_request(conn.conn, "POST", cmd)

        try:
            files_in_dir = os.listdir(blobs_dir)
            print("Files in blobs_dir:", files_in_dir)
        except Exception as e:
            print(f"Error listing files in {blobs_dir}: {e}")
            files_in_dir = []

        print("raw_response", raw_response)


    return {"data": file_list}



# streaming
# info = (dest_type = rest) 
# for streaming — views.py method stream_process
# uses post
# cmd: source_url = f"http://{ip}:{port}/?User-Agent=AnyLog/1.23?command=file retrieve where dbms={dbms} and table={table} and id={file} and stream = true"

# build image or video or audio (aka any file) viewer




# http://45.33.110.211:31800
