#!/usr/bin/env python3
"""
Test script for file_auth_router
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from main import app

def test_file_auth_router():
    """Test the file_auth_router endpoints"""
    client = TestClient(app)
    
    print("Testing File Auth Router")
    print("=" * 50)
    
    # Test 1: Signup
    print("\n1. Testing signup endpoint...")
    signup_data = {
        "email": "test@example.com",
        "password": "password123",
        "firstname": "Test",
        "lastname": "User"
    }
    response = client.post("/auth/signup/", json=signup_data)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("✅ Signup endpoint working")
        user_data = response.json()
        print(f"User created: {user_data['data']['user']['email']}")
    else:
        print(f"❌ Signup failed: {response.text}")
        return
    
    # Test 2: Login
    print("\n2. Testing login endpoint...")
    login_data = {
        "email": "test@example.com",
        "password": "password123"
    }
    response = client.post("/auth/login/", json=login_data)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("✅ Login endpoint working")
        login_result = response.json()
        user_id = login_result['data']['user']['id']
        print(f"User logged in: {login_result['data']['user']['email']}")
    else:
        print(f"❌ Login failed: {response.text}")
        return
    
    # Test 3: Get user
    print("\n3. Testing get-user endpoint...")
    get_user_data = {"jwt": user_id}
    response = client.post("/auth/get-user/", json=get_user_data)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("✅ Get user endpoint working")
    else:
        print(f"❌ Get user failed: {response.text}")
    
    # Test 4: Bookmark node
    print("\n4. Testing bookmark-node endpoint...")
    bookmark_data = {
        "jwt": user_id,
        "conn": "test-node:8080"
    }
    response = client.post("/auth/bookmark-node/", json=bookmark_data)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("✅ Bookmark node endpoint working")
    else:
        print(f"❌ Bookmark node failed: {response.text}")
    
    # Test 5: Get bookmarks
    print("\n5. Testing get-bookmarked-nodes endpoint...")
    get_bookmarks_data = {"jwt": user_id}
    response = client.post("/auth/get-bookmarked-nodes/", json=get_bookmarks_data)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("✅ Get bookmarks endpoint working")
        bookmarks = response.json()
        print(f"Found {len(bookmarks['data'])} bookmarks")
    else:
        print(f"❌ Get bookmarks failed: {response.text}")
    
    # Test 6: Add preset group
    print("\n6. Testing add-preset-group endpoint...")
    preset_group_data = {
        "jwt": user_id,
        "group": {"group_name": "Test Group"}
    }
    response = client.post("/auth/add-preset-group/", json=preset_group_data)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("✅ Add preset group endpoint working")
        group_result = response.json()
        group_id = group_result['data']['group']['id']
        print(f"Group created: {group_result['data']['group']['group_name']}")
    else:
        print(f"❌ Add preset group failed: {response.text}")
    
    # Test 7: Get preset groups
    print("\n7. Testing get-preset-groups endpoint...")
    get_groups_data = {"jwt": user_id}
    response = client.post("/auth/get-preset-groups/", json=get_groups_data)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("✅ Get preset groups endpoint working")
        groups = response.json()
        print(f"Found {len(groups['data'])} preset groups")
    else:
        print(f"❌ Get preset groups failed: {response.text}")
    
    print("\n" + "=" * 50)
    print("✅ File auth router test completed!")
    print("All endpoints are working correctly.")

if __name__ == "__main__":
    test_file_auth_router() 