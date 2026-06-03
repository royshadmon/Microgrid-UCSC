from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict
import file_auth
from classes import BookmarkUpdateRequest, PresetGroup, PresetGroupID, Preset, PresetID

# Create router
file_auth_router = APIRouter(prefix="/auth", tags=["file-auth"])

@file_auth_router.post("/bookmark-node/")
def bookmark_node(conn: Dict):
    """Bookmark a node for the default user"""
    node = conn.get("conn", {}).get("conn")
    print("Bookmark node:", node)
    
    response = file_auth.file_bookmark_node(node)
    return {"data": response}

@file_auth_router.post("/get-bookmarked-nodes/")
def get_bookmarked_nodes():
    """Get all bookmarked nodes for the default user"""
    response = file_auth.file_get_bookmarked_nodes()
    return {"data": response}

@file_auth_router.post("/delete-bookmarked-node/")
def delete_bookmarked_node(conn: Dict):
    """Delete a bookmarked node for the default user"""
    node = conn.get("conn", {}).get("conn")
    print("Delete bookmark node:", node)
    
    response = file_auth.file_delete_bookmarked_node(node)
    return {"data": response}

@file_auth_router.post("/update-bookmark-description/")
def update_bookmark_description(request: BookmarkUpdateRequest):
    """Update bookmark description for the default user"""
    response = file_auth.file_update_bookmark_description(request.node, request.description)
    return {"data": response}

@file_auth_router.post("/set-default-bookmark/")
def set_default_bookmark(conn: Dict):
    """Set a bookmark as default for the default user"""
    node = conn.get("conn", {}).get("conn")
    response = file_auth.file_set_default_bookmark(node)
    return {"data": response}

@file_auth_router.post("/add-preset-group/")
def add_preset_group(request: Dict):
    """Add a preset group for the default user"""
    group_name = request.get("group_name")
    print("Group name:", group_name)
    
    response = file_auth.file_add_preset_group(group_name)
    return {"data": response}

@file_auth_router.post("/get-preset-groups/")
def get_preset_groups():
    """Get all preset groups for the default user"""
    response = file_auth.file_get_preset_groups()
    return {"data": response}

@file_auth_router.post("/add-preset/")
def add_preset_to_group(request: Dict):
    """Add a preset to a group for the default user"""
    print("Preset:", request)
    
    response = file_auth.file_add_preset_to_group(request.get("group_id"), request.get("command"), request.get("type"), request.get("button"))
    return {"data": response}

@file_auth_router.post("/get-presets/")
def get_presets(request: Dict):
    """Get all presets for a specific group for the default user"""
    group_id = request.get("group_id")
    print("Group ID:", group_id)
    
    response = file_auth.file_get_presets_by_group(group_id)
    return {"data": response}

@file_auth_router.post("/delete-preset-group/")
def delete_preset_group(request: Dict):
    """Delete a preset group for the default user"""
    group_id = request.get("group_id")
    group_name = request.get("group_name")
    print("Group ID:", group_id)
    print("Group name:", group_name)
    
    response = file_auth.file_delete_preset_group(group_id)
    print(f"Delete response: {response}")
    return {"data": response}

@file_auth_router.post("/delete-preset/")
def delete_preset(request: Dict):
    """Delete an individual preset for the default user"""
    preset_id = request.get("preset_id")
    print("Preset ID:", preset_id)
    
    response = file_auth.file_delete_preset(preset_id)
    return {"data": response} 