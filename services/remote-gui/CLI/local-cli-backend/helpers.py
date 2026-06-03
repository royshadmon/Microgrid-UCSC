
from pydantic import BaseModel
from typing import Dict
import requests
from parsers import parse_response
import datetime
import json
import requests

from classes import *

import anylog_api.anylog_connector as anylog_connector


# Connect to AnyLog / EdgeLake connector
conn = '10.0.0.11:32249'
# conn = '127.0.0.1:32149'

auth = ()
timeout = 30
anylog_conn = anylog_connector.AnyLogConnector(conn=conn, auth=auth, timeout=timeout)

class Policy(BaseModel):
    name: str  # Policy name
    data: Dict[str, str]  # Key-value pairs


def monitor_network(conn: str) -> Dict:
    raw_response = make_request(conn, "GET", "get monitored operators")
    structured_data = parse_response(raw_response)
    data = structured_data.get("data", {})
    vals = list(data.values())
    monitored_nodes_filtered = filter_dicts_by_keys(vals, [
        "Node",
        "node name",
        "operational time",
        "elapsed time",
        "new rows",
        "total rows",
        "Free Space Percent",
        "CPU Percent",
        "Packets Recv",
        "Packets Sent",
        "Network Error"
      ])
    return monitored_nodes_filtered

def filter_dicts_by_keys(dict_list, keys_to_keep):
    """
    Filters each dictionary in dict_list to keep only the keys in keys_to_keep.

    Parameters:
        dict_list (list of dict): The list of dictionaries to filter.
        keys_to_keep (list of str): The list of keys to retain in each dictionary.

    Returns:
        list of dict: A new list of dictionaries containing only the specified keys.
    """
    return [
        {key: d[key] for key in keys_to_keep if key in d}
        for d in dict_list
    ]

def grab_network_nodes(conn: str) -> Dict:
    raw_response = make_request(conn, "GET", "test network")
    print(raw_response)

    structured_data = parse_response(raw_response)
    data = structured_data.get("data", {})

    connected_nodes = [node['Address'] for node in data if node['Status'] == "+"]
    connected_nodes = [node[:-1] + "9" for node in connected_nodes]
    return connected_nodes


def make_policy(conn:str, policy: Policy):
    # Construct the policy command
    policy_command = f'{policy.name} = create policy {policy.name} where '
    key_value_pairs = [f"{k} = {v}" for k, v in policy.data.items()]
    policy_command += " and ".join(key_value_pairs)

    # Submit the policy (POST)
    print(f"Submitting Policy: {policy_command}")
    make_request(conn, "POST", policy_command)

    # Retrieve the created policy (GET)
    get_policy_command = f"get !{policy.name}"
    print(f"Fetching Policy: {get_policy_command}")
    policy_response = make_request(conn, "GET", get_policy_command)
    print(f"Policy Response: {policy_response}")

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
    blockchain_insert_command = f"blockchain insert where policy = !{policy.name} and local = true and master = !mnode"
    print(f"Inserting Policy into Blockchain: {blockchain_insert_command}")
    make_request(conn, "POST", blockchain_insert_command)

    # Retrieve the policy from the blockchain (POST)
    blockchain_get_command = f"blockchain get {policy.name}"
    print(f"Fetching Policy from Blockchain: {blockchain_get_command}")
    blockchain_response = make_request(conn, "GET", blockchain_get_command)
    print(f"Blockchain Policy Response: {blockchain_response}")

    return blockchain_response



def make_request(conn, method, command, topic=None, destination=None, payload=None):


    auth = ()
    timeout = 30
    anylog_conn = anylog_connector.AnyLogConnector(conn=conn, auth=auth, timeout=timeout)

    blobs = False
    streaming = False


    if command.startswith("run client () sql"):
        destination = 'network'
        command = command.replace("run client () ", '')
    elif command.startswith("run client ("):
        end_index = command.find(")")
        if end_index != -1:
            destination = command[len("run client ("):end_index].strip()
            command = command[end_index + 1:].strip()

    if "file using file" in command:
        blobs = True
        if "dest_type" in command:
            streaming = True

    

    print("conn", conn)
    print("command", command)
    print("destination", destination)

    # url = f"http://{conn}"
    # # url = "http://127.0.0.1:32049" "23.239.12.151:32349"
    # headers = {
    #     "User-Agent": "AnyLog/1.23",
    #     "command": command,
    # }
    
    try:
        if method.upper() == "GET":
            response = anylog_conn.get(command=command, destination=destination)
            # response = requests.get(url, headers=headers)
        elif method.upper() == "POST":
            response = anylog_conn.post(command=command, topic=topic, destination=destination, payload=payload)
            # response = requests.post(url, headers=headers)
        else:
            raise ValueError("Invalid method. Use 'GET' or 'POST'.")
        
        # response.raise_for_status()  # Raise an error for bad status codes
        print("response", response)

        if blobs:
            if streaming:
                return { 'streaming': response }
            return { 'blobs': response }
        return response  # Assuming response is text, change if needed
    except Exception as e:
        print(f"=== FULL ERROR DETAILS ===")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        print(f"Command: {command}")
        print(f"Method: {method}")
        print(f"Destination: {destination}")
        print(f"Connection: {conn}")
        
        # Try to extract more details from the exception
        if hasattr(e, '__dict__'):
            print(f"Exception attributes: {e.__dict__}")
        
        # If it's a requests exception, try to get more details
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response headers: {dict(e.response.headers)}")
            try:
                print(f"Response text: {e.response.text}")
            except:
                print("Could not read response text")
        
        print(f"=== END ERROR DETAILS ===")
        
        # Return a structured error response instead of None
        return {
            "type": "error",
            "data": f"Error executing command: {str(e)}",
            "error_details": {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "command": command,
                "method": method,
                "destination": destination,
                "connection": conn
            }
        }

# blockchain delete policy where id = a29bcfd55cef20c6834f29fbb3aaf882 and master = 172.24.0.2:32048






# SENDING DATA TO ANYLOG



def prep_to_add_data(data: list, dbms: str, table: str) -> list:
    """
    Prepare data for adding to the database.
    """
    for record in data:
        record['dbms'] = dbms
        record['table'] = table
    return json.dumps(data)

def infer_schema(data) -> list:
    print("Parsing JSON")
    schema = {}
    for record in data:
        for key, value in record.items():
            if key not in schema:
                schema[key] = type(value).__name__
    print("Schema", schema)
    return schema


def build_msg_client_command(schema: dict) -> str:
    """
    Build a topic string based on the provided parameters.
    """
    column_details = []

    for key, value in schema.items():
        # print(f"Key: {key}, Value: {value}")
        # if key == 'timestamp':
        #     val = f'column.timestamp.timestamp="bring [timestamp]"'
        #     column_details.append(val)
        # else:
        #     val = f'column.{key}=(type={value} and value=bring [{key}])'
        #     column_details.append(val)
        val = f'column.{key}=(type={value} and value=bring [{key}])'
        column_details.append(val)

    column_str = ' and '.join(column_details)
    topic_str = f'run msg client where broker=rest and user-agent=anylog and log=false and topic=(name=new-data and dbms="bring [dbms]" and table="bring [table]" and {column_str})'
    return topic_str

    # base_str = 'run msg client where broker=rest and user-agent=anylog and log=false and topic=(name=new-data and dbms="bring [dbms]" and table="bring [table]" and column.timestamp.timestamp="bring [timestamp]" and column.value=(type=int and value=bring [value]))'

def parse_check_clients(raw: str) -> dict:
    """
    Parse the response from the check clients command.
    """
    lines = raw.strip().splitlines()
    idline = lines[0]
    ret = idline.split(": ")
    ret[1] = ret[1].strip()
    return int(ret[1])


def send_json_data(conn, dbms, table, data):
    
    # infer the schema of the data
    inferred_schema = infer_schema(data)

    # build the msg client command
    msg_client_cmd = build_msg_client_command(inferred_schema)
    print("msg_client_cmd", msg_client_cmd)

    # prep data with dbms and table
    prepped_data = prep_to_add_data(data, dbms, table)

    # check for existing msg client

    check_clients = make_request(conn, "GET", "get msg client where topic = new-data")
    if "No message client subscriptions" in check_clients:
        # create new client
        resp = make_request(conn, "POST", msg_client_cmd)
        print("New Client:", resp)
    else: 
        # get old client id
        old_client_id = parse_check_clients(check_clients)
        print(old_client_id)

        # kill old client
        kill_cmd = f'exit msg client {old_client_id}'
        make_request(conn, "POST", kill_cmd)

        # create new client
        resp = make_request(conn, "POST", msg_client_cmd)
        print("New Client:", resp)

    # send data
    response = make_request(conn=conn, method="POST", command='data', topic='new-data', payload=prepped_data)
    print("Data send resp:", response)

    # get streaming to check if data was sent
    response = make_request(conn, "GET", "get streaming")
    print("Streaming:", response)

    return response 







def get_preset_base_policy(conn: str):
    # Retrieve the created preset policy (GET)
    # NEEDS TO BE CHANGED INTO FROM X BRING Y
    get_policy_command = "get !bookmark_policy"
    print(f"Fetching Preset Policy: {get_policy_command}")
    policy_response = make_request(conn, "GET", get_policy_command)
    print(f"Preset Policy Response: {policy_response}")
    
    return policy_response


def check_preset_basepolicy(conn: str):
    resp = get_preset_base_policy(conn)
    print("check_policycmd", resp)
    if resp is None:
        c1 = "set policy bookmark_policy [bookmark] = {}"
        resp = make_request(conn, "POST", c1)
        print("setnewpolicyresp", resp)

        c2 = "set policy bookmark_policy [bookmark][bookmarks] = {}"
        resp = make_request(conn, "POST", c2)
        print("setbookmarksemptyresp", resp)

    return get_preset_base_policy(conn)


def make_preset_group_policy(conn: str, group_name:str):
    check_preset_basepolicy(conn)

    policy_command = f'set policy bookmark_policy [bookmark][bookmarks][{group_name}] = {{}}'

    # Submit the preset policy (POST)
    print(f"Submitting Preset Group Policy: {policy_command}")
    make_request(conn, "POST", policy_command)

    basepolicy = get_preset_base_policy(conn)

    return basepolicy



def make_preset_policy(conn: str, preset: Preset, group_name: str):
    name = preset.button
    cmd = preset.command
    type = preset.type


    check_preset_basepolicy(conn)


    # Construct the policy command for the preset
    # set policy bookmark_policy [bookmark][bookmarks][event-log] = {"type": "get", "value": "get event log"}
    policy_command = f'set policy bookmark_policy [bookmark][bookmarks][{group_name}][{name}] = {{"type": "{type.lower()}", "command": "{cmd}"}}'

    # Submit the preset policy (POST)
    print(f"Submitting Preset Policy: {policy_command}")
    make_request(conn, "POST", policy_command)

    basepolicy = get_preset_base_policy(conn)

    return basepolicy



def delete_preset_group_policy(conn: str, group_name:str):
    check_preset_basepolicy(conn)

    # Construct the policy command for the preset
    # set policy bookmark_policy [bookmark][bookmarks][event-log] = {"type": "get", "value": "get event log"}
    policy_command = f'set policy bookmark_policy [bookmark][bookmarks][{group_name}] = ""'

    # Submit the preset policy (POST)
    print(f"Submitting Preset Policy: {policy_command}")
    make_request(conn, "POST", policy_command)

    basepolicy = get_preset_base_policy(conn)

    return basepolicy


# SQL QUERY GENERATOR HELPER FUNCTIONS

def get_databases(conn: str) -> list:
    """
    Get all databases available on the AnyLog node using the data nodes command.
    """
    try:
        # Use AnyLog command to get all data nodes
        raw_response = make_request(conn, "GET", "get data nodes where format=json")
        structured_data = parse_response(raw_response)
        
        if structured_data.get("type") == "json" and structured_data.get("data"):
            data_nodes = structured_data["data"]
            
            # Extract unique databases from the data nodes
            databases = set()
            for node in data_nodes:
                if node.get("DBMS") and node["DBMS"].strip():
                    databases.add(node["DBMS"])
            
            # Convert to list of dictionaries
            return [{"database_name": db, "name": db} for db in sorted(databases)]
        else:
            return []
    except Exception as e:
        print(f"Error getting databases: {e}")
        return []


def get_tables(conn: str, database: str) -> list:
    """
    Get all tables in a specific database using filtered data nodes command.
    """
    try:
        # Use AnyLog command with database filter
        raw_response = make_request(conn, "GET", f'get data nodes where format=json and dbms="{database}"')
        structured_data = parse_response(raw_response)
        
        if structured_data.get("type") == "json" and structured_data.get("data"):
            data_nodes = structured_data["data"]
            
            # Extract unique tables for the specified database
            tables = set()
            for node in data_nodes:
                if node.get("Table") and node["Table"].strip():
                    tables.add(node["Table"])
            
            # Convert to list of dictionaries
            return [{"table_name": table, "name": table} for table in sorted(tables)]
        else:
            return []
    except Exception as e:
        print(f"Error getting tables: {e}")
        return []


def get_columns(conn: str, database: str, table: str) -> list:
    """
    Get all columns in a specific table using the columns command with JSON format.
    """
    try:
        # Use AnyLog command to get columns with JSON format
        raw_response = make_request(conn, "GET", f'get columns where dbms="{database}" and table="{table}" and format=json')
        structured_data = parse_response(raw_response)
        
        if structured_data.get("type") == "json" and structured_data.get("data"):
            columns_data = structured_data["data"]
            
            # Convert the JSON object to a list of column objects
            columns = []
            for column_name, data_type in columns_data.items():
                # Skip the system columns that should be ignored
                if column_name not in ["row_id", "tsd_name", "tsd_id"]:
                    columns.append({
                        "column_name": column_name,
                        "name": column_name,
                        "data_type": data_type,
                        "type": data_type
                    })
            
            return columns
        else:
            return []
    except Exception as e:
        print(f"Error getting columns: {e}")
        return []


def get_data_nodes(conn: str) -> list:
    """
    Get all data nodes information including companies, databases, tables, and node details.
    """
    try:
        # Use AnyLog command to get all data nodes
        raw_response = make_request(conn, "GET", "get data nodes where format=json")
        structured_data = parse_response(raw_response)
        
        if structured_data.get("type") == "json" and structured_data.get("data"):
            return structured_data["data"]
        else:
            return []
    except Exception as e:
        print(f"Error getting data nodes: {e}")
        return []


def get_companies(conn: str) -> list:
    """
    Get all companies available in the AnyLog network.
    """
    try:
        data_nodes = get_data_nodes(conn)
        
        # Extract unique companies
        companies = set()
        for node in data_nodes:
            if node.get("Company") and node["Company"].strip():
                companies.add(node["Company"])
        
        return [{"company_name": company, "name": company} for company in sorted(companies)]
    except Exception as e:
        print(f"Error getting companies: {e}")
        return []


def get_tables_by_company(conn: str, company: str) -> list:
    """
    Get all tables for a specific company using filtered data nodes command.
    """
    try:
        # Use AnyLog command with company filter
        raw_response = make_request(conn, "GET", f'get data nodes where format=json and company="{company}"')
        structured_data = parse_response(raw_response)
        
        if structured_data.get("type") == "json" and structured_data.get("data"):
            data_nodes = structured_data["data"]
            
            # Extract tables for the specified company
            tables = []
            for node in data_nodes:
                if (node.get("DBMS") and 
                    node.get("Table") and 
                    node["DBMS"].strip() and 
                    node["Table"].strip()):
                    tables.append({
                        "company": node["Company"],
                        "database": node["DBMS"],
                        "table": node["Table"],
                        "node_name": node.get("Node Name", ""),
                        "cluster_id": node.get("Cluster ID", ""),
                        "external_ip_port": node.get("External IP/Port", "")
                    })
            
            return tables
        else:
            return []
    except Exception as e:
        print(f"Error getting tables by company: {e}")
        return []


def get_tables_by_company_and_dbms(conn: str, company: str, dbms: str) -> list:
    """
    Get all tables for a specific company and database using filtered data nodes command.
    """
    try:
        # Use AnyLog command with company and database filter
        raw_response = make_request(conn, "GET", f'get data nodes where format=json and company="{company}" and dbms="{dbms}"')
        structured_data = parse_response(raw_response)
        
        if structured_data.get("type") == "json" and structured_data.get("data"):
            data_nodes = structured_data["data"]
            
            # Extract tables for the specified company and database
            tables = []
            for node in data_nodes:
                if node.get("Table") and node["Table"].strip():
                    tables.append({
                        "company": node["Company"],
                        "database": node["DBMS"],
                        "table": node["Table"],
                        "node_name": node.get("Node Name", ""),
                        "cluster_id": node.get("Cluster ID", ""),
                        "external_ip_port": node.get("External IP/Port", "")
                    })
            
            return tables
        else:
            return []
    except Exception as e:
        print(f"Error getting tables by company and database: {e}")
        return []


def get_nodes_by_company(conn: str, company: str) -> list:
    """
    Get all nodes for a specific company using filtered data nodes command.
    """
    try:
        # Use AnyLog command with company filter
        raw_response = make_request(conn, "GET", f'get data nodes where format=json and company="{company}"')
        structured_data = parse_response(raw_response)
        
        if structured_data.get("type") == "json" and structured_data.get("data"):
            data_nodes = structured_data["data"]
            
            # Extract unique nodes for the specified company
            nodes = set()
            for node in data_nodes:
                if node.get("Node Name") and node["Node Name"].strip():
                    nodes.add(node["Node Name"])
            
            return [{"node_name": node, "name": node} for node in sorted(nodes)]
        else:
            return []
    except Exception as e:
        print(f"Error getting nodes by company: {e}")
        return []


def get_databases_by_company(conn: str, company: str) -> list:
    """
    Get all databases for a specific company using filtered data nodes command.
    """
    try:
        # Use AnyLog command with company filter
        raw_response = make_request(conn, "GET", f'get data nodes where format=json and company="{company}"')
        structured_data = parse_response(raw_response)
        
        if structured_data.get("type") == "json" and structured_data.get("data"):
            data_nodes = structured_data["data"]
            
            # Extract unique databases for the specified company
            databases = set()
            for node in data_nodes:
                if node.get("DBMS") and node["DBMS"].strip():
                    databases.add(node["DBMS"])
            
            return [{"database_name": db, "name": db} for db in sorted(databases)]
        else:
            return []
    except Exception as e:
        print(f"Error getting databases by company: {e}")
        return []


def get_table_info_with_columns(conn: str, database: str, table: str) -> dict:
    """
    Get comprehensive table information including columns and metadata.
    """
    try:
        # Get columns for the table
        columns = get_columns(conn, database, table)
        
        # Get table metadata from data nodes
        raw_response = make_request(conn, "GET", f'get data nodes where format=json and dbms="{database}" and table="{table}"')
        structured_data = parse_response(raw_response)
        
        table_info = {
            "database": database,
            "table": table,
            "columns": columns,
            "column_count": len(columns),
            "metadata": {}
        }
        
        if structured_data.get("type") == "json" and structured_data.get("data"):
            data_nodes = structured_data["data"]
            if data_nodes:
                # Use the first node's metadata
                node = data_nodes[0]
                table_info["metadata"] = {
                    "company": node.get("Company", ""),
                    "node_name": node.get("Node Name", ""),
                    "cluster_id": node.get("Cluster ID", ""),
                    "external_ip_port": node.get("External IP/Port", ""),
                    "cluster_status": node.get("Cluster Status", ""),
                    "node_status": node.get("Node Status", "")
                }
        
        return table_info
    except Exception as e:
        print(f"Error getting table info with columns: {e}")
        return {
            "database": database,
            "table": table,
            "columns": [],
            "column_count": 0,
            "metadata": {}
        }


def execute_sql_query(conn: str, query: str) -> str:
    """
    Execute a SQL query on the AnyLog node.
    """
    try:
        # Use AnyLog SQL command to execute the query
        raw_response = make_request(conn, "GET", f"sql {query}")
        return raw_response
    except Exception as e:
        print(f"Error executing SQL query: {e}")
        raise e