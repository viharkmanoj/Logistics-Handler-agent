"""
Tests for inventory operations.
Covers:
- Test 1: Successful inventory check.
- Test 2: Insufficient inventory.
- Test 3: Invalid quantity.
- Test 8: Inventory deduction.
"""

import pytest
from logistics.inventory import check_inventory, get_inventory
from logistics.shipments import create_shipment


def test_1_successful_inventory_check(temp_db):
    """Test 1: Verify inventory check succeeds when stock is available."""
    res = check_inventory(product="Laptop", quantity=10, db_path=temp_db)
    assert res["success"] is True
    assert res["error_code"] is None
    assert res["data"]["is_sufficient"] is True
    assert res["data"]["available_quantity"] == 50
    assert res["data"]["requested_quantity"] == 10


def test_2_insufficient_inventory(temp_db):
    """Test 2: Verify inventory check fails when requested stock exceeds availability."""
    res = check_inventory(product="Laptop", quantity=999, db_path=temp_db)
    assert res["success"] is False
    assert res["error_code"] == "INSUFFICIENT_STOCK"
    assert res["data"]["is_sufficient"] is False
    assert res["data"]["available_quantity"] == 50
    assert "insufficient stock" in res["message"].lower()


def test_3_invalid_quantity(temp_db):
    """Test 3: Reject invalid quantities (zero, negative, non-numeric)."""
    # Test zero
    res_zero = check_inventory(product="Laptop", quantity=0, db_path=temp_db)
    assert res_zero["success"] is False
    assert res_zero["error_code"] == "INVALID_QUANTITY"

    # Test negative
    res_neg = check_inventory(product="Laptop", quantity=-5, db_path=temp_db)
    assert res_neg["success"] is False
    assert res_neg["error_code"] == "INVALID_QUANTITY"

    # Test non-numeric string
    res_str = check_inventory(product="Laptop", quantity="abc", db_path=temp_db)
    assert res_str["success"] is False
    assert res_str["error_code"] == "INVALID_QUANTITY"


def test_unknown_product(temp_db):
    """Verify unknown product returns UNKNOWN_PRODUCT error."""
    res = check_inventory(product="QuantumSupercomputer", quantity=1, db_path=temp_db)
    assert res["success"] is False
    assert res["error_code"] == "UNKNOWN_PRODUCT"


def test_8_inventory_deduction(temp_db):
    """Test 8: Verify stock is properly deducted following a successful shipment."""
    # Check initial stock
    inv_before = check_inventory(product="Phone", quantity=1, db_path=temp_db)
    initial_stock = inv_before["data"]["available_quantity"]
    assert initial_stock == 100

    # Create shipment for 25 units
    ship_res = create_shipment(
        origin="Chennai",
        destination="Bengaluru",
        product="Phone",
        quantity=25,
        db_path=temp_db,
    )
    assert ship_res["success"] is True

    # Check remaining stock
    inv_after = check_inventory(product="Phone", quantity=1, db_path=temp_db)
    assert inv_after["data"]["available_quantity"] == 75
