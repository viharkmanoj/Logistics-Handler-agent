"""
Logging and feedback utilities for the Logistics Handler AI Agent.
Records operations, tool executions, feedback loops, and self-healing events in SQLite.
"""

import json
from typing import Optional, Dict, Any, List
from logistics.database import get_connection, init_db


def format_result(
    success: bool,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    error_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Standardized result envelope across all tools and agent workflows."""
    return {
        "success": success,
        "message": message,
        "data": data if data is not None else {},
        "error_code": error_code,
    }


def log_activity(
    action: str,
    tool_name: Optional[str] = None,
    status: str = "SUCCESS",
    details: Optional[Any] = None,
    error_code: Optional[str] = None,
    recovery_attempted: int = 0,
    recovery_success: int = 0,
    db_path: Optional[str] = None,
) -> int:
    """
    Log an agent action, tool invocation, feedback check, or recovery attempt.
    Returns the inserted log record ID.
    """
    init_db(db_path)
    conn = get_connection(db_path)

    # Convert complex details into JSON string if needed
    details_str = details
    if isinstance(details, (dict, list)):
        try:
            details_str = json.dumps(details)
        except Exception:
            details_str = str(details)

    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO agent_activity (
                    action, tool_name, status, details, error_code,
                    recovery_attempted, recovery_success
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (
                action,
                tool_name,
                status,
                details_str,
                error_code,
                recovery_attempted,
                recovery_success,
            ))
            return cursor.lastrowid
    finally:
        conn.close()


def get_agent_activity(
    limit: int = 50,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrieve recent tool calls, actions, errors, and recovery attempts.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, action, tool_name, status, details,
                   error_code, recovery_attempted, recovery_success
            FROM agent_activity
            ORDER BY id DESC
            LIMIT ?;
        """, (limit,))
        rows = cursor.fetchall()

        activities: List[Dict[str, Any]] = []
        for row in rows:
            details_val = row["details"]
            try:
                # Parse JSON if possible
                if details_val and (details_val.startswith("{") or details_val.startswith("[")):
                    parsed = json.loads(details_val)
                    details_val = parsed
            except Exception:
                pass

            activities.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "action": row["action"],
                "tool_name": row["tool_name"],
                "status": row["status"],
                "details": details_val,
                "error_code": row["error_code"],
                "recovery_attempted": bool(row["recovery_attempted"]),
                "recovery_success": bool(row["recovery_success"]),
            })

        return format_result(
            success=True,
            message=f"Retrieved {len(activities)} recent agent activities.",
            data={"activities": activities, "count": len(activities)},
        )
    except Exception as e:
        return format_result(
            success=False,
            message=f"Failed to retrieve agent activity: {str(e)}",
            error_code="DB_QUERY_ERROR",
        )
    finally:
        conn.close()
