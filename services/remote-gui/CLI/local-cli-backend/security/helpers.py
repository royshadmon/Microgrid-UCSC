import requests
import json
from . import parsers
import anylog_api.anylog_connector as anylog_connector
from typing import Dict, Any
import hashlib
import time

def get_node_options(node: str):
    response = make_request(node, "GET", "test network")
    response = parsers.parse_table(response)
    node_names = [
        node_info['Node Name']
        for node_info in response
        if 'Node Name' in node_info and node_info.get('Status', '') == '+'
    ]
    return node_names

def get_table_options(node: str):
    response = make_request(node, "GET", "blockchain get table")
    table_names = []
    for obj in response:
        group = obj.get('table')
        if group and 'name' in group:
            table_names.append(group['name'])
    result = list(set(table_names))
    result.insert(0, "*")
    return result

def get_security_groups(node: str):
    response = make_request(node, "GET", "blockchain get security_group")
    # security_groups = []
    # for obj in response:
    #     group = obj.get('security_group')
    #     if group and 'group_name' in group:
    #         security_groups.append(group['group_name'])
    # security_groups = list(set(security_groups))

    # add admin to the list
    response.append({"security_group": {"group_name": "admin"}})
    return response

def get_permissions(node: str):
    response = make_request(node, "GET", "blockchain get permissions")

    print("GETTING Permissions Response:", response)
    permissions = []
    for obj in response:
        permission = obj.get('permissions')
        if permission:
            # Try to get the ID first, fallback to name if ID doesn't exist
            permission_id = permission.get('id') or permission.get('name')
            permission_name = permission.get('name', 'Unknown')
            if permission_id:
                permissions.append({
                    "id": permission_id,
                    "name": permission_name,
                    "type": "permission",
                    "description": f"Permission policy: {permission_name}"
                })
                print(f"Added permission: {permission_name} (ID: {permission_id})")
    
    print(f"Final permissions list: {permissions}")
    return permissions



def make_policy(conn:str, policy: Dict):

    # Extract policy name and data from the input dictionary
    if len(policy) != 1:
        raise ValueError("Policy dictionary must have exactly one key (the policy name).")
    policy_name, policy_data = next(iter(policy.items()))

    # Create a simple object to mimic attribute access (policy.name, policy.data)
    class PolicyObj:
        def __init__(self, name, data):
            self.name = name
            self.data = data

    policy = PolicyObj(policy_name, policy_data)

    post_process_key = policy.data.pop("__post_process__", None)

    print(policy.name, policy.data)

    # Policy variable
    policy_var_command = 'new_policy = ""'
    print(f"Creating Policy Variable: {policy_var_command}")
    policy_var_response = make_request(conn, "POST", policy_var_command)
    print(f"Policy Variable Response: {policy_var_response}")

    policy_name_command = f'set policy new_policy [{policy_name}] = {{}}'
    print(f"Setting Policy Name: {policy_name_command}")
    make_request(conn, "POST", policy_name_command)
    print(f"Policy Name Set: {policy_name_command}")


    # Configure the policy with its data
    for key, value in policy.data.items():
        command = f'set policy new_policy [{policy.name}][{key}] = {value}'
        print(f"Setting Policy Config: {command}")
        make_request(conn, "POST", command)


    # # Construct the policy command
    # policy_command = f'{policy.name} = create policy {policy.name} where '
    # key_value_pairs = [f"{k} = {v}" for k, v in policy.data.items()]
    # policy_command += " and ".join(key_value_pairs)

    # # Submit the policy (POST)
    # print(f"Submitting Policy: {policy_command}")
    # make_request(conn, "POST", policy_command)

    # Retrieve the created policy (GET)
    get_policy_command = "get !new_policy"
    print(f"Fetching Policy: {get_policy_command}")
    policy_response = make_request(conn, "GET", get_policy_command)
    print(f"Policy Response: {policy_response}")


    # Post-process the policy if needed
    if post_process_key:
        try:
            run_post_process(post_process_key, policy, conn)
        except Exception as e:
            raise RuntimeError(f"Post-processing failed: {e}")


    # Get the master node IP/Port (POST)
    master_node_command = 'mnode = blockchain get master bring.ip_port'
    print(f"Fetching Master Node: {master_node_command}")
    make_request(conn, "POST", master_node_command)

    # Retrieve master node info (GET)
    get_master_command = "get !mnode"
    print(f"Fetching Master Node Info: {get_master_command}")
    master_node_response = make_request(conn, "GET", get_master_command)
    print(f"Master Node Response: {master_node_response}")

    # Insert policy into blockchain (POST)
    blockchain_insert_command = "blockchain insert where policy = !new_policy and local = true and master = !mnode"
    print(f"Inserting Policy into Blockchain: {blockchain_insert_command}")
    make_request(conn, "POST", blockchain_insert_command)

    # Retrieve the policy from the blockchain (POST)
    blockchain_get_command = f"blockchain get {policy.name}"
    print(f"Fetching Policy from Blockchain: {blockchain_get_command}")
    blockchain_response = make_request(conn, "GET", blockchain_get_command)
    print(f"Blockchain Policy Response: {blockchain_response}")

    return blockchain_response



def run_post_process(key: str, policy, conn: str):
    # print(f"[Post-Processing] Triggered for: {key}")

    handlers = {
        "apply_signature": post_apply_signature,
        "add_new_member": post_add_new_member,
        # Add more here
    }

    handler = handlers.get(key)
    if handler:
        handler(policy, conn)
    else:
        print(f"[Post-Processing] No handler found for: {key}")

def post_add_new_member(policy, conn):
    command = "get !new_policy"
    policy_response = make_request(conn, "GET", command)
    print("NEW MEMBER Response: ", policy_response)

    name = policy_response.get('member', {}).get('name')
    member_type = policy_response.get('member', {}).get('type')

    command = f'blockchain get member where name = {name}'
    check = make_request(conn, "GET", command)
    # print(f"[DEBUG] Checking if member '{name}' already exists: {check}")
    if isinstance(check, list) and len(check) > 0:
        raise Exception(f"Member with name '{name}' already exists: {check}")
    
    # Use different key creation command based on member type
    if member_type == "node":
        # Generate a unique password for node members (no spaces, alphanumeric)
        # Create a unique password based on name and timestamp
        node_password = f"node_{hashlib.md5(f'{name}_{int(time.time())}'.encode()).hexdigest()[:12]}"
        command = f"id create keys for node where password = {node_password}"
        print(f"Creating keys for node member: {command}")
        print(f"Generated node password: {node_password}")
    else:
        command = f"id create keys where password = 123 and keys_file = {name}"
        print(f"Creating keys for user member: {command}")
    
    resp = make_request(conn, "POST", command)
    print("ID CREATE KEYS: ", resp)

    if member_type == "node":
        command = f"new_policy = id sign !new_policy where password = {node_password}"
        sign_response = make_request(conn, "POST", command)

        # command = f"set private password = {name} in file"
        # make_request(conn, "POST", command)
    else:
        command = f'new_member_key = get private key where keys_file = {name}'
        resp = make_request(conn, "POST", command)
        command = "get !new_member_key"
        privkey_resp = make_request(conn, "GET", command)
        print("PRIVKEY Response: ", privkey_resp)

        command = "new_policy = id sign !new_policy where key = !new_member_key and password = 123"
        sign_response = make_request(conn, "POST", command)


    print("SIGN RESPONSE: ", sign_response)
    
    # Verify the member was created successfully
    verify_command = f'blockchain get member where name = {name}'
    verify_response = make_request(conn, "GET", verify_command)
    # print(f"[DEBUG] Verifying member '{name}' was created: {verify_response}")
    
    if isinstance(verify_response, list) and len(verify_response) > 0:
        print(f"[DEBUG] ✅ Member '{name}' successfully created and found in blockchain")
    else:
        print(f"[DEBUG] ❌ Member '{name}' NOT found in blockchain after creation")

    




def post_apply_signature(policy, conn):
    print(f"[Post-Processing] Applying signature for policy: {policy.name}")

    command = "get !new_policy"
    policy_response = make_request(conn, "GET", command)
    print(f"[Post-Processing] Policy Response: {policy_response}")

    # Get signing member name from the policy data (passed from the submit endpoint)
    member_name = None
    
    # First try to get signing member name from the policy data that was passed in
    if hasattr(policy, 'data') and isinstance(policy.data, dict):
        member_name = policy.data.get("__signing_member_name__")
        print(f"[Post-Processing] Found signing member name in policy data: {member_name}")
    
    # If not found in policy data, try to extract from the policy response (legacy fallback)
    if not member_name and isinstance(policy_response, dict):
        # Check if it's a member policy
        if 'member' in policy_response:
            member_name = policy_response['member'].get('name')
        # Check if it's a user policy
        elif 'user' in policy_response:
            member_name = policy_response['user'].get('owner')
        # Check if it's a permissions policy
        elif 'permissions' in policy_response:
            member_name = policy_response['permissions'].get('name')
        # Check if it's a security_group policy
        elif 'security_group' in policy_response:
            member_name = policy_response['security_group'].get('group_name')
        # Check if it's an assignment policy
        elif 'assignment' in policy_response:
            member_name = "admin"  # Default for assignment policies
    
    if not member_name:
        print("[Post-Processing] Warning: Could not extract signing member name from policy, using default 'admin'")
        member_name = "admin"
    
    print(f"[Post-Processing] Using member name: {member_name}")

    # Get the private key for this member
    command = f"private_key = get private key where keys_file = {member_name}"
    print(f"[Post-Processing] Getting private key: {command}")
    make_request(conn, "POST", command)
    
    # Verify the private key was retrieved
    command = "get !private_key"
    privkey_response = make_request(conn, "GET", command)
    print(f"[Post-Processing] Private key response: {privkey_response}")
    
    if not privkey_response:
        print(f"[Post-Processing] Warning: No private key found for {member_name}, trying with 'admin'")
        # Fallback to admin keys
        command = "private_key = get private key where keys_file = admin"
        make_request(conn, "POST", command)

    # Sign the policy with the private key
    command = "new_policy = id sign !new_policy where key = !private_key and password = 123"
    print(f"[Post-Processing] Signing policy: {command}")
    policy_response = make_request(conn, "POST", command)
    print(f"[Post-Processing] Signature Response: {policy_response}")














def make_request(conn, method, command, topic=None, destination=None, payload=None):
    auth = ()
    timeout = 30
    anylog_conn = anylog_connector.AnyLogConnector(conn=conn, auth=auth, timeout=timeout)

    if command.startswith("run client () sql"):
        destination = 'network'
        command = command.replace("run client () ", '')
    elif command.startswith("run client ("):
        end_index = command.find(")")
        if end_index != -1:
            destination = command[len("run client ("):end_index].strip()
            command = command[end_index + 1:].strip()

    try:
        if method.upper() == "GET":
            response = anylog_conn.get(command=command, destination=destination)
        elif method.upper() == "POST":
            response = anylog_conn.post(command=command, topic=topic, destination=destination, payload=payload)
        else:
            raise ValueError("Invalid method. Use 'GET' or 'POST'.")
        # print("response", response)
        return response  # Assuming response is text, change if needed
    except requests.exceptions.RequestException as e:
        print(f"Error making {method.upper()} request: {e}")
        return None