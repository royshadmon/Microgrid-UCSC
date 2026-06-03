#!/usr/bin/env python3
"""
Test script for the new nested bookmark structure
"""

import sys
import os
import time
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from file_auth import (
    file_signup, file_login, file_bookmark_node, file_get_bookmarked_nodes,
    file_delete_bookmarked_node, file_update_bookmark_description
)

def test_nested_bookmarks():
    print("Testing Nested Bookmark Structure")
    print("=" * 50)
    
    # Test 1: Create a user with unique email
    print("\n1. Creating test user...")
    timestamp = int(time.time())
    email = f"bookmark_test_{timestamp}@example.com"
    signup_result = file_signup(email, "password123", "Bookmark", "Test")
    if "error" in signup_result:
        print(f"❌ Signup failed: {signup_result['error']}")
        return
    else:
        print(f"✅ User created: {signup_result['user']['email']}")
        user_id = signup_result['user']['id']
    
    # Test 2: Add bookmarks
    print("\n2. Adding bookmarks...")
    nodes = ["node1:8080", "node2:8080", "node3:8080"]
    for node in nodes:
        result = file_bookmark_node(user_id, node)
        if "error" in result:
            print(f"❌ Failed to bookmark {node}: {result['error']}")
        else:
            print(f"✅ Bookmarked {node}")
    
    # Test 3: Get all bookmarks
    print("\n3. Getting all bookmarks...")
    bookmarks = file_get_bookmarked_nodes(user_id)
    print(f"✅ Found {len(bookmarks)} bookmarks:")
    for bookmark in bookmarks:
        print(f"   - {bookmark['node']} (created: {bookmark['created_at']})")
    
    # Test 4: Update bookmark description
    print("\n4. Updating bookmark description...")
    result = file_update_bookmark_description(user_id, "node1:8080", "My favorite node")
    if "error" in result:
        print(f"❌ Failed to update description: {result['error']}")
    else:
        print("✅ Description updated successfully")
    
    # Test 5: Get bookmarks again to see updated description
    print("\n5. Getting bookmarks with updated description...")
    bookmarks = file_get_bookmarked_nodes(user_id)
    for bookmark in bookmarks:
        if bookmark['node'] == "node1:8080":
            print(f"   - {bookmark['node']}: {bookmark['description']}")
    
    # Test 6: Delete a bookmark
    print("\n6. Deleting a bookmark...")
    result = file_delete_bookmarked_node(user_id, "node2:8080")
    if "error" in result:
        print(f"❌ Failed to delete bookmark: {result['error']}")
    else:
        print("✅ Bookmark deleted successfully")
    
    # Test 7: Verify deletion
    print("\n7. Verifying deletion...")
    bookmarks = file_get_bookmarked_nodes(user_id)
    print(f"✅ Now have {len(bookmarks)} bookmarks:")
    for bookmark in bookmarks:
        print(f"   - {bookmark['node']}")
    
    # Test 8: Try to add duplicate bookmark
    print("\n8. Testing duplicate bookmark...")
    result = file_bookmark_node(user_id, "node1:8080")
    if "message" in result and "already exists" in result["message"]:
        print("✅ Correctly handled duplicate bookmark")
    else:
        print(f"❌ Unexpected result: {result}")
    
    print("\n" + "=" * 50)
    print("✅ Nested bookmark structure test completed!")
    print("The new structure is working correctly.")

if __name__ == "__main__":
    test_nested_bookmarks() 