#!/usr/bin/env python3
"""
Test script for the assignment policy system.
This script tests the automatic generation of assignment policies.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from . import assignment_manager
import json

def test_assignment_system():
    """Test the assignment policy system with a sample node."""
    
    # Test node (replace with your actual node)
    test_node = "192.168.86.21:32049"
    
    print("Testing Assignment Policy System")
    print("=" * 40)
    
    try:
        # Test 1: Get assignment summary
        print("\n1. Testing assignment summary...")
        summary = assignment_manager.get_assignment_summary(test_node)
        print(f"Summary: {json.dumps(summary, indent=2)}")
        
        # Test 2: Get security groups
        print("\n2. Testing security group retrieval...")
        import helpers
        security_groups = helpers.get_security_groups(test_node)
        print(f"Security groups: {security_groups}")
        
        # Test 3: Get members for a security group (if any exist)
        if security_groups:
            first_group = security_groups[0].get('security_group', {}).get('group_name', '')
            if first_group:
                print(f"\n3. Testing member retrieval for group '{first_group}'...")
                members = assignment_manager.get_all_members_in_security_group(test_node, first_group)
                print(f"Members in {first_group}: {members}")
                
                # Test 4: Get permissions for the security group
                print(f"\n4. Testing permission retrieval for group '{first_group}'...")
                permissions = assignment_manager.get_permissions_for_security_group(test_node, first_group)
                print(f"Permissions for {first_group}: {permissions}")
                
                # Test 5: Regenerate assignments for this security group
                if members and permissions:
                    print(f"\n5. Testing assignment regeneration for group '{first_group}'...")
                    assignment_manager.regenerate_assignments_for_security_group(test_node, first_group)
                    print("Assignment regeneration completed!")
        
        # Test 6: Get updated summary
        print("\n6. Getting updated assignment summary...")
        updated_summary = assignment_manager.get_assignment_summary(test_node)
        print(f"Updated summary: {json.dumps(updated_summary, indent=2)}")
        
        print("\n✅ All tests completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_assignment_system() 