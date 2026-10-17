"""
Tests for Model Context Protocol (MCP) server integration.
Verifies tool availability, input schemas, and execution via MCP server handlers.
"""

import pytest
import asyncio
from mcp_server.server import (
    mcp_server,
    check_inventory,
    create_shipment,
    track_shipment,
    estimate_delivery,
    get_inventory,
    update_shipment_status,
    get_agent_activity,
)
from logistics.config import STATUS_CREATED, STATUS_IN_TRANSIT


@pytest.mark.asyncio
async def test_mcp_tool_registration():
    """Verify that all 7 logistics tools are registered on the MCP server instance."""
    tools = await mcp_server.list_tools()
    tool_names = [t.name for t in tools]

    expected_tools = [
        "check_inventory",
        "create_shipment",
        "track_shipment",
        "estimate_delivery",
        "get_inventory",
        "update_shipment_status",
        "get_agent_activity",
    ]

    for et in expected_tools:
        assert et in tool_names, f"Tool {et} not found in MCP registered tools: {tool_names}"

    assert len(tools) >= 7


def test_mcp_check_inventory_execution(temp_db, monkeypatch):
    """Test invoking check_inventory through MCP handler."""
    from logistics.agent import set_active_db_path
    set_active_db_path(temp_db)

    res = check_inventory(product="Laptop", quantity=5)
    assert res["success"] is True
    assert res["data"]["is_sufficient"] is True
    assert res["data"]["available_quantity"] == 50


def test_mcp_create_and_track_shipment(temp_db, monkeypatch):
    """Test creating and tracking shipment through MCP handlers."""
    from logistics.agent import set_active_db_path
    set_active_db_path(temp_db)

    create_res = create_shipment(
        origin="Chennai",
        destination="Bengaluru",
        product="Phone",
        quantity=3,
        idempotency_key="MCP-TEST-001",
    )
    assert create_res["success"] is True
    ship_id = create_res["data"]["shipment_id"]

    track_res = track_shipment(shipment_id=ship_id)
    assert track_res["success"] is True
    assert track_res["data"]["shipment_id"] == ship_id
    assert track_res["data"]["status"] == STATUS_CREATED


def test_mcp_update_status_and_activity(temp_db, monkeypatch):
    """Test advancing status and querying activity through MCP handlers."""
    from logistics.agent import set_active_db_path
    set_active_db_path(temp_db)

    create_res = create_shipment(
        origin="Chennai",
        destination="Bengaluru",
        product="Laptop",
        quantity=2,
    )
    ship_id = create_res["data"]["shipment_id"]

    # Advance status
    up_res = update_shipment_status(shipment_id=ship_id, status=STATUS_IN_TRANSIT)
    assert up_res["success"] is True
    assert up_res["data"]["status"] == STATUS_IN_TRANSIT

    # Query activity
    act_res = get_agent_activity(limit=10)
    assert act_res["success"] is True
    assert len(act_res["data"]["activities"]) > 0
