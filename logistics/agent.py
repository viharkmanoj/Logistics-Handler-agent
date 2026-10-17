"""
Google ADK (Agent Development Kit) & Google Gemini AI Agent Orchestrator.
Coordinates warehouse inventory, shipment creation, tracking, and recovery
using Google's official Agent Development Kit (google-adk) and Gemini models.
Provides a clear, deterministic Demo Mode fallback when Google credentials are not set.
"""

import os
import re
import json
import uuid
from typing import Dict, Any, List, Optional, Callable

# Google ADK (Agent Development Kit) and Google GenAI imports
import google.adk as adk
from google.adk import Agent as ADKAgent, Runner as ADKRunner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from logistics.config import GEMINI_API_KEY, GOOGLE_API_KEY, GEMINI_MODEL
from logistics.inventory import check_inventory, get_inventory, normalize_product_name
from logistics.shipments import create_shipment, track_shipment, update_shipment_status
from logistics.routing import estimate_delivery
from logistics.logging_utils import get_agent_activity, log_activity, format_result
from logistics.recovery import execute_with_recovery

# Active thread-local DB path override for test isolation
_CURRENT_DB_PATH: Optional[str] = None


def set_active_db_path(db_path: Optional[str]) -> None:
    """Set active database path context for tool execution."""
    global _CURRENT_DB_PATH
    _CURRENT_DB_PATH = db_path


def get_active_db_path() -> Optional[str]:
    """Retrieve active database path context."""
    global _CURRENT_DB_PATH
    return _CURRENT_DB_PATH


# ============================================================================
# Core Domain Tool Dispatcher
# ============================================================================

def dispatch_tool(tool_name: str, arguments: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Central tool executor that wraps calls in bounded self-healing recovery,
    idempotency enforcement, and audit feedback logging.
    """
    active_db = db_path or get_active_db_path()

    if tool_name == "check_inventory":
        return execute_with_recovery(
            check_inventory,
            product=arguments.get("product", ""),
            quantity=arguments.get("quantity", 0),
            operation_name="check_inventory",
            db_path=active_db,
        )
    elif tool_name == "create_shipment":
        return execute_with_recovery(
            create_shipment,
            origin=arguments.get("origin", ""),
            destination=arguments.get("destination", ""),
            product=arguments.get("product", ""),
            quantity=arguments.get("quantity", 0),
            idempotency_key=arguments.get("idempotency_key"),
            operation_name="create_shipment",
            db_path=active_db,
        )
    elif tool_name == "track_shipment":
        return execute_with_recovery(
            track_shipment,
            shipment_id=arguments.get("shipment_id", ""),
            operation_name="track_shipment",
            db_path=active_db,
        )
    elif tool_name == "estimate_delivery":
        return execute_with_recovery(
            estimate_delivery,
            origin=arguments.get("origin", ""),
            destination=arguments.get("destination", ""),
            operation_name="estimate_delivery",
            db_path=active_db,
        )
    elif tool_name == "get_inventory":
        return execute_with_recovery(
            get_inventory,
            operation_name="get_inventory",
            db_path=active_db,
        )
    elif tool_name == "update_shipment_status":
        return execute_with_recovery(
            update_shipment_status,
            shipment_id=arguments.get("shipment_id", ""),
            new_status=arguments.get("status", ""),
            operation_name="update_shipment_status",
            db_path=active_db,
        )
    elif tool_name == "get_agent_activity":
        limit = arguments.get("limit", 20)
        return get_agent_activity(limit=limit, db_path=active_db)
    else:
        return format_result(
            success=False,
            message=f"Unknown tool '{tool_name}' requested.",
            error_code="UNKNOWN_TOOL",
        )


# ============================================================================
# Google ADK Tools (Standard Callable Functions with Type Annotations)
# ============================================================================

def adk_check_inventory(product: str, quantity: int) -> Dict[str, Any]:
    """Check stock availability for a specific product and requested quantity.

    Args:
        product: The product name (e.g., 'Laptop', 'Phone', 'Headphones').
        quantity: The number of units to verify stock for.

    Returns:
        Structured result with availability status and remaining stock.
    """
    return dispatch_tool("check_inventory", {"product": product, "quantity": quantity})


def adk_create_shipment(
    origin: str,
    destination: str,
    product: str,
    quantity: int,
    idempotency_key: str = "",
) -> Dict[str, Any]:
    """Create a new verified shipment. Validates stock, deducts inventory atomically, and persists to SQLite.

    Args:
        origin: Origin city/location.
        destination: Destination city/location.
        product: Product name to be shipped.
        quantity: Quantity of units to ship.
        idempotency_key: Optional unique idempotency key to prevent duplicate shipments on retry.

    Returns:
        Structured result with verified shipment ID, status, and delivery date.
    """
    return dispatch_tool("create_shipment", {
        "origin": origin,
        "destination": destination,
        "product": product,
        "quantity": quantity,
        "idempotency_key": idempotency_key or None,
    })


def adk_track_shipment(shipment_id: str) -> Dict[str, Any]:
    """Track the status and timeline details of an existing shipment by shipment ID.

    Args:
        shipment_id: The unique shipment ID (e.g. SHP-XXXXXXXX).

    Returns:
        Structured result with current shipment status, route, and timeline.
    """
    return dispatch_tool("track_shipment", {"shipment_id": shipment_id})


def adk_estimate_delivery(origin: str, destination: str) -> Dict[str, Any]:
    """Estimate transit distance, transit days, and expected delivery date between two locations.

    Args:
        origin: Origin location.
        destination: Destination location.

    Returns:
        Distance, transit days, and estimated arrival date with provider labeling.
    """
    return dispatch_tool("estimate_delivery", {"origin": origin, "destination": destination})


def adk_get_inventory() -> Dict[str, Any]:
    """Retrieve the current overall warehouse inventory catalog and available stock levels.

    Returns:
        Full list of catalog items with available and reserved quantities.
    """
    return dispatch_tool("get_inventory", {})


def adk_update_shipment_status(shipment_id: str, status: str) -> Dict[str, Any]:
    """Update the lifecycle status of a shipment enforcing valid state machine transitions.

    Args:
        shipment_id: The shipment ID to update.
        status: Target status (CREATED, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, CANCELLED).

    Returns:
        Confirmation of status update or validation rejection.
    """
    return dispatch_tool("update_shipment_status", {"shipment_id": shipment_id, "status": status})


def adk_get_agent_activity(limit: int = 20) -> Dict[str, Any]:
    """Retrieve recent tool calls, agent execution audit records, and error history.

    Args:
        limit: Number of recent activity entries to retrieve.

    Returns:
        List of recent audit records.
    """
    return dispatch_tool("get_agent_activity", {"limit": limit})


# List of tools exposed to Google ADK Agent
GOOGLE_ADK_TOOLS: List[Callable] = [
    adk_check_inventory,
    adk_create_shipment,
    adk_track_shipment,
    adk_estimate_delivery,
    adk_get_inventory,
    adk_update_shipment_status,
    adk_get_agent_activity,
]


def build_adk_agent(model: str = GEMINI_MODEL) -> ADKAgent:
    """Build and configure a Google ADK Agent instance for logistics orchestration."""
    instruction = (
        "You are the Logistics Coordinator AI Agent built with Google ADK (Agent Development Kit) "
        "and powered by Google Gemini.\n"
        "You manage warehouse inventory, shipment creation, tracking, and delivery estimation.\n\n"
        "CRITICAL RULES:\n"
        "1. Always check stock availability before creating a shipment.\n"
        "2. When creating a shipment, call 'adk_create_shipment' with origin, destination, product, and quantity.\n"
        "3. NEVER invent shipment IDs, stock levels, or delivery dates. Only use data returned by the tools.\n"
        "4. If required parameters (e.g. quantity, origin, destination, product) are missing from the request, "
        "ask the user for clarification before executing.\n"
        "5. Distinguish clearly between successful operations and failed operations.\n"
        "6. Provide clear, professional summaries with shipment IDs, statuses, and delivery dates."
    )
    return ADKAgent(
        name="GoogleADKLogisticsCoordinator",
        model=model,
        instruction=instruction,
        tools=GOOGLE_ADK_TOOLS,
    )


# ============================================================================
# Deterministic Demo Mode Fallback Engine
# ============================================================================

class DemoLogisticsAgent:
    """
    Deterministic rule-based intent parser and orchestrator.
    Active when Google Gemini API keys are unconfigured.
    Transparently reports its mode and DOES NOT claim to use Gemini.
    """

    def __init__(self, mode_label: str = "Demo Mode (Rule-Based Intent Engine)"):
        self.mode_label = mode_label

    def run(self, user_prompt: str, db_path: Optional[str] = None) -> Dict[str, Any]:
        set_active_db_path(db_path)
        prompt = user_prompt.strip()
        executed_tools: List[Dict[str, Any]] = []

        log_activity(
            action="USER_PROMPT_RECEIVED",
            tool_name=None,
            status="INFO",
            details={"prompt": prompt, "framework": "Google ADK Demo Engine"},
            db_path=db_path,
        )

        # 1. Track Shipment: "Track shipment SHP-XXXXXXXX" or "Track SHP-12345678"
        track_match = re.search(r"\b(shp-[a-z0-9]+)\b", prompt, re.IGNORECASE)
        if ("track" in prompt.lower() or "status" in prompt.lower()) and track_match:
            shipment_id = track_match.group(1).upper()
            tool_res = dispatch_tool("track_shipment", {"shipment_id": shipment_id}, db_path=db_path)
            executed_tools.append({"tool": "track_shipment", "args": {"shipment_id": shipment_id}, "result": tool_res})

            if tool_res["success"]:
                d = tool_res["data"]
                response_text = (
                    f"**Shipment Tracking Result**\n\n"
                    f"- **Shipment ID:** `{d['shipment_id']}`\n"
                    f"- **Status:** `{d['status']}`\n"
                    f"- **Route:** {d['origin']} ➔ {d['destination']}\n"
                    f"- **Items:** {d['quantity']}x {d['product']}\n"
                    f"- **Estimated Delivery:** {d['estimated_delivery']}\n"
                    f"- **Created At:** {d['created_at']}\n\n"
                    f"*{self.mode_label}*"
                )
            else:
                response_text = f"**Tracking Failed:** {tool_res['message']}\n\n*{self.mode_label}*"

            return {"response": response_text, "tools_executed": executed_tools, "mode": "demo"}

        # 2. Check failed operations: "Why did my shipment fail?"
        if "fail" in prompt.lower() or "error" in prompt.lower() or "why did" in prompt.lower():
            act_res = dispatch_tool("get_agent_activity", {"limit": 10}, db_path=db_path)
            executed_tools.append({"tool": "get_agent_activity", "args": {"limit": 10}, "result": act_res})

            activities = act_res.get("data", {}).get("activities", [])
            recent_failures = [a for a in activities if a.get("status") == "FAILURE"]

            if recent_failures:
                top_fail = recent_failures[0]
                details = top_fail.get("details", {})
                reason = details.get("reason") or details.get("error") or "Unknown error"
                response_text = (
                    f"**Failure Analysis from Recent Activity Logs:**\n\n"
                    f"- **Action:** `{top_fail.get('action')}`\n"
                    f"- **Error Code:** `{top_fail.get('error_code')}`\n"
                    f"- **Reason:** {reason}\n"
                    f"- **Timestamp:** {top_fail.get('timestamp')}\n\n"
                    f"*{self.mode_label}*"
                )
            else:
                response_text = (
                    f"No recent failure logs found in the activity history. "
                    f"All recent operations were either successful or self-healed.\n\n*{self.mode_label}*"
                )
            return {"response": response_text, "tools_executed": executed_tools, "mode": "demo"}

        # 3. Delivery Estimation: "Estimate delivery time from Chennai to Bengaluru"
        route_match = re.search(r"from\s+([a-zA-Z\s]+?)\s+to\s+([a-zA-Z\s]+)", prompt, re.IGNORECASE)
        if ("estimate" in prompt.lower() or "delivery time" in prompt.lower() or "transit" in prompt.lower()) and route_match:
            origin = route_match.group(1).strip()
            destination = route_match.group(2).strip()
            destination = re.sub(r"\b(and|check|with|for)\b.*$", "", destination, flags=re.IGNORECASE).strip()

            tool_res = dispatch_tool("estimate_delivery", {"origin": origin, "destination": destination}, db_path=db_path)
            executed_tools.append({"tool": "estimate_delivery", "args": {"origin": origin, "destination": destination}, "result": tool_res})

            if tool_res["success"]:
                d = tool_res["data"]
                response_text = (
                    f"**Delivery Estimate**\n\n"
                    f"- **Route:** {d['origin']} ➔ {d['destination']}\n"
                    f"- **Distance:** ~{d['estimated_distance_km']} km\n"
                    f"- **Transit Time:** ~{d['estimated_transit_days']} business day(s) (~{d['estimated_transit_hours']} hrs transit)\n"
                    f"- **Estimated Delivery Date:** {d['estimated_delivery_date']}\n"
                    f"- **Provider:** {d['provider']}\n\n"
                    f"*{self.mode_label}*"
                )
            else:
                response_text = f"**Estimation Failed:** {tool_res['message']}\n\n*{self.mode_label}*"

            return {"response": response_text, "tools_executed": executed_tools, "mode": "demo"}

        # 4. Overall Inventory Query: "How many headphones are available?" or "Show inventory"
        if ("how many" in prompt.lower() or "inventory" in prompt.lower() or "stock" in prompt.lower() or "catalog" in prompt.lower()) and ("ship" not in prompt.lower() and "create" not in prompt.lower()):
            found_prod = None
            for p in ["headphone", "laptop", "phone"]:
                if p in prompt.lower():
                    found_prod = p
                    break

            if found_prod:
                qty_match = re.search(r"\b(\d+)\b", prompt)
                qty = int(qty_match.group(1)) if qty_match else 1
                tool_res = dispatch_tool("check_inventory", {"product": found_prod, "quantity": qty}, db_path=db_path)
                executed_tools.append({"tool": "check_inventory", "args": {"product": found_prod, "quantity": qty}, "result": tool_res})

                if tool_res["success"]:
                    d = tool_res["data"]
                    response_text = (
                        f"**Stock Availability Check**\n\n"
                        f"- **Product:** {d['product_name']}\n"
                        f"- **Available Stock:** {d['available_quantity']} units\n"
                        f"- **Requested Quantity ({qty}):** {'Sufficient' if d['is_sufficient'] else 'Insufficient'}\n\n"
                        f"*{self.mode_label}*"
                    )
                else:
                    response_text = f"**Stock Check Result:** {tool_res['message']}\n\n*{self.mode_label}*"
                return {"response": response_text, "tools_executed": executed_tools, "mode": "demo"}
            else:
                tool_res = dispatch_tool("get_inventory", {}, db_path=db_path)
                executed_tools.append({"tool": "get_inventory", "args": {}, "result": tool_res})
                items = tool_res.get("data", {}).get("inventory", [])
                lines = [f"- **{i['product_name']}:** {i['available_quantity']} available (Reserved: {i['reserved_quantity']})" for i in items]
                response_text = (
                    f"**Current Warehouse Inventory**\n\n" + "\n".join(lines) + f"\n\n*{self.mode_label}*"
                )
                return {"response": response_text, "tools_executed": executed_tools, "mode": "demo"}

        # 5. Shipment Creation Workflow:
        if "ship" in prompt.lower() or "create" in prompt.lower() or "send" in prompt.lower():
            product = None
            for p in ["headphone", "laptop", "phone"]:
                if p in prompt.lower():
                    product = p
                    break

            qty_match = re.search(r"\b(\d+)\b", prompt)
            quantity = int(qty_match.group(1)) if qty_match else None

            route_match = re.search(r"from\s+([a-zA-Z\s]+?)\s+to\s+([a-zA-Z\s]+)", prompt, re.IGNORECASE)
            origin = None
            destination = None
            if route_match:
                origin = route_match.group(1).strip()
                destination = route_match.group(2).strip()
                destination = re.sub(r"\b(and|check|with|for|available|availability)\b.*$", "", destination, flags=re.IGNORECASE).strip()

            missing_fields = []
            if not product:
                missing_fields.append("product (e.g. Laptop, Phone, Headphones)")
            if not quantity:
                missing_fields.append("quantity (e.g. 5)")
            if not origin:
                missing_fields.append("origin city (e.g. Chennai)")
            if not destination:
                missing_fields.append("destination city (e.g. Bengaluru)")

            if missing_fields:
                response_text = (
                    f"**Clarification Needed:**\n"
                    f"To process your shipment request, please provide the missing information:\n"
                    + "\n".join([f"- {f}" for f in missing_fields])
                    + f"\n\n*Example:* 'Create a shipment for 5 laptops from Chennai to Bengaluru.'\n\n*{self.mode_label}*"
                )
                return {"response": response_text, "tools_executed": executed_tools, "mode": "demo"}

            # Multi-step Workflow
            inv_check = dispatch_tool("check_inventory", {"product": product, "quantity": quantity}, db_path=db_path)
            executed_tools.append({"tool": "check_inventory", "args": {"product": product, "quantity": quantity}, "result": inv_check})

            if not inv_check["success"] or not inv_check.get("data", {}).get("is_sufficient"):
                response_text = (
                    f"**Shipment Rejected - Stock Insufficient:**\n\n"
                    f"{inv_check['message']}\n\n"
                    f"Shipment was **not** created. No inventory was deducted.\n\n*{self.mode_label}*"
                )
                return {"response": response_text, "tools_executed": executed_tools, "mode": "demo"}

            ship_res = dispatch_tool(
                "create_shipment",
                {"origin": origin, "destination": destination, "product": product, "quantity": quantity},
                db_path=db_path,
            )
            executed_tools.append({
                "tool": "create_shipment",
                "args": {"origin": origin, "destination": destination, "product": product, "quantity": quantity},
                "result": ship_res,
            })

            if ship_res["success"]:
                d = ship_res["data"]
                response_text = (
                    f"### Shipment Confirmed & Created Successfully!\n\n"
                    f"- **Shipment ID:** `{d['shipment_id']}`\n"
                    f"- **Status:** `{d['status']}`\n"
                    f"- **Product:** {d['quantity']}x {d['product']}\n"
                    f"- **Route:** {d['origin']} ➔ {d['destination']}\n"
                    f"- **Estimated Delivery:** {d['estimated_delivery']}\n"
                    f"- **Remaining Warehouse Stock:** {d['remaining_stock']} units\n\n"
                    f"All details were persisted and verified in SQLite database.\n\n"
                    f"*{self.mode_label}*"
                )
            else:
                response_text = (
                    f"**Shipment Creation Failed:**\n\n"
                    f"{ship_res['message']}\n"
                    f"Database transaction was safely rolled back.\n\n*{self.mode_label}*"
                )

            return {"response": response_text, "tools_executed": executed_tools, "mode": "demo"}

        # Fallback / Help
        response_text = (
            f"**Logistics Handler AI Agent (Google ADK Ready)**\n\n"
            f"I can assist with the following operations:\n"
            f"- 'Create a shipment for 5 laptops from Chennai to Bengaluru and check inventory availability.'\n"
            f"- 'Check stock for 10 laptops.'\n"
            f"- 'Ship 5 phones from Chennai to Bengaluru.'\n"
            f"- 'Track shipment SHP-XXXXXXXX.'\n"
            f"- 'How many headphones are available?'\n"
            f"- 'Estimate delivery time from Chennai to Bengaluru.'\n"
            f"- 'Why did my shipment fail?'\n\n"
            f"*{self.mode_label}*"
        )
        return {"response": response_text, "tools_executed": executed_tools, "mode": "demo"}


# ============================================================================
# Google ADK Logistics Coordinator Agent
# ============================================================================

class LogisticsCoordinatorAgent:
    """
    Primary Coordinator Agent implemented with Google ADK (Agent Development Kit).
    Utilizes Google's Gemini models for intelligent tool orchestration when credentials exist,
    or smoothly delegates to DemoLogisticsAgent when GEMINI_API_KEY is not configured.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = GEMINI_MODEL):
        self.api_key = (api_key or GEMINI_API_KEY or GOOGLE_API_KEY).strip()
        self.model = model
        self.demo_agent = DemoLogisticsAgent()
        self._adk_agent: Optional[ADKAgent] = None
        self._runner: Optional[ADKRunner] = None

    @property
    def is_ai_mode_active(self) -> bool:
        """Verify whether genuine Google Gemini credentials are configured."""
        return bool(self.api_key and not self.api_key.startswith("sk-placeholder") and not self.api_key.startswith("gemini-placeholder"))

    def _get_runner(self) -> ADKRunner:
        """Lazily initialize Google ADK Agent and Runner."""
        if self._runner is None:
            # Set environment variable for Google GenAI / ADK authentication
            os.environ["GEMINI_API_KEY"] = self.api_key
            os.environ["GOOGLE_API_KEY"] = self.api_key

            self._adk_agent = build_adk_agent(model=self.model)
            session_service = InMemorySessionService()
            self._runner = ADKRunner(
                app_name="logistics_handler_adk",
                agent=self._adk_agent,
                session_service=session_service,
                auto_create_session=True,
            )
        return self._runner

    def run(self, user_prompt: str, db_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute logistics instruction via Google ADK + Gemini,
        or via Demo Mode if credentials are absent.
        """
        set_active_db_path(db_path)

        if not self.is_ai_mode_active:
            return self.demo_agent.run(user_prompt, db_path=db_path)

        try:
            runner = self._get_runner()
            user_msg = genai_types.Content(parts=[genai_types.Part(text=user_prompt)])
            session_id = f"session_{uuid.uuid4().hex[:8]}"

            events = runner.run(
                user_id="logistics_operator",
                session_id=session_id,
                new_message=user_msg,
            )

            executed_tools: List[Dict[str, Any]] = []
            text_chunks: List[str] = []

            for event in events:
                # Capture tool invocations
                fn_calls = event.get_function_calls()
                if fn_calls:
                    for fc in fn_calls:
                        executed_tools.append({
                            "tool": fc.name,
                            "args": fc.args,
                        })

                # Capture generated message parts
                if event.message and event.message.parts:
                    for part in event.message.parts:
                        if hasattr(part, "text") and part.text:
                            text_chunks.append(part.text)

            final_text = "\n\n".join(text_chunks).strip() or "Request processed via Google ADK."

            return {
                "response": final_text,
                "tools_executed": executed_tools,
                "mode": "google_adk_gemini",
                "framework": "Google ADK (Agent Development Kit)",
                "model": self.model,
            }

        except Exception as e:
            # If Google API call encounters auth or network issue, fail gracefully to Demo Engine
            demo_res = self.demo_agent.run(user_prompt, db_path=db_path)
            demo_res["warning"] = f"Google ADK Gemini notice ({str(e)}). Active mode: Demo Engine."
            return demo_res
