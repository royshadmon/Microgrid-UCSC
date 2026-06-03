from . import helpers
import json
from typing import Dict, List, Any, Optional


def get_member_policy(node: str, pubkey: str):
    """
    Fetch the member policy for a given public key from the specified node.
    """
    command = f"blockchain get member where public_key = {pubkey}"
    print(f"Fetching Member Policy: {command}")
    response = helpers.make_request(node, "GET", command)
    
    if not response:
        raise ValueError(f"No member policy found for pubkey: {pubkey}")
    
    return response


def get_permissions_policy(node: str, permission_name: str):
    """
    Fetch a specific permissions policy from the node.
    """
    command = f"blockchain get permissions where name = {permission_name}"
    print(f"Fetching Permissions Policy: {command}")
    response = helpers.make_request(node, "GET", command)
    
    if not response:
        raise ValueError(f"No permissions policy found for: {permission_name}")
    
    return response


def get_role_permissions(node: str, member_role: str):
    """
    Fetch role permissions mapping for a specific member role.
    """
    command = f"blockchain get role_perms where member_role = {member_role}"
    print(f"Fetching Role Permissions: {command}")
    response = helpers.make_request(node, "GET", command)
    
    if not response:
        raise ValueError(f"No role permissions found for role: {member_role}")
    
    return response


def check_field_permission(node: str, member_pubkey: str, policy_type: str, field_name: str) -> bool:
    """
    Check if a member has permission to access a specific field in a policy type.
    
    Args:
        node: The node address
        member_pubkey: The member's public key
        policy_type: The type of policy (config, security, user, member)
        field_name: The name of the field to check
    
    Returns:
        bool: True if the member has permission, False otherwise
    """
    try:
        # Get member policy to find the role
        member_policy = get_member_policy(node, member_pubkey)
        if not isinstance(member_policy, dict):
            print(f"Invalid member policy format for pubkey: {member_pubkey}")
            return False
            
        member_role = member_policy.get('role')
        
        if not member_role:
            print(f"No role found in member policy for pubkey: {member_pubkey}")
            return False
        
        # Get role permissions to find associated permissions
        role_perms = get_role_permissions(node, member_role)
        if not isinstance(role_perms, dict):
            print(f"Invalid role permissions format for role: {member_role}")
            return False
            
        permission_names = role_perms.get('permissions', [])
        
        if not permission_names:
            print(f"No permissions found for role: {member_role}")
            return False
        
        # Check each permission for field access
        for perm_name in permission_names:
            try:
                perm_policy = get_permissions_policy(node, perm_name)
                if not isinstance(perm_policy, dict):
                    print(f"Invalid permissions policy format for: {perm_name}")
                    continue
                    
                field_perms = perm_policy.get('field_permissions', {})
                
                # Check if policy type exists in field permissions
                if policy_type in field_perms:
                    policy_fields = field_perms[policy_type]
                    
                    # Check if field exists and is allowed
                    if field_name in policy_fields:
                        return policy_fields[field_name] == True
                    
                    # If field not explicitly defined, deny access
                    return False
                    
            except ValueError as e:
                print(f"Error fetching permission {perm_name}: {e}")
                continue
        
        # If no permissions allow access, deny
        return False
        
    except Exception as e:
        print(f"Error checking field permission: {e}")
        return False


def get_allowed_fields(node: str, member_pubkey: str, policy_type: str) -> List[str]:
    """
    Get all fields that a member is allowed to access for a specific policy type.
    
    Args:
        node: The node address
        member_pubkey: The member's public key
        policy_type: The type of policy (config, security, user, member)
    
    Returns:
        List[str]: List of field names the member can access
    """
    try:
        # Get member policy to find the role
        member_policy = get_member_policy(node, member_pubkey)
        if not isinstance(member_policy, dict):
            print(f"Invalid member policy format for pubkey: {member_pubkey}")
            return []
            
        member_role = member_policy.get('role')
        
        if not member_role:
            return []
        
        # Get role permissions to find associated permissions
        role_perms = get_role_permissions(node, member_role)
        if not isinstance(role_perms, dict):
            print(f"Invalid role permissions format for role: {member_role}")
            return []
            
        permission_names = role_perms.get('permissions', [])
        
        allowed_fields = set()
        
        # Check each permission for field access
        for perm_name in permission_names:
            try:
                perm_policy = get_permissions_policy(node, perm_name)
                if not isinstance(perm_policy, dict):
                    print(f"Invalid permissions policy format for: {perm_name}")
                    continue
                    
                field_perms = perm_policy.get('field_permissions', {})
                
                # Check if policy type exists in field permissions
                if policy_type in field_perms:
                    policy_fields = field_perms[policy_type]
                    
                    # Add fields that are allowed (True)
                    for field_name, is_allowed in policy_fields.items():
                        if is_allowed == True:
                            allowed_fields.add(field_name)
                    
            except ValueError as e:
                print(f"Error fetching permission {perm_name}: {e}")
                continue
        
        return list(allowed_fields)
        
    except Exception as e:
        print(f"Error getting allowed fields: {e}")
        return []


def validate_policy_access(node: str, member_pubkey: str, policy_type: str, policy_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and filter policy data based on member permissions.
    
    Args:
        node: The node address
        member_pubkey: The member's public key
        policy_type: The type of policy being submitted
        policy_data: The policy data to validate
    
    Returns:
        Dict[str, Any]: Filtered policy data with only allowed fields
    """
    allowed_fields = get_allowed_fields(node, member_pubkey, policy_type)
    
    if not allowed_fields:
        raise ValueError(f"No field permissions found for policy type: {policy_type}")
    
    # Filter policy data to only include allowed fields
    filtered_data = {}
    for field_name, field_value in policy_data.items():
        if field_name in allowed_fields:
            filtered_data[field_name] = field_value
        else:
            print(f"Field '{field_name}' not allowed for policy type '{policy_type}'")
    
    return filtered_data

