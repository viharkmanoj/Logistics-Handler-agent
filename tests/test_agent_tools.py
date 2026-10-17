"""
Tests for AI Agent intent resolution, tool calling, and workflow execution.
"""

import pytest
from logistics.agent import DemoLogisticsAgent, LogisticsCoordinatorAgent, dispatch_tool
from logistics.routing import estimate_delivery
from logistics.logging_utils import get_agent_activity


def test_agent_create_shipment_workflow(temp_db):
    """
    Test agent workflow:
    'Create a shipment for 5 laptops from Chennai to Bengaluru and check inventory availability.'
    """
    agent = DemoLogisticsAgent()
    prompt = "Create a shipment for 5 laptops from Chennai to Bengaluru and check inventory availability."
    result = agent.run(prompt, db_path=temp_db)

    assert "Shipment Confirmed & Created Successfully" in result["response"]
    assert len(result["tools_executed"]) == 2
    assert result["tools_executed"][0]["tool"] == "check_inventory"
    assert result["tools_executed"][1]["tool"] == "create_shipment"

    # Verify inventory was decremented from 50 to 45
    inv_check = dispatch_tool("check_inventory", {"product": "Laptop", "quantity": 1}, db_path=temp_db)
    assert inv_check["data"]["available_quantity"] == 45


def test_agent_stock_check_queries(temp_db):
    """Test stock inquiry requests."""
    agent = DemoLogisticsAgent()

    # Query 1: "Check stock for 10 laptops."
    res1 = agent.run("Check stock for 10 laptops.", db_path=temp_db)
    assert "Stock Availability Check" in res1["response"]
    assert "Laptop" in res1["response"]
    assert len(res1["tools_executed"]) > 0
    result_tool = res1["tools_executed"][0]
    assert result_tool["tool"] == "check_inventory"

    # Query 2: "How many headphones are available?"
    res2 = agent.run("How many headphones are available?", db_path=temp_db)
    assert "Headphones" in res2["response"]


def test_agent_delivery_estimation(temp_db):
    """Test 'Estimate delivery time from Chennai to Bengaluru.'"""
    agent = DemoLogisticsAgent()
    res = agent.run("Estimate delivery time from Chennai to Bengaluru.", db_path=temp_db)

    assert "Delivery Estimate" in res["response"]
    assert "Chennai ➔ Bengaluru" in res["response"]
    assert len(res["tools_executed"]) == 1
    assert res["tools_executed"][0]["tool"] == "estimate_delivery"


def test_agent_tracking_workflow(temp_db):
    """Test tracking an existing shipment by ID."""
    # First create a shipment
    create_res = dispatch_tool(
        "create_shipment",
        {"origin": "Chennai", "destination": "Bengaluru", "product": "Phone", "quantity": 3},
        db_path=temp_db,
    )
    shipment_id = create_res["data"]["shipment_id"]

    # Now ask agent to track
    agent = DemoLogisticsAgent()
    res = agent.run(f"Track shipment {shipment_id}", db_path=temp_db)
    assert "Shipment Tracking Result" in res["response"]
    assert shipment_id in res["response"]


def test_agent_missing_parameters_clarification(temp_db):
    """
    When essential shipment parameters are missing (e.g. quantity or cities),
    agent asks for clarification without executing tools blindly.
    """
    agent = DemoLogisticsAgent()
    res = agent.run("Please ship some laptops", db_path=temp_db)

    assert "Clarification Needed" in res["response"]
    assert len(res["tools_executed"]) == 0


def test_agent_failure_explanation(temp_db):
    """Test 'Why did my shipment fail?' queries agent activity logs."""
    # First trigger a deliberate failure
    dispatch_tool(
        "create_shipment",
        {"origin": "Chennai", "destination": "Bengaluru", "product": "Laptop", "quantity": 99999},
        db_path=temp_db,
    )

    agent = DemoLogisticsAgent()
    res = agent.run("Why did my shipment fail?", db_path=temp_db)
    assert "Failure Analysis" in res["response"]
    assert "INSUFFICIENT_STOCK" in res["response"]


def test_routing_estimate_labeling(temp_db):
    """Verify estimate_delivery outputs clearly labeled simulated information."""
    est = estimate_delivery("Chennai", "Bengaluru", db_path=temp_db)
    assert est["success"] is True
    assert est["data"]["is_simulated"] is True
    assert "Simulated Logistics Estimation Engine" in est["data"]["provider"]
    assert est["data"]["estimated_distance_km"] == 346
