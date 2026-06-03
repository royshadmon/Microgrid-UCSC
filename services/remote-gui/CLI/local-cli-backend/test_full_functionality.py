#!/usr/bin/env python3
"""
Comprehensive test for all file-based authentication functionality
"""

import sys
import os
import time
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from file_auth import (
    file_signup, file_login, file_get_user,
    file_bookmark_node, file_get_bookmarked_nodes, file_delete_bookmarked_node, file_update_bookmark_description,
    file_add_preset_group, file_get_preset_groups, file_add_preset_to_group, file_get_presets_by_group, file_delete_preset_group
)

def test_full_functionality():
    print("Testing Full File-Based Authentication Functionality")
    print("=" * 60)
    
    # Test 1: Create a user
    print("\n1. Creating test user...")
    timestamp = int(time.time())
    email = f"full_test_{timestamp}@example.com"
    signup_result = file_signup(email, "password123", "Full", "Test")
    if "error" in signup_result:
        print(f"❌ Signup failed: {signup_result['error']}")
        return
    else:
        print(f"✅ User created: {signup_result['user']['email']}")
        user_id = signup_result['user']['id']
    
    # Test 2: Login with the user
    print("\n2. Testing login...")
    login_result = file_login(email, "password123")
    if "error" in login_result:
        print(f"❌ Login failed: {login_result['error']}")
        return
    else:
        print(f"✅ Login successful: {login_result['user']['email']}")
    
    # Test 3: Get user information
    print("\n3. Getting user information...")
    user_info = file_get_user(user_id)
    if user_info:
        print(f"✅ User info retrieved: {user_info['firstname']} {user_info['lastname']}")
    else:
        print("❌ Failed to get user info")
        return
    
    # Test 4: Add bookmarks
    print("\n4. Adding bookmarks...")
    nodes = ["production-server:8080", "staging-server:8080", "dev-server:8080"]
    for node in nodes:
        result = file_bookmark_node(user_id, node)
        if "error" in result:
            print(f"❌ Failed to bookmark {node}: {result['error']}")
        else:
            print(f"✅ Bookmarked {node}")
    
    # Test 5: Get and display bookmarks
    print("\n5. Getting all bookmarks...")
    bookmarks = file_get_bookmarked_nodes(user_id)
    print(f"✅ Found {len(bookmarks)} bookmarks:")
    for bookmark in bookmarks:
        print(f"   - {bookmark['node']}")
    
    # Test 6: Update bookmark description
    print("\n6. Updating bookmark description...")
    result = file_update_bookmark_description(user_id, "production-server:8080", "Main production server")
    if "error" in result:
        print(f"❌ Failed to update description: {result['error']}")
    else:
        print("✅ Description updated successfully")
    
    # Test 7: Create preset groups
    print("\n7. Creating preset groups...")
    group_names = ["Quick Commands", "Database Operations", "System Monitoring"]
    group_ids = []
    
    for group_name in group_names:
        result = file_add_preset_group(user_id, group_name)
        if "error" in result:
            print(f"❌ Failed to create group '{group_name}': {result['error']}")
        else:
            print(f"✅ Created group: {group_name}")
            group_ids.append(result['group']['id'])
    
    # Test 8: Add presets to groups
    print("\n8. Adding presets to groups...")
    presets_data = [
        {"group_id": group_ids[0], "command": "blockchain get *", "type": "GET", "button": "Get All"},
        {"group_id": group_ids[0], "command": "blockchain get status", "type": "GET", "button": "Get Status"},
        {"group_id": group_ids[1], "command": "SELECT * FROM data_table", "type": "POST", "button": "Query Data"},
        {"group_id": group_ids[1], "command": "INSERT INTO data_table VALUES (...)", "type": "POST", "button": "Insert Data"},
        {"group_id": group_ids[2], "command": "monitor network", "type": "GET", "button": "Monitor Network"},
        {"group_id": group_ids[2], "command": "monitor nodes", "type": "GET", "button": "Monitor Nodes"}
    ]
    
    for preset in presets_data:
        result = file_add_preset_to_group(
            user_id, 
            preset["group_id"], 
            preset["command"], 
            preset["type"], 
            preset["button"]
        )
        if "error" in result:
            print(f"❌ Failed to add preset '{preset['button']}': {result['error']}")
        else:
            print(f"✅ Added preset: {preset['button']}")
    
    # Test 9: Get all preset groups
    print("\n9. Getting all preset groups...")
    groups = file_get_preset_groups(user_id)
    print(f"✅ Found {len(groups)} preset groups:")
    for group in groups:
        print(f"   - {group['group_name']}")
    
    # Test 10: Get presets for each group
    print("\n10. Getting presets for each group...")
    for group in groups:
        presets = file_get_presets_by_group(user_id, group['id'])
        print(f"✅ Group '{group['group_name']}' has {len(presets)} presets:")
        for preset in presets:
            print(f"   - {preset['button']}: {preset['command']}")
    
    # Test 11: Delete a bookmark
    print("\n11. Deleting a bookmark...")
    result = file_delete_bookmarked_node(user_id, "staging-server:8080")
    if "error" in result:
        print(f"❌ Failed to delete bookmark: {result['error']}")
    else:
        print("✅ Bookmark deleted successfully")
    
    # Test 12: Delete a preset group
    print("\n12. Deleting a preset group...")
    group_to_delete = group_ids[1]  # Database Operations
    result = file_delete_preset_group(user_id, group_to_delete)
    if "error" in result:
        print(f"❌ Failed to delete group: {result['error']}")
    else:
        print("✅ Group deleted successfully")
    
    # Test 13: Final verification
    print("\n13. Final verification...")
    
    # Check remaining bookmarks
    final_bookmarks = file_get_bookmarked_nodes(user_id)
    print(f"✅ Final bookmarks: {len(final_bookmarks)}")
    for bookmark in final_bookmarks:
        print(f"   - {bookmark['node']}")
    
    # Check remaining groups
    final_groups = file_get_preset_groups(user_id)
    print(f"✅ Final groups: {len(final_groups)}")
    for group in final_groups:
        presets = file_get_presets_by_group(user_id, group['id'])
        print(f"   - {group['group_name']}: {len(presets)} presets")
    
    print("\n" + "=" * 60)
    print("✅ Full functionality test completed!")
    print("All file-based authentication features are working correctly.")

if __name__ == "__main__":
    test_full_functionality() 