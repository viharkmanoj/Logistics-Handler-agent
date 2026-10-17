"""
Tests for shipment lifecycle operations.
Covers:
- Test 4: Successful shipment creation.
- Test 5: Shipment persistence.
- Test 6: Shipment tracking.
- Test 7: Unknown shipment ID.
- Test 12: Invalid shipment status transition.
- Test 13: Database consistency.
"""

import pytest
import sqlite3
from logistics.shipments import (
    create_shipment,
    track_shipment,
    update_shipment_status,
    get_shipments,
)
from logistics.config import (
    STATUS_CREATED,
    STATUS_IN_TRANSIT,
    STATUS_OUT_FOR_DELIVERY,
    STATUS_DELIVERED,
    STATUS_CANCELLED,
)
from logistics.database import get_connection


def test_4_successful_shipment_creation(temp_db):
    """Test 4: Verify shipment can be successfully created with valid inputs."""
    res = create_shipment(
        origin="Chennai",
        destination="Bengaluru",
        product="Laptop",
        quantity=5,
        db_path=temp_db,
    )
    assert res["success"] is True
    assert res["error_code"] is None
    assert "shipment_id" in res["data"]
    assert res["data"]["shipment_id"].startswith("SHP-")
    assert res["data"]["status"] == STATUS_CREATED
    assert res["data"]["quantity"] == 5
    assert res["data"]["product"] == "Laptop"


def test_5_shipment_persistence(temp_db):
    """Test 5: Verify shipment records persist in SQLite across independent connections."""
    create_res = create_shipment(
        origin="Mumbai",
        destination="Delhi",
        product="Phone",
        quantity=10,
        db_path=temp_db,
    )
    shipment_id = create_res["data"]["shipment_id"]

    # Open a fresh connection directly to the SQLite file
    conn = get_connection(temp_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shipments WHERE shipment_id = ?;", (shipment_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["shipment_id"] == shipment_id
        assert row["origin"] == "Mumbai"
        assert row["destination"] == "Delhi"
        assert row["quantity"] == 10
        assert row["status"] == STATUS_CREATED
    finally:
        conn.close()


def test_6_shipment_tracking(temp_db):
    """Test 6: Retrieve shipment details and status by ID."""
    create_res = create_shipment(
        origin="Hyderabad",
        destination="Bengaluru",
        product="Headphones",
        quantity=8,
        db_path=temp_db,
    )
    shipment_id = create_res["data"]["shipment_id"]

    track_res = track_shipment(shipment_id=shipment_id, db_path=temp_db)
    assert track_res["success"] is True
    assert track_res["data"]["shipment_id"] == shipment_id
    assert track_res["data"]["status"] == STATUS_CREATED
    assert track_res["data"]["origin"] == "Hyderabad"
    assert track_res["data"]["destination"] == "Bengaluru"


def test_7_unknown_shipment_id(temp_db):
    """Test 7: Tracking non-existent shipment returns clear error."""
    track_res = track_shipment(shipment_id="SHP-NONEXISTENT999", db_path=temp_db)
    assert track_res["success"] is False
    assert track_res["error_code"] == "SHIPMENT_NOT_FOUND"
    assert "not found" in track_res["message"].lower()


def test_12_invalid_shipment_status_transition(temp_db):
    """Test 12: Validate permitted status transitions and reject invalid ones."""
    create_res = create_shipment(
        origin="Chennai",
        destination="Bengaluru",
        product="Laptop",
        quantity=2,
        db_path=temp_db,
    )
    shipment_id = create_res["data"]["shipment_id"]

    # Invalid: CREATED -> DELIVERED (Must go through IN_TRANSIT, OUT_FOR_DELIVERY)
    bad_res = update_shipment_status(
        shipment_id=shipment_id,
        new_status=STATUS_DELIVERED,
        db_path=temp_db,
    )
    assert bad_res["success"] is False
    assert bad_res["error_code"] == "INVALID_STATUS_TRANSITION"

    # Valid: CREATED -> IN_TRANSIT
    ok_transit = update_shipment_status(
        shipment_id=shipment_id,
        new_status=STATUS_IN_TRANSIT,
        db_path=temp_db,
    )
    assert ok_transit["success"] is True
    assert ok_transit["data"]["status"] == STATUS_IN_TRANSIT

    # Valid: IN_TRANSIT -> OUT_FOR_DELIVERY
    ok_out = update_shipment_status(
        shipment_id=shipment_id,
        new_status=STATUS_OUT_FOR_DELIVERY,
        db_path=temp_db,
    )
    assert ok_out["success"] is True

    # Valid: OUT_FOR_DELIVERY -> DELIVERED
    ok_delivered = update_shipment_status(
        shipment_id=shipment_id,
        new_status=STATUS_DELIVERED,
        db_path=temp_db,
    )
    assert ok_delivered["success"] is True

    # Invalid: DELIVERED -> CREATED (terminal state cannot transition)
    terminal_res = update_shipment_status(
        shipment_id=shipment_id,
        new_status=STATUS_CREATED,
        db_path=temp_db,
    )
    assert terminal_res["success"] is False
    assert terminal_res["error_code"] == "INVALID_STATUS_TRANSITION"


def test_13_database_consistency(temp_db):
    """
    Test 13: Database consistency under errors.
    Verify transactions roll back cleanly when a check constraint or failure occurs.
    """
    # Attempt to ship more than available stock
    fail_res = create_shipment(
        origin="Chennai",
        destination="Bengaluru",
        product="Headphones",
        quantity=999,  # Only 30 available
        db_path=temp_db,
    )
    assert fail_res["success"] is False
    assert fail_res["error_code"] == "INSUFFICIENT_STOCK"

    # Verify no shipment was created and inventory was NOT altered
    conn = get_connection(temp_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS count FROM shipments WHERE product_name = 'Headphones';")
        assert cursor.fetchone()["count"] == 0

        cursor.execute("SELECT available_quantity FROM inventory WHERE product_name = 'Headphones';")
        assert cursor.fetchone()["available_quantity"] == 30
    finally:
        conn.close()
