# main.py
from fastapi import APIRouter, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Literal, Union, Dict, List
# from .models.user_policy import UserPolicyData, UserPolicy
# from .models.base_policy import BasePolicy
from .models.generic_policy import GenericPolicy
import json
import os
from . import helpers
from . import permissions
from . import assignment_manager
import secrets
import textwrap



security_router = APIRouter(prefix="/security", tags=["Security Policy Generator"])

# Get the directory where this file is located
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(_CURRENT_DIR, "templates")

# --- Unified Request Model --- #
class SubmitPolicyRequest(BaseModel):
    node: str
    policy_file: str  # Allow dynamic addition
    policy: Dict
    member_pubkey: str = None  # Current user's public key for signing
    signing_member_name: str = None  # Member to sign the policy with


class LoginRequest(BaseModel):
    node: str
    pubkey: str


class GetUserPermissionsRequest(BaseModel):
    node: str
    pubkey: str


class CheckPermissionRequest(BaseModel):
    node: str
    member_pubkey: str
    policy_type: str
    field_name: str


class GetAllowedFieldsRequest(BaseModel):
    node: str
    member_pubkey: str
    policy_type: str


class RegenerateAssignmentsRequest(BaseModel):
    node: str
    security_group: str = None  # If None, regenerate all


class AssignmentSummaryRequest(BaseModel):
    node: str


class CheckGuestRequest(BaseModel):
    pubkey: str


class AvailableSigningMembersRequest(BaseModel):
    node: str
    pubkey: str


@security_router.get("/")
def root():
    return {"message": "Policy GUI Backend is running", "status": "healthy"}

@security_router.get("/health")
def health():
    try:
        # Test external REST API connectivity
        import requests
        response = requests.get("https://httpbin.org/get", timeout=5)
        
        if response.status_code == 200:
            return {
                "status": "healthy", 
                "message": "Backend is running",
                "rest_api_test": {
                    "external_api": "working",
                    "status_code": response.status_code,
                    "response_time": f"{response.elapsed.total_seconds():.3f}s"
                }
            }
        else:
            return {
                "status": "unhealthy",
                "message": "External API test failed",
                "rest_api_test": {
                    "external_api": "failed",
                    "status_code": response.status_code
                }
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Backend has issues: {str(e)}",
            "rest_api_test": {
                "external_api": "failed",
                "error": str(e)
            }
        }




@security_router.get("/policy-types")
def list_policy_types():
    policy_list = []

    for filename in os.listdir(TEMPLATE_DIR):
        if filename.endswith("_policy.json"):
            try:
                with open(os.path.join(TEMPLATE_DIR, filename), "r") as f:
                    template = json.load(f)
                    policy_list.append(
                        {
                            "type": template.get("policy_file"),
                            "name": template.get("name", template.get("policy_file")),
                        }
                    )
            except Exception as e:
                continue  # skip broken files

    return {"types": policy_list}


@security_router.get("/policy-template/{policy_file}")
def get_policy_template(policy_file: str):
    file_path = os.path.join(TEMPLATE_DIR, f"{policy_file}.json")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Policy template not found")

    with open(file_path, "r") as f:
        return json.load(f)


# --- Dispatcher --- #
def policy_factory(policy_file: str, policy_data: Dict, node: str = None):
    template_path = os.path.join(TEMPLATE_DIR, f"{policy_file}.json")
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail="Template not found")

    with open(template_path, "r") as f:
        template = json.load(f)

    try:
        # print("Creating policy object for:", policy_file)
        print("Template on line 94:", template)
        print("Policy data on line 95:", policy_data)
        return GenericPolicy(template, policy_data, node)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@security_router.post("/submit")
def submit_policy(request: SubmitPolicyRequest):
    policy_obj = policy_factory(request.policy_file, request.policy, request.node)

    # print("Policy Object:", policy_obj)

    if not policy_obj.validate():
        raise HTTPException(status_code=422, detail="Policy validation failed")

    final_json = policy_obj.to_dict()

    # Determine signing member name
    signing_member_name = None
    
    # Special handling for member policy creation - new member signs themselves
    if request.policy_file == "member_policy":
        # For member policies, the new member will sign themselves after key creation
        # We don't need to specify a signing member as post_add_new_member handles this
        print("Member policy detected - new member will sign themselves after key creation")
    else:
        # For other policies, use the provided signing member
        if request.signing_member_name:
            signing_member_name = request.signing_member_name
            print(f"Using provided signing member: {signing_member_name}")
        else:
            # Fallback to current user's member name for backward compatibility
            if request.member_pubkey:
                try:
                    member_policy = permissions.get_member_policy(request.node, f'"{request.member_pubkey}"')
                    if member_policy and len(member_policy) > 0:
                        signing_member_name = member_policy[0].get("member", {}).get("name")
                        print(f"Using current user member name: {signing_member_name}")
                except Exception as e:
                    print(f"Warning: Could not get member policy for {request.member_pubkey}: {e}")
            
            # Final fallback to admin
            if not signing_member_name:
                signing_member_name = "admin"
                print(f"Using default member name: {signing_member_name}")
    
    # Add signing member name to the policy data for post-processing (only if provided)
    if signing_member_name:
        for policy_type, policy_data in final_json.items():
            if isinstance(policy_data, dict):
                policy_data["__signing_member_name__"] = signing_member_name

    # print("Final JSON Policy:", final_json)

    resp = helpers.make_policy(request.node, final_json)

    # # Auto-regenerate assignments if this policy affects security groups or members
    # try:
    #     if request.policy_file == "member_policy":
    #         # Extract security groups from member policy
    #         security_groups = request.policy.get("security_group", [])
    #         if isinstance(security_groups, str):
    #             security_groups = [security_groups]
            
    #         # Extract member pubkey if available
    #         member_pubkey = request.policy.get("public_key")
    #         if member_pubkey:
    #             assignment_manager.handle_member_policy_change(
    #                 request.node, member_pubkey, security_groups
    #             )
    #         else:
    #             # If no pubkey, regenerate all assignments for affected security groups
    #             for security_group in security_groups:
    #                 assignment_manager.handle_security_group_change(request.node, security_group)
        
    #     elif request.policy_file == "securitygroup_policy":
    #         # Extract security group name
    #         security_group = request.policy.get("group_name")
    #         if security_group:
    #             assignment_manager.handle_security_group_change(request.node, security_group)
        
    #     elif request.policy_file == "permissions_policy":
    #         # Permissions policy changes might affect multiple security groups
    #         # Get all security groups and regenerate their assignments
    #         security_groups_response = helpers.get_security_groups(request.node)
    #         for group_data in security_groups_response:
    #             if isinstance(group_data, dict) and 'security_group' in group_data:
    #                 group = group_data['security_group']
    #                 if 'group_name' in group:
    #                     assignment_manager.handle_security_group_change(request.node, group['group_name'])
    
    # except Exception as e:
    #     print(f"Warning: Failed to auto-regenerate assignments: {e}")
    #     # Don't fail the main request, just log the warning

    return resp

challenge_store = {}

@security_router.post("/login")
def authenticate_user(request: LoginRequest):
    """
    Authenticate user using node and pubkey, returning member policy if found.
    Supports guest login for admin access.
    """
    try:
        # Check for guest login
        if request.pubkey.lower() in ["guest", "admin", "test"]:
            # Create a guest member policy with admin privileges
            guest_member_policy = [{
                "member": {
                    "public_key": "guest_admin_key",
                    "name": "Guest Admin",
                    "type": "user",
                    "security_group": "admin"
                }
            }]
            
            print("Guest login detected - providing admin access")
            
            return {
                "success": True,
                "member_policy": guest_member_policy,
                "message": "Guest admin login successful",
                "is_guest": True
            }
        
        # Regular authentication flow
        # test see if node is running
        resp = helpers.make_request(request.node, "GET", "get status")
        print("Node Status:", resp)

        member_policy = permissions.get_member_policy(
            request.node, f'"{request.pubkey}"'
        )

        if len(member_policy) > 0:
            print("Member Policy:", member_policy)
            member_policy_pubkey = member_policy[0].get("member", {}).get("public_key")
            member_policy_name = member_policy[0].get("member", {}).get("name")

            challenge = secrets.token_urlsafe(32)

            helpers.make_request(request.node, "POST", f"message = {challenge}")
            resp = helpers.make_request(request.node, "GET", "get !message")
            print("Secret logged:", resp)

            command = f"login_pubkey = get public key where keys_file = {member_policy_name}"
            print("Command to get pubkey:", command)
            helpers.make_request(request.node, "POST", command)
            resp = helpers.make_request(request.node, "GET", "get !login_pubkey")
            print("Pubkey logged:", resp)
            print("Login Pubkey:", member_policy_pubkey)

            helpers.make_request(request.node, "POST", "id encrypt !message !login_pubkey")
            encrypted = helpers.make_request(request.node, "GET", "get !message")
            print("Encrypted Secret logged:", encrypted)

            challenge_store[request.pubkey] = challenge

            command = f"login_privkey = get private key where keys_file = {member_policy_name}"
            print("Command to get privkey:", command)
            helpers.make_request(request.node, "POST", command)
            resp = helpers.make_request(request.node, "GET", "get !login_privkey")
            print("Privkey logged:", resp)

            helpers.make_request(request.node, "POST", "message = id decrypt !message where key = !login_privkey and password = 123")
            decrypted = helpers.make_request(request.node, "GET", "get !message")
            print("Decrypted Secret logged:", decrypted)

        return {
            "success": True,
            "member_policy": member_policy,
            "message": "Authentication successful",
            "is_guest": False
        }
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")


# @security_router.post("/auth/request-challenge"):
# def request_challenge(request: LoginRequest):
#     try:
#         member_policy = permissions.get_member_policy(request.node, f'"{request.pubkey}"')

#         return {
#             "success": True,
#             "member_policy": member_policy,
#             "message": "Authentication successful"
#         }
#     except ValueError as e:
#         raise HTTPException(status_code=401, detail=str(e))
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")

@security_router.get("/custom-types")
def get_custom_types():
    """
    Endpoint to get all custom types (policy types) available in the system.
    This can be used by the frontend to populate type selectors, etc.
    """
    try:
        # Assuming policy templates are stored as files in TEMPLATE_DIR
        types = ["node", "table", "security_group"]
        return {"custom_types": types}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get custom types: {str(e)}")


@security_router.post("/type-options")
def get_type_options(node: str = Body(...), type: str = Body(...)):
    """
    Generic endpoint to get options for a given type (e.g., node, table, etc.) on a node.
    Extend this as new types are needed.
    """
    try:
        if type == "node":
            options = helpers.get_node_options(node)
            return {"options": options}
        elif type == "table":
            # Placeholder: replace with actual logic as needed
            options = helpers.get_table_options(node)
            # options = ["table1", "table2", "table3"]
            return {"options": options}
        elif type == "security_group":
            # Placeholder: replace with actual logic as needed
            resp = helpers.get_security_groups(node)
            print("Security Groups Response:", resp)
            options = resp
            return {"options": options}
        else:
            return {"options": []}
    except Exception as e:
        print(f"Failed to get options for type '{type}': {str(e)}")
        return {"options": []}
        # raise HTTPException(status_code=500, detail=f"Failed to get options for type '{type}': {str(e)}")


@security_router.get("/permissions/{node}")
def get_permissions(node: str):
    # Fetch the on‑chain permissions policy from the node
    resp = helpers.get_permissions(node)
    # print("Permissions Response:", resp)
    # Return the permissions list directly
    return resp


@security_router.post("/user-permissions")
def get_user_permissions(node: str = Body(...), pubkey: str = Body(...)):
    """
    After login, aggregate all permissions for the user based on their role.
    Supports guest users with admin privileges.
    """

    print("Aggregating permissions for user:", pubkey, "on node:", node)

    try:
        # Check for guest users
        if pubkey.lower() in ["guest", "admin", "test"] or pubkey == "guest_admin_key":
            print("Guest user detected - providing admin permissions")
            return {
                "security_group": ["admin"],
                "allowed_policy_types": ["*"],
                "allowed_policy_fields": {},
                "is_guest": True
            }

        # 1. Get member policy
        member_policy = permissions.get_member_policy(node, f'"{pubkey}"')
        # if not isinstance(member_policy[0], dict):
        #     raise HTTPException(status_code=404, detail="Member policy not found or invalid format")
        member_policy = (
            member_policy[0].get("member")
            if isinstance(member_policy, list)
            else member_policy.get("member")
        )
        security_group_names = member_policy.get("security_group")
        if isinstance(security_group_names, str):
            security_group_names = [security_group_names]
        # if not role:
        #     raise HTTPException(status_code=404, detail="Role not found in member policy")

        # 2. Get all security_group policies for this role
        # (Assume helpers.make_request returns a list of policies if multiple match)

        if "admin" in security_group_names:
            # Admins have all permissions, return empty allowed_policy_fields
            return {
                "security_group": security_group_names,
                "allowed_policy_types": ["*"],
                "allowed_policy_fields": {},
                "is_guest": False
            }

        all_security_group_policies = []
        for group_name in security_group_names:
            group_policies = helpers.make_request(
                node,
                "GET",
                f"blockchain get security_group where group_name = {group_name}",
            )
            if group_policies:
                all_security_group_policies.extend(group_policies)

        if not all_security_group_policies:
            raise HTTPException(
                status_code=404, detail="No security_group policies found for these roles"
            )

        print("Role Permissions Policies:", all_security_group_policies)

        # 3. Aggregate all permission names
        permission_names = set()
        for policy in all_security_group_policies:
            policy_data = policy.get("security_group", {})
            perms = policy_data.get("permissions", [])
            permission_names.update(perms)

        print("Aggregated Permission Names:", permission_names)

        # 4. For each permission name, get the permissions_policy
        permissions_policies = []
        for perm_name in permission_names:
            perm_policy = permissions.get_permissions_policy(node, perm_name)
            if perm_policy:
                permissions_policies.append(perm_policy)

        # 5. For each permissions_policy, extract field_permissions, and aggregate like keys

        # def aggregate_field_permissions(nested):
        #     aggregated = {}
        #     for sublist in nested:
        #         for entry in sublist:
        #             fp = entry.get("permissions", {}).get("field_permissions", {})
        #             for category, fields in fp.items():
        #                 aggregated.setdefault(category, {}).update(fields)
        #     return aggregated

        # The function aggregates all field_permissions, ensuring that if any policy marks a field as True, the result is True.
        def aggregate_field_permissions(nested):
            aggregated = {}
            for sublist in nested:
                for entry in sublist:
                    fp = entry.get("permissions", {}).get("field_permissions", {})
                    for category, fields in fp.items():
                        if category not in aggregated:
                            aggregated[category] = {}
                        for field, value in fields.items():
                            # If any value is True, keep it True
                            if field in aggregated[category]:
                                aggregated[category][field] = aggregated[category][field] or value
                            else:
                                aggregated[category][field] = value
            return aggregated

        allowed_policy_fields = aggregate_field_permissions(permissions_policies)

        # Remove all subkeys (fields) with value False from allowed_policy_fields
        for category in list(allowed_policy_fields.keys()):
            fields = allowed_policy_fields[category]
            # Remove fields with value False
            filtered_fields = {k: v for k, v in fields.items() if v}
            if filtered_fields:
                allowed_policy_fields[category] = filtered_fields
            else:
                # If no fields remain, remove the category entirely
                del allowed_policy_fields[category]

        print("Allowed Policy fields: ", allowed_policy_fields)

        allowed_policy_types = list(allowed_policy_fields.keys())

        return {
            "security_group": security_group_names, # str: name of the group
            "allowed_policy_types": allowed_policy_types, # list of allowed policy types
            "allowed_policy_fields": allowed_policy_fields, # dict of type: {field: t/f}
            "is_guest": False
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to aggregate user permissions: {str(e)}"
        )


@security_router.post("/check-field-permission")
def check_field_permission(request: CheckPermissionRequest):
    """
    Check if a member has permission to access a specific field in a policy type.
    """
    try:
        has_permission = permissions.check_field_permission(
            request.node, request.member_pubkey, request.policy_type, request.field_name
        )
        return {
            "has_permission": has_permission,
            "field": request.field_name,
            "policy_type": request.policy_type,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Permission check failed: {str(e)}"
        )


@security_router.post("/get-allowed-fields")
def get_allowed_fields(request: GetAllowedFieldsRequest):
    """
    Get all fields that a member is allowed to access for a specific policy type.
    """
    try:
        allowed_fields = permissions.get_allowed_fields(
            request.node, request.member_pubkey, request.policy_type
        )
        return {"allowed_fields": allowed_fields, "policy_type": request.policy_type}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get allowed fields: {str(e)}"
        )


@security_router.post("/validate-policy-access")
def validate_policy_access(request: SubmitPolicyRequest):
    """
    Validate and filter policy data based on member permissions.
    This endpoint requires the member_pubkey to be included in the policy data.
    """
    try:
        # Extract member_pubkey from policy data
        member_pubkey = request.policy.get("member_pubkey")
        if not member_pubkey or not isinstance(member_pubkey, str):
            raise HTTPException(
                status_code=400, detail="member_pubkey is required in policy data"
            )

        # Remove member_pubkey from policy data before validation
        policy_data = {k: v for k, v in request.policy.items() if k != "member_pubkey"}

        filtered_data = permissions.validate_policy_access(
            request.node, member_pubkey, request.policy_file, policy_data
        )

        return {
            "filtered_policy": filtered_data,
            "policy_type": request.policy_file,
            "original_fields": list(policy_data.keys()),
            "allowed_fields": list(filtered_data.keys()),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Policy validation failed: {str(e)}"
        )


# --- Assignment Policy Management Endpoints --- #

@security_router.post("/regenerate-assignments")
def regenerate_assignments(request: RegenerateAssignmentsRequest):
    """
    Regenerate assignment policies for a specific security group or all security groups.
    """
    try:
        if request.security_group:
            assignment_manager.regenerate_assignments_for_security_group(
                request.node, request.security_group
            )
            return {
                "success": True,
                "message": f"Regenerated assignments for security group: {request.security_group}"
            }
        else:
            assignment_manager.regenerate_all_assignments(request.node)
            return {
                "success": True,
                "message": "Regenerated all assignment policies"
            }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to regenerate assignments: {str(e)}"
        )


@security_router.post("/assignment-summary")
def get_assignment_summary(request: AssignmentSummaryRequest):
    """
    Get a summary of all assignment policies for monitoring and debugging.
    """
    try:
        summary = assignment_manager.get_assignment_summary(request.node)
        return summary
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get assignment summary: {str(e)}"
        )


@security_router.post("/handle-member-change")
def handle_member_policy_change_endpoint(node: str = Body(...), member_pubkey: str = Body(...), new_security_groups: List[str] = Body(...)):
    """
    Handle changes to member policies by updating relevant assignment policies.
    """
    try:
        assignment_manager.handle_member_policy_change(
            node, member_pubkey, new_security_groups
        )
        return {
            "success": True,
            "message": f"Handled member policy change for {member_pubkey}"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to handle member policy change: {str(e)}"
        )


@security_router.post("/handle-security-group-change")
def handle_security_group_change_endpoint(node: str = Body(...), security_group: str = Body(...)):
    """
    Handle changes to security group policies by updating relevant assignment policies.
    """
    try:
        assignment_manager.handle_security_group_change(node, security_group)
        return {
            "success": True,
            "message": f"Handled security group change for {security_group}"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to handle security group change: {str(e)}"
        )


@security_router.post("/check-guest")
def check_guest_user(request: CheckGuestRequest):
    """
    Check if a user is a guest user.
    """
    try:
        is_guest = request.pubkey.lower() in ["guest", "admin", "test"] or request.pubkey == "guest_admin_key"
        return {
            "is_guest": is_guest,
            "pubkey": request.pubkey
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to check guest status: {str(e)}"
        )


@security_router.get("/debug-members/{node}")
def debug_members(node: str):
    """
    Debug endpoint to check what members are available on the blockchain.
    """
    try:
        command = "blockchain get member"
        response = helpers.make_request(node, "GET", command)
        return {
            "node": node,
            "command": command,
            "response": response,
            "count": len(response) if response else 0
        }
    except Exception as e:
        return {
            "node": node,
            "error": str(e)
        }

@security_router.post("/available-signing-members")
def get_available_signing_members(request: AvailableSigningMembersRequest):
    """
    Get list of members that the current user can sign policies with.
    """
    try:
        # Check for guest users - they can sign with admin
        # if request.pubkey.lower() in ["guest", "admin", "test"] or request.pubkey == "guest_admin_key":
        #     return {
        #         "members": [
        #             {
        #                 "name": "admin",
        #                 "type": "admin",
        #                 "description": "Administrator account with full privileges"
        #             }
        #         ]
        #     }

        # Get all member policies from the blockchain
        command = "blockchain get member"
        # print(f"[DEBUG] Making blockchain query: {command} on node: {request.node}")
        response = helpers.make_request(request.node, "GET", command)
        
        # print(f"[DEBUG] Raw blockchain response type: {type(response)}")
        # print(f"[DEBUG] Raw blockchain response: {response}")
        
        if not response:
            # print("[DEBUG] No members found in blockchain response")
            return {"members": []}
        
        if not isinstance(response, list):
            # print(f"[DEBUG] Response is not a list, it's: {type(response)}")
            return {"members": []}
        
        available_members = []
        
        for member_data in response:
            if isinstance(member_data, dict) and 'member' in member_data:
                member = member_data['member']
                member_name = member.get('name')
                member_type = member.get('type', 'user')
                public_key = member.get('public_key')
                
                # print(f"[DEBUG] Processing member: {member_name} (type: {member_type}, pubkey: {public_key})")
                
                if member_name and public_key:
                    # For now, allow signing with any member
                    # TODO: Add permission checking based on user's security group
                    available_members.append({
                        "name": member_name,
                        "type": member_type,
                        "description": f"{member_type.title()} member",
                        "public_key": public_key
                    })
        
        # print(f"[DEBUG] Final available members list: {available_members}")
        return {"members": available_members}
        
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get available signing members: {str(e)}"
        )
