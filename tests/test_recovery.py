"""
Tests for self-healing, retry bounded recovery, and duplicate prevention.
Covers:
- Test 9: Duplicate shipment prevention during retries.
- Test 10: Temporary failure and successful recovery.
- Test 11: Recovery exhaustion.
"""

import pytest
import sqlite3
from logistics.recovery import (
    execute_with_recovery,
    set_simulated_failures,
    get_simulated_failures,
    TransientLogisticsError,
)
from logistics.shipments import create_shipment, track_shipment
from logistics.inventory import check_inventory
from logistics.database import get_connection


def test_9_duplicate_shipment_prevention_during_retries(temp_db):
    """
    Test 9: Verify duplicate shipment creation is prevented during retries.
    Using the same idempotency key returns the existing shipment without double-deduction.
    """
    idempotency_key = "IDEMP-TEST-RETRIES-001"

    # Initial creation
    res1 = create_shipment(
        origin="Chennai",
        destination="Bengaluru",
        product="Laptop",
        quantity=5,
        idempotency_key=idempotency_key,
        db_path=temp_db,
    )
    assert res1["success"] is True
    shipment_id_1 = res1["data"]["shipment_id"]

    # Verify inventory was deducted once: 50 - 5 = 45
    inv_mid = check_inventory("Laptop", 1, db_path=temp_db)
    assert inv_mid["data"]["available_quantity"] == 45

    # Simulated retry with exact same idempotency key
    res2 = create_shipment(
        origin="Chennai",
        destination="Bengaluru",
        product="Laptop",
        quantity=5,
        idempotency_key=idempotency_key,
        db_path=temp_db,
    )
    assert res2["success"] is True
    assert res2["data"]["shipment_id"] == shipment_id_1
    assert "duplicate request detected" in res2["message"].lower()

    # Verify inventory was NOT deducted a second time
    inv_after = check_inventory("Laptop", 1, db_path=temp_db)
    assert inv_after["data"]["available_quantity"] == 45

    # Verify database has exactly 1 shipment record
    conn = get_connection(temp_db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS count FROM shipments WHERE idempotency_key = ?;", (idempotency_key,))
        assert cursor.fetchone()["count"] == 1
    finally:
        conn.close()


def test_10_temporary_failure_and_successful_recovery(temp_db):
    """
    Test 10: Simulate 1 transient failure followed by self-healing recovery.
    Verifies that execute_with_recovery catches the transient error, applies backoff,
    retries, succeeds, and verifies database state.
    """
    # Configure 1 transient failure before recovery
    result = execute_with_recovery(
        create_shipment,
        origin="Chennai",
        destination="Bengaluru",
        product="Phone",
        quantity=4,
        max_attempts=3,
        backoff_base=0.01,  # Fast backoff for test speed
        operation_name="create_shipment_healing_test",
        simulate_fail_count=1,
        db_path=temp_db,
    )

    assert result["success"] is True
    assert "shipment_id" in result["data"]
    shipment_id = result["data"]["shipment_id"]

    # Verify database state was preserved and shipment exists
    track_res = track_shipment(shipment_id=shipment_id, db_path=temp_db)
    assert track_res["success"] is True
    assert track_res["data"]["quantity"] == 4

    # Verify self-healing activity was recorded in SQLite
    conn = get_connection(temp_db)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT status, recovery_attempted, recovery_success
            FROM agent_activity
            WHERE tool_name = 'create_shipment_healing_test' AND status = 'RECOVERY_SUCCESS';
        """)
        row = cursor.fetchone()
        assert row is not None
        assert row["recovery_attempted"] == 1
        assert row["recovery_success"] == 1
    finally:
        conn.close()


def test_11_recovery_exhaustion(temp_db):
    """
    Test 11: When transient failures exceed maximum retry budget (e.g. 5 failures with max 3 attempts),
    recovery halts, logs failure, and honestly reports RECOVERY_EXHAUSTED without false success.
    """
    result = execute_with_recovery(
        create_shipment,
        origin="Chennai",
        destination="Bengaluru",
        product="Laptop",
        quantity=3,
        max_attempts=3,
        backoff_base=0.01,
        operation_name="exhaustion_test",
        simulate_fail_count=5,  # Exceeds max 3 attempts
        db_path=temp_db,
    )

    assert result["success"] is False
    assert result["error_code"] == "RECOVERY_EXHAUSTED"
    assert "exhausted" in result["message"].lower()

    # Reset failure counter
    set_simulated_failures(0)
