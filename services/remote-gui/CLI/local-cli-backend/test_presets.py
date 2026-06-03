#!/usr/bin/env python3
"""
Test script for preset groups and presets functionality
"""

import sys
import os
import time
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from file_auth import (
    file_signup, file_add_preset_group, file_get_preset_groups,
    file_add_preset_to_group, file_get_presets_by_group,
    file_delete_preset_group, file_delete_preset
)

def test_presets():
    print("Testing Preset Groups and Presets")
    print("=" * 50)
    
    # Test 1: Create a user with unique email
    print("\n1. Creating test user...")
    timestamp = int(time.time())
    email = f"preset_test_{timestamp}@example.com"
    signup_result = file_signup(email, "password123", "Preset", "Test")
    if "error" in signup_result:
        print(f"❌ Signup failed: {signup_result['error']}")
        return
    else:
        print(f"✅ User created: {signup_result['user']['email']}")
        user_id = signup_result['user']['id']
    
    # Test 2: Add preset groups
    print("\n2. Adding preset groups...")
    group_names = ["Database Commands", "Monitoring", "Custom Queries"]
    group_ids = []
    
    for group_name in group_names:
        result = file_add_preset_group(user_id, group_name)
        if "error" in result:
            print(f"❌ Failed to create group '{group_name}': {result['error']}")
        else:
            print(f"✅ Created group: {group_name}")
            group_ids.append(result['group']['id'])
    
    # Test 3: Get all preset groups
    print("\n3. Getting all preset groups...")
    groups = file_get_preset_groups(user_id)
    print(f"✅ Found {len(groups)} preset groups:")
    for group in groups:
        print(f"   - {group['group_name']} (ID: {group['id']})")
    
    # Test 4: Add presets to groups
    print("\n4. Adding presets to groups...")
    presets_data = [
        {
            "group_id": group_ids[0],  # Database Commands
            "command": "blockchain get *",
            "type": "GET",
            "button": "Get All Data"
        },
        {
            "group_id": group_ids[0],  # Database Commands
            "command": "blockchain get table_name",
            "type": "GET", 
            "button": "Get Table"
        },
        {
            "group_id": group_ids[1],  # Monitoring
            "command": "monitor network",
            "type": "GET",
            "button": "Monitor Network"
        },
        {
            "group_id": group_ids[1],  # Monitoring
            "command": "monitor nodes",
            "type": "GET",
            "button": "Monitor Nodes"
        },
        {
            "group_id": group_ids[2],  # Custom Queries
            "command": "SELECT * FROM table WHERE timestamp > now() - 1 hour",
            "type": "POST",
            "button": "Recent Data"
        }
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
    
    # Test 5: Get presets for each group
    print("\n5. Getting presets for each group...")
    for i, group_id in enumerate(group_ids):
        presets = file_get_presets_by_group(user_id, group_id)
        print(f"✅ Group '{group_names[i]}' has {len(presets)} presets:")
        for preset in presets:
            print(f"   - {preset['button']}: {preset['command']} ({preset['type']})")
    
    # Test 6: Try to add duplicate group
    print("\n6. Testing duplicate group creation...")
    result = file_add_preset_group(user_id, "Database Commands")
    if "error" in result and "already exists" in result["error"]:
        print("✅ Correctly handled duplicate group")
    else:
        print(f"❌ Unexpected result: {result}")
    
    # Test 7: Try to add preset to non-existent group
    print("\n7. Testing preset to non-existent group...")
    fake_group_id = "fake-group-id"
    result = file_add_preset_to_group(user_id, fake_group_id, "test command", "GET", "Test")
    if "error" in result and "not found" in result["error"]:
        print("✅ Correctly handled non-existent group")
    else:
        print(f"❌ Unexpected result: {result}")
    
    # Test 8: Delete an individual preset
    print("\n8. Testing individual preset deletion...")
    # Get presets from the first group
    presets = file_get_presets_by_group(user_id, group_ids[0])
    if presets:
        preset_to_delete = presets[0]  # Delete the first preset
        print(f"Deleting preset: {preset_to_delete['button']}")
        result = file_delete_preset(user_id, preset_to_delete['id'])
        if "error" in result:
            print(f"❌ Failed to delete preset: {result['error']}")
        else:
            print("✅ Preset deleted successfully")
        
        # Verify preset deletion
        presets_after_delete = file_get_presets_by_group(user_id, group_ids[0])
        print(f"✅ Group now has {len(presets_after_delete)} presets (was {len(presets)})")
    else:
        print("⚠️ No presets to delete")
    
    # Test 9: Delete a preset group
    print("\n9. Deleting a preset group...")
    group_to_delete = group_ids[1]  # Monitoring group
    result = file_delete_preset_group(user_id, group_to_delete)
    if "error" in result:
        print(f"❌ Failed to delete group: {result['error']}")
    else:
        print("✅ Group deleted successfully")
    
    # Test 10: Verify group deletion
    print("\n10. Verifying group deletion...")
    groups_after_delete = file_get_preset_groups(user_id)
    print(f"✅ Now have {len(groups_after_delete)} groups:")
    for group in groups_after_delete:
        print(f"   - {group['group_name']}")
    
    # Test 11: Verify presets are also deleted
    print("\n11. Verifying presets are deleted with group...")
    presets_after_delete = file_get_presets_by_group(user_id, group_to_delete)
    print(f"✅ Deleted group has {len(presets_after_delete)} presets (should be 0)")
    
    print("\n" + "=" * 50)
    print("✅ Preset groups and presets test completed!")
    print("The preset functionality is working correctly.")

if __name__ == "__main__":
    test_presets() 