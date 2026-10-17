"""
Inventory management tools for the Logistics Handler AI Agent.
Handles stock checking, atomic deductions, and product normalization.
"""

from typing import Optional, Dict, Any, List
from logistics.database import get_connection, init_db
from logistics.logging_utils import format_result, log_activity


def normalize_product_name(product: str) -> str:
    """
    Normalize product strings to canonical names (e.g., handles plurals and casing).
    'laptops' -> 'Laptop', 'laptop' -> 'Laptop'
    'phones' -> 'Phone', 'phone' -> 'Phone'
    'headphones' -> 'Headphones', 'headphone' -> 'Headphones'
    """
    clean = product.strip().lower()
    mapping = {
        "laptop": "Laptop",
        "laptops": "Laptop",
        "notebook": "Laptop",
        "phone": "Phone",
        "phones": "Phone",
        "smartphone": "Phone",
        "smartphones": "Phone",
        "headphone": "Headphones",
        "headphones": "Headphones",
        "earphone": "Headphones",
        "earphones": "Headphones",
    }
    return mapping.get(clean, product.strip().capitalize())


def check_inventory(
    product: str,
    quantity: int,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Tool: check_inventory(product, quantity)
    - Check available stock in SQLite.
    - Reject invalid quantities (must be an integer > 0).
    - Handle unknown products.
    - Return structured results.
    """
    action_name = "CHECK_INVENTORY"

    # Input validation: Quantity
    try:
        qty_int = int(quantity)
        if qty_int <= 0:
            msg = f"Invalid quantity '{quantity}'. Quantity must be a positive integer greater than zero."
            log_activity(
                action=action_name,
                tool_name="check_inventory",
                status="FAILURE",
                details={"product": product, "quantity": quantity, "reason": msg},
                error_code="INVALID_QUANTITY",
                db_path=db_path,
            )
            return format_result(
                success=False,
                message=msg,
                data={"product": product, "requested_quantity": quantity},
                error_code="INVALID_QUANTITY",
            )
    except (ValueError, TypeError):
        msg = f"Invalid quantity '{quantity}'. Quantity must be an integer."
        log_activity(
            action=action_name,
            tool_name="check_inventory",
            status="FAILURE",
            details={"product": product, "quantity": quantity, "reason": msg},
            error_code="INVALID_QUANTITY",
            db_path=db_path,
        )
        return format_result(
            success=False,
            message=msg,
            data={"product": product, "requested_quantity": quantity},
            error_code="INVALID_QUANTITY",
        )

    # Input validation: Product string
    if not product or not isinstance(product, str) or not product.strip():
        msg = "Product name cannot be empty."
        log_activity(
            action=action_name,
            tool_name="check_inventory",
            status="FAILURE",
            details={"product": product, "reason": msg},
            error_code="INVALID_PRODUCT",
            db_path=db_path,
        )
        return format_result(
            success=False,
            message=msg,
            error_code="INVALID_PRODUCT",
        )

    canonical_product = normalize_product_name(product)
    init_db(db_path)
    conn = get_connection(db_path)

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT product_id, product_name, available_quantity, reserved_quantity
            FROM inventory
            WHERE product_name = ? COLLATE NOCASE;
        """, (canonical_product,))
        row = cursor.fetchone()

        if not row:
            msg = f"Product '{product}' is not in the inventory catalog."
            log_activity(
                action=action_name,
                tool_name="check_inventory",
                status="FAILURE",
                details={"product": product, "reason": msg},
                error_code="UNKNOWN_PRODUCT",
                db_path=db_path,
            )
            return format_result(
                success=False,
                message=msg,
                data={"product": product, "requested_quantity": qty_int},
                error_code="UNKNOWN_PRODUCT",
            )

        available = row["available_quantity"]
        is_sufficient = available >= qty_int

        if is_sufficient:
            msg = f"Inventory check passed: {qty_int} units of '{row['product_name']}' are available in stock ({available} in total stock)."
            log_activity(
                action=action_name,
                tool_name="check_inventory",
                status="SUCCESS",
                details={
                    "product": row["product_name"],
                    "requested": qty_int,
                    "available": available,
                    "is_sufficient": True,
                },
                db_path=db_path,
            )
            return format_result(
                success=True,
                message=msg,
                data={
                    "product_id": row["product_id"],
                    "product_name": row["product_name"],
                    "available_quantity": available,
                    "requested_quantity": qty_int,
                    "is_sufficient": True,
                },
            )
        else:
            msg = f"Insufficient stock for '{row['product_name']}': requested {qty_int}, but only {available} units available."
            log_activity(
                action=action_name,
                tool_name="check_inventory",
                status="FAILURE",
                details={
                    "product": row["product_name"],
                    "requested": qty_int,
                    "available": available,
                    "is_sufficient": False,
                },
                error_code="INSUFFICIENT_STOCK",
                db_path=db_path,
            )
            return format_result(
                success=False,
                message=msg,
                data={
                    "product_id": row["product_id"],
                    "product_name": row["product_name"],
                    "available_quantity": available,
                    "requested_quantity": qty_int,
                    "is_sufficient": False,
                },
                error_code="INSUFFICIENT_STOCK",
            )
    finally:
        conn.close()


def get_inventory(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Tool: get_inventory()
    - Return the current inventory catalog with available and reserved quantities.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT product_id, product_name, available_quantity, reserved_quantity, updated_at
            FROM inventory
            ORDER BY product_name ASC;
        """)
        rows = cursor.fetchall()
        items: List[Dict[str, Any]] = [
            {
                "product_id": r["product_id"],
                "product_name": r["product_name"],
                "available_quantity": r["available_quantity"],
                "reserved_quantity": r["reserved_quantity"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

        return format_result(
            success=True,
            message=f"Retrieved inventory with {len(items)} catalog items.",
            data={"inventory": items, "total_items": len(items)},
        )
    except Exception as e:
        return format_result(
            success=False,
            message=f"Failed to query inventory: {str(e)}",
            error_code="DB_QUERY_ERROR",
        )
    finally:
        conn.close()
