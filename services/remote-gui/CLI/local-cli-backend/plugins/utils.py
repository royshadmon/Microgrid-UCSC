# plugins/utils.py
"""
Utility module for plugins that provides easy access to backend functionality.
This module imports commonly used functions and classes from the backend codebase.
"""

import sys
import os
from typing import Dict, Any

# Add the backend directory to the path for imports
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

# Import core backend functionality
try:
    # Import helpers functions
    from helpers import (
        make_request,
        monitor_network,
        grab_network_nodes,
        get_data_nodes,
        get_companies,
        get_nodes_by_company,
        get_databases,
        get_tables,
        get_columns,
        get_tables_by_company,
        get_tables_by_company_and_dbms,
        get_databases_by_company,
        get_table_info_with_columns,
        execute_sql_query,
        make_policy,
        get_preset_base_policy,
        check_preset_basepolicy,
        make_preset_group_policy,
        make_preset_policy,
        delete_preset_group_policy,
        send_json_data,
        prep_to_add_data,
        infer_schema,
        build_msg_client_command,
        parse_check_clients,
        filter_dicts_by_keys
    )
    
    # Import parser functions
    from parsers import (
        parse_response,
        parse_table_fixed,
        parse_table,
        parse_json
    )
    
    # Import classes
    from classes import (
        Connection,
        DBConnection,
        Command,
        Policy,
        BookmarkUpdateRequest,
        PresetGroup,
        PresetGroupID,
        Preset
    )
    
    # Import anylog connector
    try:
        import anylog_api.anylog_connector as anylog_connector
    except ImportError:
        anylog_connector = None
    
    # Import security functionality if available
    try:
        from security.helpers import *
        from security.parsers import *
        from security.permissions import *
        from security.assignment_manager import *
    except ImportError:
        # Security module not available, continue without it
        pass
    
except ImportError as e:
    print(f"Warning: Could not import some backend modules: {e}")
    # Define fallback functions for critical imports
    def make_request(*args, **kwargs):
        raise ImportError("make_request not available - check backend imports")
    
    def parse_response(*args, **kwargs):
        raise ImportError("parse_response not available - check backend imports")

# Convenience functions for common operations
def create_anylog_connector(conn: str, auth: tuple = (), timeout: int = 30):
    """Create an AnyLog connector instance"""
    if anylog_connector is None:
        raise ImportError("anylog_connector not available")
    return anylog_connector.AnyLogConnector(conn=conn, auth=auth, timeout=timeout)

def execute_command(conn: str, method: str, command: str, **kwargs):
    """Execute a command on a node with error handling"""
    try:
        return make_request(conn, method, command, **kwargs)
    except Exception as e:
        raise Exception(f"Command execution failed: {str(e)}")

def parse_command_response(response: Any) -> Dict:
    """Parse command response with error handling"""
    try:
        return parse_response(response)
    except Exception as e:
        raise Exception(f"Response parsing failed: {str(e)}")

def get_node_health(conn: str) -> Dict:
    """Get basic health information for a node"""
    try:
        health_info = {}
        
        # Try to get basic node info
        try:
            health_info["node_info"] = make_request(conn, "GET", "get node")
        except Exception:
            health_info["node_info"] = "Unable to retrieve"
        
        # Try to get current time
        try:
            health_info["current_time"] = make_request(conn, "GET", "get time")
        except Exception:
            health_info["current_time"] = "Unable to retrieve"
        
        # Try to get monitored nodes count
        try:
            monitored = monitor_network(conn)
            health_info["monitored_nodes"] = len(monitored)
        except Exception:
            health_info["monitored_nodes"] = 0
        
        return health_info
    except Exception as e:
        raise Exception(f"Health check failed: {str(e)}")

def get_network_summary(conn: str) -> Dict:
    """Get a summary of network status"""
    try:
        summary = {}
        
        # Get monitored nodes
        try:
            monitored = monitor_network(conn)
            summary["monitored_nodes"] = monitored
            summary["monitored_count"] = len(monitored)
        except Exception:
            summary["monitored_nodes"] = []
            summary["monitored_count"] = 0
        
        # Get connected nodes
        try:
            connected = grab_network_nodes(conn)
            summary["connected_nodes"] = connected
            summary["connected_count"] = len(connected)
        except Exception:
            summary["connected_nodes"] = []
            summary["connected_count"] = 0
        
        # Get data nodes
        try:
            data_nodes = get_data_nodes(conn)
            summary["data_nodes"] = data_nodes
            summary["data_nodes_count"] = len(data_nodes)
        except Exception:
            summary["data_nodes"] = []
            summary["data_nodes_count"] = 0
        
        # Get companies
        try:
            companies = get_companies(conn)
            summary["companies"] = companies
            summary["companies_count"] = len(companies)
        except Exception:
            summary["companies"] = []
            summary["companies_count"] = 0
        
        return summary
    except Exception as e:
        raise Exception(f"Network summary failed: {str(e)}")

# Export commonly used items for easy importing
__all__ = [
    # Core functions
    'make_request',
    'execute_command',
    'parse_command_response',
    'get_node_health',
    'get_network_summary',
    
    # Network functions
    'monitor_network',
    'grab_network_nodes',
    'get_data_nodes',
    'get_companies',
    'get_nodes_by_company',
    
    # Database functions
    'get_databases',
    'get_tables',
    'get_columns',
    'get_tables_by_company',
    'get_tables_by_company_and_dbms',
    'get_databases_by_company',
    'get_table_info_with_columns',
    'execute_sql_query',
    
    # Policy functions
    'make_policy',
    'get_preset_base_policy',
    'check_preset_basepolicy',
    'make_preset_group_policy',
    'make_preset_policy',
    'delete_preset_group_policy',
    
    # Data functions
    'send_json_data',
    'prep_to_add_data',
    'infer_schema',
    'build_msg_client_command',
    'parse_check_clients',
    'filter_dicts_by_keys',
    
    # Parser functions
    'parse_response',
    'parse_table_fixed',
    'parse_table',
    'parse_json',
    
    # Classes
    'Connection',
    'DBConnection',
    'Command',
    'Policy',
    'BookmarkUpdateRequest',
    'PresetGroup',
    'PresetGroupID',
    'Preset',
    
    # Connector
    'create_anylog_connector',
    'anylog_connector'
]
