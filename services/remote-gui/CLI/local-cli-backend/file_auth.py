import json
import hashlib
import os
import uuid
import shutil
import platform
from datetime import datetime
from typing import Dict, List, Optional
import tempfile
from pathlib import Path

# Default user ID for all operations (no authentication needed)
DEFAULT_USER_ID = "default-user-12345"

# # Old File paths for data storage
# USERS_FILE = "usr-mgm/users.json"
# BOOKMARKS_FILE = "usr-mgm/bookmarks.json"
# PRESETS_FILE = "usr-mgm/presets.json"
# PRESET_GROUPS_FILE = "usr-mgm/preset_groups.json"

# Base data directory (configurable via env; default to backend/usr-mgm next to this file)
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "usr-mgm"))

# Platform detection for debugging
PLATFORM_INFO = {
    "system": platform.system(),
    "release": platform.release(),
    "version": platform.version(),
    "machine": platform.machine(),
    "processor": platform.processor()
}

print(f"Platform info: {PLATFORM_INFO}")
print(f"Base directory: {BASE_DIR}")
print(f"Data directory: {DATA_DIR}")

DATA_DIR.mkdir(parents=True, exist_ok=True)

USERS_FILE = DATA_DIR / "users.json"
BOOKMARKS_FILE = DATA_DIR / "bookmarks.json"
PRESETS_FILE = DATA_DIR / "presets.json"
PRESET_GROUPS_FILE = DATA_DIR / "preset_groups.json"

_DEFAULTS: Dict[Path, Dict] = {
    USERS_FILE: {"users": []},
    BOOKMARKS_FILE: {"bookmarks": {}},
    PRESETS_FILE: {"presets": []},
    PRESET_GROUPS_FILE: {"preset_groups": []},
}

def _read_json(path: Path) -> Dict:
    try:
        if path.exists():
            with path.open("r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading {path}: {e}")
    return _DEFAULTS.get(path, {})

def _write_json_simple(path: Path, data: Dict):
    """Simple non-atomic file writing as fallback"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Writing directly to: {path}")
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"File written successfully: {path}")
    except Exception as e:
        print(f"Error in simple write {path}: {e}")
        raise

def _write_json_atomic(path: Path, data: Dict):
    """Atomic file writing with fallback to simple write"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Creating directory: {path.parent}")
    except Exception as e:
        print(f"Error creating directory {path.parent}: {e}")
        raise
    
    tmp = None
    try:
        print(f"Writing to temporary file in: {path.parent}")
        with tempfile.NamedTemporaryFile("w", dir=str(path.parent), delete=False) as t:
            json.dump(data, t, indent=2)
            t.flush()
            os.fsync(t.fileno())
            tmp = t.name
            print(f"Temporary file created: {tmp}")
        
        # Use shutil.move instead of os.replace for better cross-platform compatibility
        print(f"Moving {tmp} to {path}")
        shutil.move(tmp, path)
        print(f"File successfully written to: {path}")
    except Exception as e:
        print(f"Atomic write failed, trying simple write: {e}")
        # Fallback to simple write if atomic fails
        try:
            _write_json_simple(path, data)
        except Exception as simple_error:
            print(f"Simple write also failed: {simple_error}")
            raise simple_error
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
                print(f"Cleaned up temporary file: {tmp}")
            except Exception as e:
                print(f"Error cleaning up temporary file {tmp}: {e}")

# keep your existing functions, but switch to the helpers:
def load_json_file(filename) -> Dict:
    # filename can be either a string or Path object
    if isinstance(filename, str):
        filename = Path(filename)
    return _read_json(filename)

def save_json_file(filename, data: Dict):
    # filename can be either a string or Path object
    if isinstance(filename, str):
        filename = Path(filename)
    _write_json_atomic(filename, data)

# def load_json_file(filename: str) -> Dict:
#     """Load data from a JSON file"""
#     try:
#         if os.path.exists(filename):
#             with open(filename, 'r') as f:
#                 return json.load(f)
#         else:
#             # Return default structure if file doesn't exist
#             if filename == USERS_FILE:
#                 return {"users": []}
#             elif filename == BOOKMARKS_FILE:
#                 return {"bookmarks": {}}  # Changed to nested structure
#             elif filename == PRESETS_FILE:
#                 return {"presets": []}
#             elif filename == PRESET_GROUPS_FILE:
#                 return {"preset_groups": []}
#             else:
#                 return {}
#     except Exception as e:
#         print(f"Error loading {filename}: {e}")
#         return {}

# def save_json_file(filename: str, data: Dict):
#     """Save data to a JSON file"""
#     try:
#         with open(filename, 'w') as f:
#             json.dump(data, f, indent=2)
#     except Exception as e:
#         print(f"Error saving {filename}: {e}")

def hash_password(password: str) -> str:
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def file_signup(email: str, password: str, firstname: str, lastname: str) -> Dict:
    """Register a new user"""
    try:
        print(f"Starting signup for email: {email}")
        print(f"Platform: {PLATFORM_INFO}")
        print(f"Users file path: {USERS_FILE}")
        print(f"Users file exists: {USERS_FILE.exists()}")
        
        users_data = load_json_file(USERS_FILE)
        print(f"Loaded users data: {len(users_data.get('users', []))} users")
        
        # Check if user already exists
        for user in users_data.get("users", []):
            if user.get("email") == email:
                print(f"User already exists: {email}")
                return {"error": "User already exists"}
        
        # Create new user
        new_user = {
            "id": str(uuid.uuid4()),
            "email": email,
            "password": hash_password(password),
            "firstname": firstname,
            "lastname": lastname,
            "created_at": datetime.now().isoformat()
        }
        
        print(f"Created new user with ID: {new_user['id']}")
        users_data.setdefault("users", []).append(new_user)
        print(f"Total users after adding: {len(users_data['users'])}")
        
        print("Saving users data...")
        save_json_file(USERS_FILE, users_data)
        print("Users data saved successfully")
        
        return {
            "user": {
                "id": new_user["id"],
                "email": new_user["email"],
                "firstname": new_user["firstname"],
                "lastname": new_user["lastname"],
                "created_at": new_user["created_at"]
            }
        }
    except Exception as e:
        print(f"Error in file_signup: {e}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return {"error": f"Signup failed: {str(e)}"}

def file_login(email: str, password: str) -> Dict:
    """Authenticate a user"""
    users_data = load_json_file(USERS_FILE)
    
    hashed_password = hash_password(password)
    
    for user in users_data.get("users", []):
        if user.get("email") == email and user.get("password") == hashed_password:
            return {
                "user": {
                    "id": user["id"],
                    "email": user["email"],
                    "firstname": user["firstname"],
                    "lastname": user["lastname"],
                    "created_at": user["created_at"]
                }
            }
    
    return {"error": "Invalid email or password"}

def file_get_user(user_id: str) -> Optional[Dict]:
    """Get user by ID"""
    users_data = load_json_file(USERS_FILE)
    
    for user in users_data.get("users", []):
        if user.get("id") == user_id:
            return {
                "id": user["id"],
                "email": user["email"],
                "firstname": user["firstname"],
                "lastname": user["lastname"],
                "created_at": user["created_at"]
            }
    
    return None

def file_bookmark_node(node: str) -> Dict:
    """Add a bookmark for the default user"""
    bookmarks_data = load_json_file(BOOKMARKS_FILE)
    
    # Initialize bookmarks structure if it doesn't exist
    if "bookmarks" not in bookmarks_data:
        bookmarks_data["bookmarks"] = []
    
    # Check if bookmark already exists
    for bookmark in bookmarks_data["bookmarks"]:
        if bookmark.get("node", {}).get("conn") == node:
            return {"message": "Bookmark already exists"}
    
    # Add new bookmark
    new_bookmark = {
        "id": str(uuid.uuid4()),
        "node": {"conn": node},
        "description": "",
        "created_at": datetime.now().isoformat(),
        "is_default": False
    }
    
    bookmarks_data["bookmarks"].append(new_bookmark)
    save_json_file(BOOKMARKS_FILE, bookmarks_data)
    
    return {"bookmark": {"user_id": DEFAULT_USER_ID, "node": node, "description": "", "created_at": new_bookmark["created_at"]}}

def file_get_bookmarked_nodes() -> List[Dict]:
    """Get all bookmarks for the default user"""
    bookmarks_data = load_json_file(BOOKMARKS_FILE)
    
    user_bookmarks = []
    if "bookmarks" in bookmarks_data:
        for bookmark in bookmarks_data["bookmarks"]:
            user_bookmarks.append({
                "user_id": DEFAULT_USER_ID,
                "node": bookmark.get("node", {}).get("conn", ""),
                "description": bookmark.get("description", ""),
                "created_at": bookmark.get("created_at", ""),
                "is_default": bookmark.get("is_default", False)
            })
    
    return user_bookmarks

def file_delete_bookmarked_node(node: str) -> Dict:
    """Delete a bookmark for the default user"""
    print(f"Attempting to delete bookmark with node: {node}")
    bookmarks_data = load_json_file(BOOKMARKS_FILE)
    print(f"Current bookmarks: {bookmarks_data}")
    
    if "bookmarks" in bookmarks_data:
        for i, bookmark in enumerate(bookmarks_data["bookmarks"]):
            bookmark_node = bookmark.get("node", {}).get("conn")
            print(f"Checking bookmark {i}: {bookmark_node} vs {node}")
            if bookmark_node == node:
                print(f"Found bookmark to delete at index {i}")
                del bookmarks_data["bookmarks"][i]
                save_json_file(BOOKMARKS_FILE, bookmarks_data)
                print("Bookmark deleted successfully")
                return {"message": "Bookmark deleted successfully"}
    
    print("Bookmark not found")
    return {"error": "Bookmark not found"}

def file_update_bookmark_description(node: str, description: str) -> Dict:
    """Update bookmark description for the default user"""
    bookmarks_data = load_json_file(BOOKMARKS_FILE)
    
    if "bookmarks" in bookmarks_data:
        for bookmark in bookmarks_data["bookmarks"]:
            if bookmark.get("node", {}).get("conn") == node:
                bookmark["description"] = description
                save_json_file(BOOKMARKS_FILE, bookmarks_data)
                return {"message": "Bookmark updated successfully"}
    
    return {"error": "Bookmark not found"}

def file_set_default_bookmark(node: str) -> Dict:
    """Set a single bookmark as default and unset others"""
    bookmarks_data = load_json_file(BOOKMARKS_FILE)
    if "bookmarks" not in bookmarks_data:
        bookmarks_data["bookmarks"] = []

    found = False
    for bookmark in bookmarks_data["bookmarks"]:
        if bookmark.get("node", {}).get("conn") == node:
            bookmark["is_default"] = True
            found = True
        else:
            # ensure others are not default
            if "is_default" in bookmark and bookmark["is_default"]:
                bookmark["is_default"] = False

    if not found:
        return {"error": "Bookmark not found"}

    save_json_file(BOOKMARKS_FILE, bookmarks_data)
    return {"message": "Default bookmark set", "node": node}

def file_add_preset_group(group_name: str) -> Dict:
    """Add a preset group for the default user"""
    groups_data = load_json_file(PRESET_GROUPS_FILE)
    
    # Check if group already exists
    for group in groups_data.get("preset_groups", []):
        if group.get("user_id") == DEFAULT_USER_ID and group.get("group_name") == group_name:
            return {"error": "Group already exists"}
    
    # Add new group
    new_group = {
        "id": str(uuid.uuid4()),
        "user_id": DEFAULT_USER_ID,
        "group_name": group_name,
        "created_at": datetime.now().isoformat()
    }
    
    groups_data.setdefault("preset_groups", []).append(new_group)
    save_json_file(PRESET_GROUPS_FILE, groups_data)
    
    return {"group": new_group}

def file_get_preset_groups() -> List[Dict]:
    """Get all preset groups for the default user"""
    groups_data = load_json_file(PRESET_GROUPS_FILE)
    
    user_groups = []
    for group in groups_data.get("preset_groups", []):
        if group.get("user_id") == DEFAULT_USER_ID:
            user_groups.append(group)
    
    return user_groups

def file_add_preset_to_group(group_id: str, command: str, type: str, button: str) -> Dict:
    """Add a preset to a group for the default user"""
    presets_data = load_json_file(PRESETS_FILE)
    
    # Verify group exists and belongs to default user
    groups_data = load_json_file(PRESET_GROUPS_FILE)
    group_exists = False
    for group in groups_data.get("preset_groups", []):
        if group.get("id") == group_id and group.get("user_id") == DEFAULT_USER_ID:
            group_exists = True
            break
    
    if not group_exists:
        return {"error": "Group not found or access denied"}
    
    # Add new preset
    new_preset = {
        "id": str(uuid.uuid4()),
        "user_id": DEFAULT_USER_ID,
        "group_id": group_id,
        "command": command,
        "type": type,
        "button": button,
        "created_at": datetime.now().isoformat()
    }
    
    presets_data.setdefault("presets", []).append(new_preset)
    save_json_file(PRESETS_FILE, presets_data)
    
    return {"preset": new_preset}

def file_get_presets_by_group(group_id: str) -> List[Dict]:
    """Get all presets for a specific group for the default user"""
    presets_data = load_json_file(PRESETS_FILE)
    
    group_presets = []
    for preset in presets_data.get("presets", []):
        if preset.get("user_id") == DEFAULT_USER_ID and preset.get("group_id") == group_id:
            group_presets.append(preset)
    
    return group_presets

def file_delete_preset_group(group_id: str) -> Dict:
    """Delete a preset group and all its presets for the default user"""
    print(f"Attempting to delete group {group_id} for default user")
    
    groups_data = load_json_file(PRESET_GROUPS_FILE)
    presets_data = load_json_file(PRESETS_FILE)

    print("Group ID: ", group_id)
    
    # Check if group exists and belongs to default user
    group_exists = False
    for group in groups_data.get("preset_groups", []):
        if group.get("id") == group_id and group.get("user_id") == DEFAULT_USER_ID:
            group_exists = True
            print(f"Found group: {group.get('group_name')} (ID: {group.get('id')})")
            break
    
    if not group_exists:
        print(f"Group {group_id} not found or doesn't belong to default user")
        return {"error": "Group not found or access denied"}
    
    # Delete the group
    original_group_count = len(groups_data.get("preset_groups", []))
    groups_data["preset_groups"] = [
        group for group in groups_data.get("preset_groups", [])
        if not (group.get("id") == group_id and group.get("user_id") == DEFAULT_USER_ID)
    ]
    
    if len(groups_data["preset_groups"]) < original_group_count:
        print(f"Group deleted successfully. Groups before: {original_group_count}, after: {len(groups_data['preset_groups'])}")
        save_json_file(PRESET_GROUPS_FILE, groups_data)
        
        # Delete all presets in this group
        original_preset_count = len(presets_data.get("presets", []))
        presets_data["presets"] = [
            preset for preset in presets_data.get("presets", [])
            if not (preset.get("group_id") == group_id and preset.get("user_id") == DEFAULT_USER_ID)
        ]
        
        presets_deleted = original_preset_count - len(presets_data["presets"])
        print(f"Presets deleted: {presets_deleted}. Presets before: {original_preset_count}, after: {len(presets_data['presets'])}")
        
        # Always save presets file, even if no presets were deleted
        save_json_file(PRESETS_FILE, presets_data)
        
        return {"message": f"Group and {presets_deleted} presets deleted successfully"}
    else:
        print(f"Failed to delete group. Groups before: {original_group_count}, after: {len(groups_data['preset_groups'])}")
        return {"error": "Group not found or access denied"}

def file_delete_preset(preset_id: str) -> Dict:
    """Delete an individual preset for the default user"""
    presets_data = load_json_file(PRESETS_FILE)
    
    # Find and delete the preset
    original_preset_count = len(presets_data.get("presets", []))
    presets_data["presets"] = [
        preset for preset in presets_data.get("presets", [])
        if not (preset.get("id") == preset_id and preset.get("user_id") == DEFAULT_USER_ID)
    ]
    
    if len(presets_data["presets"]) < original_preset_count:
        save_json_file(PRESETS_FILE, presets_data)
        return {"message": "Preset deleted successfully"}
    else:
        return {"error": "Preset not found or access denied"}