"""
Model Context Protocol (MCP) Server for Logistics Handler.
Exposes logistics tools to MCP-compatible AI agents, IDEs, and orchestrators.
Kept cleanly decoupled from core business logic.
"""

import sys
import os
from typing import Optional, Dict, Any

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from logistics.inventory import check_inventory as _check_inventory, get_inventory as _get_inventory
from logistics.shipments import create_shipment as _create_shipment, track_shipment as _track_shipment
from logistics.routing import estimate_delivery as _estimate_delivery
from logistics.logging_utils import get_agent_activity as _get_agent_activity
from logistics.recovery import execute_with_recovery

# Compatible server instantiation across MCP SDK versions
try:
    from mcp.server.mcpserver import MCPServer
    mcp_server = MCPServer("logistics-mcp-server")
except ImportError:
    from mcp.server.fastmcp import FastMCP
    mcp_server = FastMCP("logistics-mcp-server")


@mcp_server.tool()
def check_inventory(product: str, quantity: int) -> Dict[str, Any]:
    """
    Check stock availability for a specific product and requested quantity.
    Returns available units and sufficiency status.
    """
    return execute_with_recovery(
        _check_inventory,
        product=product,
        quantity=quantity,
        operation_name="mcp_check_inventory",
    )


@mcp_server.tool()
def create_shipment(
    origin: str,
    destination: str,
    product: str,
    quantity: int,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new shipment if inventory is sufficient.
    Deducts stock atomically, saves shipment record, and returns verified shipment ID.
    """
    return execute_with_recovery(
        _create_shipment,
        origin=origin,
        destination=destination,
        product=product,
        quantity=quantity,
        idempotency_key=idempotency_key,
        operation_name="mcp_create_shipment",
    )


@mcp_server.tool()
def track_shipment(shipment_id: str) -> Dict[str, Any]:
    """
    Track an existing shipment by shipment ID.
    Returns status, route, and estimated delivery.
    """
    return execute_with_recovery(
        _track_shipment,
        shipment_id=shipment_id,
        operation_name="mcp_track_shipment",
    )


@mcp_server.tool()
def estimate_delivery(origin: str, destination: str) -> Dict[str, Any]:
    """
    Estimate transit distance, transit days, and delivery date between two locations.
    """
    return execute_with_recovery(
        _estimate_delivery,
        origin=origin,
        destination=destination,
        operation_name="mcp_estimate_delivery",
    )


@mcp_server.tool()
def get_inventory() -> Dict[str, Any]:
    """
    Retrieve the current warehouse catalog and inventory stock levels.
    """
    return execute_with_recovery(
        _get_inventory,
        operation_name="mcp_get_inventory",
    )


@mcp_server.tool()
def get_agent_activity(limit: int = 20) -> Dict[str, Any]:
    """
    Retrieve recent activity records, tool calls, errors, and recovery events.
    """
    return _get_agent_activity(limit=limit)


if __name__ == "__main__":
    # Run standard MCP server over stdio
    try:
        mcp_server.run(transport="stdio")
    except TypeError:
        mcp_server.run()
