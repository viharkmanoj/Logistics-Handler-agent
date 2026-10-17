"""
Shipment management module for the Logistics Handler AI Agent.
Handles shipment creation, atomic inventory deduction, idempotency protection,
status tracking, and status transition enforcement.
"""

import uuid
import json
from datetime import datetime
from typing import Optional, Dict, Any, List

from logistics.config import (
    STATUS_CREATED,
    VALID_TRANSITIONS,
    ALL_STATUSES,
)
from logistics.database import get_connection, init_db
from logistics.inventory import normalize_product_name
from logistics.routing import estimate_delivery
from logistics.logging_utils import format_result, log_activity


def generate_shipment_id() -> str:
    """Generate a clean, professional, unique shipment ID."""
    unique_suffix = uuid.uuid4().hex[:8].upper()
    return f"SHP-{unique_suffix}"


def create_shipment(
    origin: str,
    destination: str,
    product: str,
    quantity: int,
    idempotency_key: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Tool: create_shipment(origin, destination, product, quantity)
    - Validate the input.
    - Check stock availability.
    - Prevent shipment creation if stock is insufficient.
    - Generate a unique shipment ID.
    - Deduct inventory atomically.
    - Persist the shipment in SQLite.
    - Avoid duplicate shipments if an operation is retried (via idempotency_key).
    - Verify database state before reporting success.
    - Return structured result.
    """
    action_name = "CREATE_SHIPMENT"

    # 1. Input Validations
    if not origin or not isinstance(origin, str) or not origin.strip():
        msg = "Origin location cannot be empty."
        log_activity(action=action_name, tool_name="create_shipment", status="FAILURE",
                     details={"reason": msg}, error_code="INVALID_ORIGIN", db_path=db_path)
        return format_result(success=False, message=msg, error_code="INVALID_ORIGIN")

    if not destination or not isinstance(destination, str) or not destination.strip():
        msg = "Destination location cannot be empty."
        log_activity(action=action_name, tool_name="create_shipment", status="FAILURE",
                     details={"reason": msg}, error_code="INVALID_DESTINATION", db_path=db_path)
        return format_result(success=False, message=msg, error_code="INVALID_DESTINATION")

    norm_origin = origin.strip().title()
    norm_dest = destination.strip().title()

    if norm_origin.lower() == norm_dest.lower():
        msg = f"Origin and destination cannot be identical ('{norm_origin}')."
        log_activity(action=action_name, tool_name="create_shipment", status="FAILURE",
                     details={"reason": msg}, error_code="SAME_ORIGIN_DESTINATION", db_path=db_path)
        return format_result(success=False, message=msg, error_code="SAME_ORIGIN_DESTINATION")

    if not product or not isinstance(product, str) or not product.strip():
        msg = "Product name cannot be empty."
        log_activity(action=action_name, tool_name="create_shipment", status="FAILURE",
                     details={"reason": msg}, error_code="INVALID_PRODUCT", db_path=db_path)
        return format_result(success=False, message=msg, error_code="INVALID_PRODUCT")

    try:
        qty_int = int(quantity)
        if qty_int <= 0:
            msg = f"Invalid shipment quantity '{quantity}'. Quantity must be greater than zero."
            log_activity(action=action_name, tool_name="create_shipment", status="FAILURE",
                         details={"quantity": quantity, "reason": msg}, error_code="INVALID_QUANTITY", db_path=db_path)
            return format_result(success=False, message=msg, error_code="INVALID_QUANTITY")
    except (ValueError, TypeError):
        msg = f"Invalid shipment quantity '{quantity}'. Quantity must be an integer."
        log_activity(action=action_name, tool_name="create_shipment", status="FAILURE",
                     details={"quantity": quantity, "reason": msg}, error_code="INVALID_QUANTITY", db_path=db_path)
        return format_result(success=False, message=msg, error_code="INVALID_QUANTITY")

    canonical_product = normalize_product_name(product)
    init_db(db_path)
    conn = get_connection(db_path)

    # 2. Check Idempotency (prevent duplicate creation on retries)
    if idempotency_key:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT shipment_id, response_payload
                FROM idempotency_records
                WHERE idempotency_key = ?;
            """, (idempotency_key,))
            existing = cursor.fetchone()
            if existing:
                cached_data = json.loads(existing["response_payload"])
                log_activity(
                    action=action_name,
                    tool_name="create_shipment",
                    status="SUCCESS",
                    details={"idempotency_hit": True, "shipment_id": existing["shipment_id"]},
                    db_path=db_path,
                )
                return format_result(
                    success=True,
                    message=f"Duplicate request detected with idempotency key '{idempotency_key}'. Returning existing shipment {existing['shipment_id']}.",
                    data=cached_data,
                )
        except Exception as e:
            # Continue if idempotency check failed
            pass

    # 3. Atomic Transaction: Check Stock -> Deduct Stock -> Insert Shipment -> Save Idempotency
    shipment_id = generate_shipment_id()
    delivery_est = estimate_delivery(norm_origin, norm_dest, db_path=db_path)
    est_date = delivery_est.get("data", {}).get("estimated_delivery_date", "Pending")

    try:
        with conn:
            cursor = conn.cursor()

            # Acquire lock and check inventory
            cursor.execute("""
                SELECT product_id, product_name, available_quantity
                FROM inventory
                WHERE product_name = ? COLLATE NOCASE;
            """, (canonical_product,))
            inv_row = cursor.fetchone()

            if not inv_row:
                msg = f"Product '{product}' (canonical: '{canonical_product}') is not found in the inventory catalog."
                log_activity(action=action_name, tool_name="create_shipment", status="FAILURE",
                             details={"product": product, "reason": msg}, error_code="UNKNOWN_PRODUCT", db_path=db_path)
                return format_result(success=False, message=msg, error_code="UNKNOWN_PRODUCT")

            current_stock = inv_row["available_quantity"]
            if current_stock < qty_int:
                msg = f"Cannot create shipment: Insufficient stock for '{inv_row['product_name']}'. Requested {qty_int}, available {current_stock}."
                log_activity(action=action_name, tool_name="create_shipment", status="FAILURE",
                             details={"product": inv_row["product_name"], "requested": qty_int, "available": current_stock},
                             error_code="INSUFFICIENT_STOCK", db_path=db_path)
                return format_result(
                    success=False,
                    message=msg,
                    data={"product": inv_row["product_name"], "available": current_stock, "requested": qty_int},
                    error_code="INSUFFICIENT_STOCK",
                )

            # Deduct inventory atomically
            cursor.execute("""
                UPDATE inventory
                SET available_quantity = available_quantity - ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE product_name = ? COLLATE NOCASE AND available_quantity >= ?;
            """, (qty_int, canonical_product, qty_int))

            if cursor.rowcount == 0:
                msg = "Inventory deduction failed due to concurrent modification. Operation rolled back."
                return format_result(success=False, message=msg, error_code="CONCURRENCY_ERROR")

            # Insert Shipment record
            cursor.execute("""
                INSERT INTO shipments (
                    shipment_id, origin, destination, product_name, quantity,
                    status, idempotency_key, estimated_delivery
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                shipment_id,
                norm_origin,
                norm_dest,
                inv_row["product_name"],
                qty_int,
                STATUS_CREATED,
                idempotency_key,
                est_date,
            ))

            result_data = {
                "shipment_id": shipment_id,
                "origin": norm_origin,
                "destination": norm_dest,
                "product": inv_row["product_name"],
                "quantity": qty_int,
                "status": STATUS_CREATED,
                "estimated_delivery": est_date,
                "remaining_stock": current_stock - qty_int,
                "created_at": datetime.now().isoformat(),
            }

            # Save idempotency record if key provided
            if idempotency_key:
                cursor.execute("""
                    INSERT INTO idempotency_records (idempotency_key, shipment_id, response_payload)
                    VALUES (?, ?, ?);
                """, (idempotency_key, shipment_id, json.dumps(result_data)))

        # 4. Post-Transaction State Verification
        # Verify directly in SQLite that the shipment exists and inventory was decremented
        verification_cursor = conn.cursor()
        verification_cursor.execute("SELECT shipment_id, status FROM shipments WHERE shipment_id = ?;", (shipment_id,))
        verified_shipment = verification_cursor.fetchone()

        if not verified_shipment:
            msg = f"Fatal verification failure: Shipment {shipment_id} was not confirmed in database."
            log_activity(action=action_name, tool_name="create_shipment", status="FAILURE",
                         details={"shipment_id": shipment_id}, error_code="DB_VERIFICATION_FAILED", db_path=db_path)
            return format_result(success=False, message=msg, error_code="DB_VERIFICATION_FAILED")

        # Success confirmation
        success_msg = f"Shipment {shipment_id} successfully created and verified in database. Status: {STATUS_CREATED}."
        log_activity(
            action=action_name,
            tool_name="create_shipment",
            status="SUCCESS",
            details=result_data,
            db_path=db_path,
        )

        return format_result(
            success=True,
            message=success_msg,
            data=result_data,
        )

    except Exception as e:
        msg = f"Database error during shipment creation: {str(e)}"
        log_activity(action=action_name, tool_name="create_shipment", status="FAILURE",
                     details={"error": str(e)}, error_code="DB_ERROR", db_path=db_path)
        return format_result(success=False, message=msg, error_code="DB_ERROR")
    finally:
        conn.close()


def track_shipment(shipment_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Tool: track_shipment(shipment_id)
    - Retrieve shipment information from SQLite.
    - Return shipment status and shipment details.
    - Handle unknown shipment IDs with clear structured error.
    """
    action_name = "TRACK_SHIPMENT"

    if not shipment_id or not isinstance(shipment_id, str) or not shipment_id.strip():
        msg = "Shipment ID cannot be empty."
        log_activity(action=action_name, tool_name="track_shipment", status="FAILURE",
                     details={"reason": msg}, error_code="INVALID_SHIPMENT_ID", db_path=db_path)
        return format_result(success=False, message=msg, error_code="INVALID_SHIPMENT_ID")

    clean_id = shipment_id.strip().upper()
    init_db(db_path)
    conn = get_connection(db_path)

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT shipment_id, origin, destination, product_name, quantity,
                   status, idempotency_key, estimated_delivery, created_at, updated_at
            FROM shipments
            WHERE shipment_id = ?;
        """, (clean_id,))
        row = cursor.fetchone()

        if not row:
            msg = f"Shipment with ID '{clean_id}' was not found in the records."
            log_activity(action=action_name, tool_name="track_shipment", status="FAILURE",
                         details={"shipment_id": clean_id, "reason": msg}, error_code="SHIPMENT_NOT_FOUND", db_path=db_path)
            return format_result(
                success=False,
                message=msg,
                data={"shipment_id": clean_id},
                error_code="SHIPMENT_NOT_FOUND",
            )

        data = {
            "shipment_id": row["shipment_id"],
            "origin": row["origin"],
            "destination": row["destination"],
            "product": row["product_name"],
            "quantity": row["quantity"],
            "status": row["status"],
            "estimated_delivery": row["estimated_delivery"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

        msg = f"Shipment {clean_id} is currently {row['status']}. Shipping {row['quantity']}x {row['product_name']} from {row['origin']} to {row['destination']}."
        log_activity(action=action_name, tool_name="track_shipment", status="SUCCESS",
                     details=data, db_path=db_path)

        return format_result(
            success=True,
            message=msg,
            data=data,
        )
    finally:
        conn.close()


def update_shipment_status(
    shipment_id: str,
    new_status: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Tool: update_shipment_status(shipment_id, status)
    - Validate permitted status transitions.
    - Persist status updates in SQLite.
    - Log the changes.
    """
    action_name = "UPDATE_SHIPMENT_STATUS"

    if not shipment_id or not isinstance(shipment_id, str) or not shipment_id.strip():
        return format_result(success=False, message="Shipment ID cannot be empty.", error_code="INVALID_SHIPMENT_ID")

    clean_id = shipment_id.strip().upper()
    clean_status = new_status.strip().upper()

    if clean_status not in ALL_STATUSES:
        msg = f"Invalid status '{new_status}'. Allowed statuses are: {', '.join(ALL_STATUSES)}"
        log_activity(action=action_name, tool_name="update_shipment_status", status="FAILURE",
                     details={"shipment_id": clean_id, "invalid_status": new_status},
                     error_code="INVALID_STATUS", db_path=db_path)
        return format_result(success=False, message=msg, error_code="INVALID_STATUS")

    init_db(db_path)
    conn = get_connection(db_path)

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT shipment_id, status FROM shipments WHERE shipment_id = ?;", (clean_id,))
        row = cursor.fetchone()

        if not row:
            msg = f"Shipment '{clean_id}' does not exist."
            log_activity(action=action_name, tool_name="update_shipment_status", status="FAILURE",
                         details={"shipment_id": clean_id}, error_code="SHIPMENT_NOT_FOUND", db_path=db_path)
            return format_result(success=False, message=msg, error_code="SHIPMENT_NOT_FOUND")

        current_status = row["status"]

        # If it's already in the target status, report as idempotent success
        if current_status == clean_status:
            return format_result(
                success=True,
                message=f"Shipment {clean_id} is already in status '{clean_status}'.",
                data={"shipment_id": clean_id, "current_status": current_status, "new_status": clean_status},
            )

        # Validate permitted transition
        allowed_next = VALID_TRANSITIONS.get(current_status, [])
        if clean_status not in allowed_next:
            msg = (
                f"Illegal status transition for shipment {clean_id}: "
                f"Cannot transition from '{current_status}' to '{clean_status}'. "
                f"Permitted next statuses: {allowed_next if allowed_next else 'None (Terminal state)'}."
            )
            log_activity(action=action_name, tool_name="update_shipment_status", status="FAILURE",
                         details={"shipment_id": clean_id, "current_status": current_status, "attempted_status": clean_status},
                         error_code="INVALID_STATUS_TRANSITION", db_path=db_path)
            return format_result(
                success=False,
                message=msg,
                data={"shipment_id": clean_id, "current_status": current_status, "allowed_transitions": allowed_next},
                error_code="INVALID_STATUS_TRANSITION",
            )

        with conn:
            cursor.execute("""
                UPDATE shipments
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE shipment_id = ?;
            """, (clean_status, clean_id))

        msg = f"Shipment {clean_id} successfully transitioned from '{current_status}' to '{clean_status}'."
        log_activity(action=action_name, tool_name="update_shipment_status", status="SUCCESS",
                     details={"shipment_id": clean_id, "previous_status": current_status, "status": clean_status},
                     db_path=db_path)

        return format_result(
            success=True,
            message=msg,
            data={"shipment_id": clean_id, "previous_status": current_status, "status": clean_status},
        )
    finally:
        conn.close()


def get_shipments(db_path: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Retrieve all recent shipments for reporting and dashboard display."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT shipment_id, origin, destination, product_name, quantity,
                   status, estimated_delivery, created_at, updated_at
            FROM shipments
            ORDER BY id DESC
            LIMIT ?;
        """ if "id" in [c[1] for c in cursor.execute("PRAGMA table_info(shipments);").fetchall()] else """
            SELECT shipment_id, origin, destination, product_name, quantity,
                   status, estimated_delivery, created_at, updated_at
            FROM shipments
            ORDER BY created_at DESC
            LIMIT ?;
        """, (limit,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
