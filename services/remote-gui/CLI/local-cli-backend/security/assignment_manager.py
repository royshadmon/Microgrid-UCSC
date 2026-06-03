from . import helpers
import json
from typing import Dict, List, Any, Optional
from .models.generic_policy import GenericPolicy


def get_all_members_in_security_group(node: str, security_group: str) -> List[str]:
    """
    Get all member public keys that belong to a specific security group.
    """
    try:
        command = f"blockchain get member where security_group = {security_group}"
        response = helpers.make_request(node, "GET", command)
        
        if not response:
            return []
        
        member_pubkeys = []
        for member_data in response:
            if isinstance(member_data, dict) and 'member' in member_data:
                member = member_data['member']
                if 'public_key' in member:
                    member_pubkeys.append(member['public_key'])
        
        return member_pubkeys
    except Exception as e:
        print(f"Error getting members for security group {security_group}: {e}")
        return []


def get_permissions_for_security_group(node: str, security_group: str) -> List[str]:
    """
    Get all permission names associated with a security group.
    """
    try:
        command = f"blockchain get security_group where group_name = {security_group}"
        response = helpers.make_request(node, "GET", command)
        
        if not response:
            return []
        
        permission_names = []
        for group_data in response:
            if isinstance(group_data, dict) and 'security_group' in group_data:
                group = group_data['security_group']
                if 'permissions' in group:
                    permissions = group['permissions']
                    if isinstance(permissions, list):
                        permission_names.extend(permissions)
                    elif isinstance(permissions, str):
                        permission_names.append(permissions)
        
        return list(set(permission_names))  # Remove duplicates
    except Exception as e:
        print(f"Error getting permissions for security group {security_group}: {e}")
        return []


def get_policy_id_by_name(node: str, policy_type: str, policy_name: str) -> str:
    """
    Get the policy ID by querying the blockchain with the policy name.
    """
    try:
        command = f"blockchain get {policy_type} where name = {policy_name}"
        response = helpers.make_request(node, "GET", command)
        
        if not response:
            raise ValueError(f"No {policy_type} policy found with name: {policy_name}")
        
        # The response should contain the policy with its ID
        for policy_data in response:
            if isinstance(policy_data, dict) and policy_type in policy_data:
                policy = policy_data[policy_type]
                if 'id' in policy:
                    return policy['id']
                elif 'policy_id' in policy:
                    return policy['policy_id']
        
        raise ValueError(f"No ID found in {policy_type} policy with name: {policy_name}")
        
    except Exception as e:
        print(f"Error getting policy ID for {policy_type} '{policy_name}': {e}")
        raise


def get_existing_assignments(node: str, security_group: str = None) -> List[Dict]:
    """
    Get existing assignment policies, optionally filtered by security group.
    """
    try:
        command = "blockchain get assignment"
        if security_group:
            command += f" where security_group = {security_group}"
        
        response = helpers.make_request(node, "GET", command)
        
        if not response:
            return []
        
        return response
    except Exception as e:
        print(f"Error getting existing assignments: {e}")
        return []


def delete_assignment_policy(node: str, assignment_id: str):
    """
    Delete an existing assignment policy.
    """
    try:
        master_node_command = 'mnode = blockchain get master bring.ip_port'
        print(f"Fetching Master Node: {master_node_command}")
        helpers.make_request(node, "POST", master_node_command)

        command = f"blockchain delete assignment where id = {assignment_id} and master = !mnode"
        helpers.make_request(node, "POST", command)
        print(f"Deleted assignment policy: {assignment_id}")
    except Exception as e:
        print(f"Error deleting assignment policy {assignment_id}: {e}")


def create_assignment_policy(node: str, permissions_name: str, member_pubkeys: List[str], 
                           security_group: str = None, description: str = None) -> Dict:
    """
    Create a new assignment policy.
    """
    try:
        # Get the actual permissions policy ID from the name
        permissions_id = get_policy_id_by_name(node, "permissions", permissions_name)
        
        # Load assignment policy template
        template_path = "templates/assignment_policy.json"
        with open(template_path, "r") as f:
            template = json.load(f)
        
        # Prepare assignment data
        assignment_data = {
            "permissions": permissions_id,
            "members": member_pubkeys,
            "security_group": security_group or "",
            "description": description or f"Auto-generated assignment for {permissions_name}"
        }
        
        # Create assignment policy object
        assignment_policy = GenericPolicy(template, assignment_data, node)
        
        if not assignment_policy.validate():
            raise ValueError("Assignment policy validation failed")
        
        # Submit the assignment policy
        final_json = assignment_policy.to_dict()
        response = helpers.make_policy(node, final_json)
        
        print(f"Created assignment policy for permissions {permissions_name} (ID: {permissions_id}) with {len(member_pubkeys)} members")
        return response
        
    except Exception as e:
        print(f"Error creating assignment policy: {e}")
        raise


def regenerate_assignments_for_security_group(node: str, security_group: str):
    """
    Regenerate all assignment policies for a specific security group.
    This should be called when security group policies or member policies change.
    """
    try:
        print(f"Regenerating assignments for security group: {security_group}")
        
        # Get all members in this security group
        member_pubkeys = get_all_members_in_security_group(node, security_group)
        if not member_pubkeys:
            print(f"No members found for security group: {security_group}")
            return
        
        # Get all permissions for this security group
        permission_names = get_permissions_for_security_group(node, security_group)
        if not permission_names:
            print(f"No permissions found for security group: {security_group}")
            return
        
        # Delete existing assignments for this security group
        existing_assignments = get_existing_assignments(node, security_group)
        for assignment in existing_assignments:
            if isinstance(assignment, dict) and 'assignment' in assignment:
                assignment_id = assignment['assignment'].get('id')
                if assignment_id:
                    delete_assignment_policy(node, assignment_id)
        
        # Create new assignments for each permission
        for permission_name in permission_names:
            try:
                create_assignment_policy(
                    node=node,
                    permissions_name=permission_name,
                    member_pubkeys=member_pubkeys,
                    security_group=security_group,
                    description=f"Auto-generated assignment for {security_group} group"
                )
            except Exception as e:
                print(f"Error creating assignment for permission {permission_name}: {e}")
        
        print(f"Successfully regenerated assignments for security group: {security_group}")
        
    except Exception as e:
        print(f"Error regenerating assignments for security group {security_group}: {e}")
        raise


def regenerate_all_assignments(node: str):
    """
    Regenerate all assignment policies for all security groups.
    This is useful for system-wide updates or migrations.
    """
    try:
        print("Regenerating all assignment policies...")
        
        # Get all security groups
        security_groups_response = helpers.get_security_groups(node)
        security_group_names = []
        
        for group_data in security_groups_response:
            if isinstance(group_data, dict) and 'security_group' in group_data:
                group = group_data['security_group']
                if 'group_name' in group:
                    security_group_names.append(group['group_name'])
        
        # Regenerate assignments for each security group
        for security_group in security_group_names:
            try:
                regenerate_assignments_for_security_group(node, security_group)
            except Exception as e:
                print(f"Error regenerating assignments for {security_group}: {e}")
        
        print("Completed regeneration of all assignment policies")
        
    except Exception as e:
        print(f"Error regenerating all assignments: {e}")
        raise


def handle_member_policy_change(node: str, member_pubkey: str, new_security_groups: List[str]):
    """
    Handle changes to member policies by updating relevant assignment policies.
    This should be called when a member's security group assignment changes.
    """
    try:
        print(f"Handling member policy change for {member_pubkey}")
        
        # Get all security groups that have members
        all_security_groups = set()
        
        # Get existing assignments to find all security groups
        existing_assignments = get_existing_assignments(node)
        for assignment in existing_assignments:
            if isinstance(assignment, dict) and 'assignment' in assignment:
                assignment_data = assignment['assignment']
                if 'security_group' in assignment_data:
                    all_security_groups.add(assignment_data['security_group'])
        
        # Add the new security groups
        all_security_groups.update(new_security_groups)
        
        # Regenerate assignments for all affected security groups
        for security_group in all_security_groups:
            try:
                regenerate_assignments_for_security_group(node, security_group)
            except Exception as e:
                print(f"Error regenerating assignments for {security_group}: {e}")
        
        print(f"Completed handling member policy change for {member_pubkey}")
        
    except Exception as e:
        print(f"Error handling member policy change: {e}")
        raise


def handle_security_group_change(node: str, security_group: str):
    """
    Handle changes to security group policies by updating relevant assignment policies.
    This should be called when a security group's permissions change.
    """
    try:
        print(f"Handling security group change for {security_group}")
        regenerate_assignments_for_security_group(node, security_group)
        print(f"Completed handling security group change for {security_group}")
    except Exception as e:
        print(f"Error handling security group change: {e}")
        raise


def get_assignment_summary(node: str) -> Dict[str, Any]:
    """
    Get a summary of all assignment policies for monitoring and debugging.
    """
    try:
        assignments = get_existing_assignments(node)
        
        summary = {
            "total_assignments": len(assignments),
            "assignments_by_security_group": {},
            "assignments_by_permission": {}
        }
        
        for assignment in assignments:
            if isinstance(assignment, dict) and 'assignment' in assignment:
                assignment_data = assignment['assignment']
                
                security_group = assignment_data.get('security_group', 'unknown')
                permissions_id = assignment_data.get('permissions', 'unknown')
                member_count = len(assignment_data.get('members', []))
                
                # Count by security group
                if security_group not in summary["assignments_by_security_group"]:
                    summary["assignments_by_security_group"][security_group] = 0
                summary["assignments_by_security_group"][security_group] += 1
                
                # Count by permission
                if permissions_id not in summary["assignments_by_permission"]:
                    summary["assignments_by_permission"][permissions_id] = {
                        "count": 0,
                        "total_members": 0
                    }
                summary["assignments_by_permission"][permissions_id]["count"] += 1
                summary["assignments_by_permission"][permissions_id]["total_members"] += member_count
        
        return summary
        
    except Exception as e:
        print(f"Error getting assignment summary: {e}")
        return {"error": str(e)} 