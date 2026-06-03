# nodechecks.py
"""
Node check functions for the nodecheck plugin.
These functions execute specific commands on nodes and return the raw output.
"""

from ..utils import make_request, monitor_network as utils_monitor_network
from typing import Dict, Any


def get_status(connection: str) -> Dict[str, Any]:
    """
    Get comprehensive status information from the node.
    Returns basic node information, time, and system status.
    """
    try:
        status_data = {}
        
        # Get system status
        try:
            status_data["status"] = make_request(connection, "GET", "get status")
        except Exception as e:
            status_data["status"] = f"Error: {str(e)}"
        
        
        return {
            "success": True,
            "data": status_data,
            "message": "Status information retrieved successfully"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get status: {str(e)}"
        }


def get_processes(connection: str) -> Dict[str, Any]:
    """
    Get information about running processes on the node.
    """
    try:
        # Get running processes
        processes_data = make_request(connection, "GET", "get processes where format=json")
        
        return {
            "success": True,
            "data": processes_data,
            "message": "Process information retrieved successfully"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get processes: {str(e)}"
        }


def get_connections(connection: str) -> Dict[str, Any]:
    """
    Get network connection information from the node.
    """
    try:
        # Get network connections
        connections_data = make_request(connection, "GET", "get connections where format=json")
        
        return {
            "success": True,
            "data": connections_data,
            "message": "Connection information retrieved successfully"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get connections: {str(e)}"
        }


def test_network(connection: str) -> Dict[str, Any]:
    """
    Test network connectivity and get network information.
    """
    try:
        # Test network connectivity
        network_data = make_request(connection, "GET", "test network")
        
        return {
            "success": True,
            "data": network_data,
            "message": "Network test completed successfully"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to test network: {str(e)}"
        }


def monitor_network(connection: str) -> Dict[str, Any]:
    """
    Monitor network nodes using the utility function from utils.py.
    This provides detailed monitoring information about network nodes.
    """
    try:
        # Use the monitor_network function from utils
        monitored_data = utils_monitor_network(connection)
        
        return {
            "success": True,
            "data": monitored_data,
            "message": f"Network monitoring completed successfully. Found {len(monitored_data)} monitored nodes."
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to monitor network: {str(e)}"
        }


def run_all_checks(connection: str) -> Dict[str, Any]:
    """
    Run all available checks and return comprehensive results.
    """
    try:
        all_results = {}
        
        # Run status check
        status_result = get_status(connection)
        all_results["status"] = status_result
        
        # Run processes check
        processes_result = get_processes(connection)
        all_results["processes"] = processes_result
        
        # Run connections check
        connections_result = get_connections(connection)
        all_results["connections"] = connections_result
        
        # Run network test
        # network_result = test_network(connection)
        # all_results["network_test"] = network_result
        
        # # Run network monitoring
        # monitor_result = monitor_network(connection)
        # all_results["network_monitor"] = monitor_result
        
        # Count successful checks
        successful_checks = sum(1 for result in all_results.values() if result.get("success", False))
        total_checks = len(all_results)
        
        return {
            "success": True,
            "data": all_results,
            "summary": {
                "total_checks": total_checks,
                "successful_checks": successful_checks,
                "failed_checks": total_checks - successful_checks
            },
            "message": f"All checks completed. {successful_checks}/{total_checks} checks successful."
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to run all checks: {str(e)}"
        }
