"""
AI Agent orchestration module for the Logistics Handler.
Provides an OpenAI Agents SDK / Tool-Calling Coordinator Agent with a robust,
transparent Demo Mode fallback when OPENAI_API_KEY is not configured.
"""

import os
import re
import json
from typing import Dict, Any, List, Optional, Tuple

from logistics.config import OPENAI_API_KEY, OPENAI_MODEL
from logistics.inventory import check_inventory, get_inventory, normalize_product_name
from logistics.shipments import create_shipment, track_shipment, update_shipment_status
from logistics.routing import estimate_delivery
from logistics.logging_utils import get_agent_activity, log_activity, format_result
from logistics.recovery import execute_with_recovery


# Tool definitions matching OpenAI Function Calling schema
LOGISTICS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_inventory",
            "description": "Check stock availability for a specific product and requested quantity. Returns availability status and remaining stock.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "The product name (e.g., 'Laptop', 'Phone', 'Headphones')."},
                    "quantity": {"type": "integer", "description": "The number of units to verify stock for."},
                },
                "required": ["product", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_shipment",
            "description": "Create a new verified shipment. Validates stock, deducts inventory atomically, and persists to database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "Origin city/location."},
                    "destination": {"type": "string", "description": "Destination city/location."},
                    "product": {"type": "string", "description": "Product name to be shipped."},
                    "quantity": {"type": "integer", "description": "Quantity to ship."},
                    "idempotency_key": {"type": "string", "description": "Optional unique idempotency key to prevent duplicate shipments on retry."},
                },
                "required": ["origin", "destination", "product", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "track_shipment",
            "description": "Track the status and timeline details of an existing shipment by shipment ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "shipment_id": {"type": "string", "description": "The unique shipment ID (e.g. SHP-XXXXXXXX)."},
                },
                "required": ["shipment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_delivery",
            "description": "Estimate transit distance, transit days, and expected delivery date between two locations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "Origin location."},
                    "destination": {"type": "string", "description": "Destination location."},
                },
                "required": ["origin", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inventory",
            "description": "Retrieve the current overall warehouse inventory catalog and available stock levels.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_shipment_status",
            "description": "Update the status of a shipment (e.g., CREATED -> IN_TRANSIT -> OUT_FOR_DELIVERY -> DELIVERED, or CANCELLED). Validates transitions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "shipment_id": {"type": "string", "description": "The shipment ID to update."},
                    "status": {"type": "string", "description": "Target status (CREATED, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, CANCELLED)."},
                },
                "required": ["shipment_id", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_agent_activity",
            "description": "Retrieve recent tool calls, agent execution audit records, and error history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of recent activity entries to retrieve."},
                },
            },
        },
    },
]


def dispatch_tool(tool_name: str, arguments: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """Execute a logistics tool with bounded self-healing recovery and audit logging."""
    if tool_name == "check_inventory":
        return execute_with_recovery(
            check_inventory,
            product=arguments.get("product", ""),
            quantity=arguments.get("quantity", 0),
            operation_name="check_inventory",
            db_path=db_path,
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
            db_path=db_path,
        )
    elif tool_name == "track_shipment":
        return execute_with_recovery(
            track_shipment,
            shipment_id=arguments.get("shipment_id", ""),
            operation_name="track_shipment",
            db_path=db_path,
        )
    elif tool_name == "estimate_delivery":
        return execute_with_recovery(
            estimate_delivery,
            origin=arguments.get("origin", ""),
            destination=arguments.get("destination", ""),
            operation_name="estimate_delivery",
            db_path=db_path,
        )
    elif tool_name == "get_inventory":
        return execute_with_recovery(
            get_inventory,
            operation_name="get_inventory",
            db_path=db_path,
        )
    elif tool_name == "update_shipment_status":
        return execute_with_recovery(
            update_shipment_status,
            shipment_id=arguments.get("shipment_id", ""),
            new_status=arguments.get("status", ""),
            operation_name="update_shipment_status",
            db_path=db_path,
        )
    elif tool_name == "get_agent_activity":
        limit = arguments.get("limit", 20)
        return get_agent_activity(limit=limit, db_path=db_path)
    else:
        return format_result(
            success=False,
            message=f"Unknown tool '{tool_name}' requested.",
            error_code="UNKNOWN_TOOL",
        )


class DemoLogisticsAgent:
    """
    Local, deterministic intent parser and orchestrator.
    Used when OPENAI_API_KEY is absent or when Demo Mode is explicitly chosen.
    Does NOT pretend to be an LLM; executes verified logistics workflows directly.
    """

    def __init__(self, mode_label: str = "Demo Mode (Rule-Based Intent Engine)"):
        self.mode_label = mode_label

    def run(self, user_prompt: str, db_path: Optional[str] = None) -> Dict[str, Any]:
        prompt = user_prompt.strip()
        executed_tools: List[Dict[str, Any]] = []

        log_activity(
            action="USER_PROMPT_RECEIVED",
            tool_name=None,
            status="INFO",
            details={"prompt": prompt, "mode": "DEMO"},
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
            # Clean up trailing words like 'and', 'with', etc.
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
            # Check if a specific product was mentioned
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
        # e.g.: "Create a shipment for 5 laptops from Chennai to Bengaluru and check inventory availability."
        # or: "Ship 5 phones from Chennai to Bengaluru"
        if "ship" in prompt.lower() or "create" in prompt.lower() or "send" in prompt.lower():
            # Extract product
            product = None
            for p in ["headphone", "laptop", "phone"]:
                if p in prompt.lower():
                    product = p
                    break

            # Extract quantity
            qty_match = re.search(r"\b(\d+)\b", prompt)
            quantity = int(qty_match.group(1)) if qty_match else None

            # Extract origin & destination
            route_match = re.search(r"from\s+([a-zA-Z\s]+?)\s+to\s+([a-zA-Z\s]+)", prompt, re.IGNORECASE)
            origin = None
            destination = None
            if route_match:
                origin = route_match.group(1).strip()
                destination = route_match.group(2).strip()
                destination = re.sub(r"\b(and|check|with|for|available|availability)\b.*$", "", destination, flags=re.IGNORECASE).strip()

            # Check if any essential parameter is missing and ask for clarification
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

            # Multi-step Workflow:
            # Step 1: Check Inventory Availability
            inv_check = dispatch_tool("check_inventory", {"product": product, "quantity": quantity}, db_path=db_path)
            executed_tools.append({"tool": "check_inventory", "args": {"product": product, "quantity": quantity}, "result": inv_check})

            if not inv_check["success"] or not inv_check.get("data", {}).get("is_sufficient"):
                response_text = (
                    f"**Shipment Rejected - Stock Insufficient:**\n\n"
                    f"{inv_check['message']}\n\n"
                    f"Shipment was **not** created. No inventory was deducted.\n\n*{self.mode_label}*"
                )
                return {"response": response_text, "tools_executed": executed_tools, "mode": "demo"}

            # Step 2: Create Shipment atomically with DB persistence & verification
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

        # Default fallback / Help
        response_text = (
            f"**Logistics Handler AI Agent - Ready**\n\n"
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


class LogisticsCoordinatorAgent:
    """
    Coordinator Agent that handles user requests.
    Uses OpenAI LLM with function calling when OPENAI_API_KEY is configured.
    Falls back gracefully to DemoLogisticsAgent when API key is missing.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = OPENAI_MODEL):
        self.api_key = (api_key or OPENAI_API_KEY).strip()
        self.model = model
        self.demo_agent = DemoLogisticsAgent()

    @property
    def is_ai_mode_active(self) -> bool:
        return bool(self.api_key and not self.api_key.startswith("sk-placeholder"))

    def run(self, user_prompt: str, db_path: Optional[str] = None) -> Dict[str, Any]:
        """Process user request using live OpenAI Agent or deterministic Demo Mode."""
        if not self.is_ai_mode_active:
            return self.demo_agent.run(user_prompt, db_path=db_path)

        # Real OpenAI Tool-Calling Execution Loop
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)

            system_instructions = (
                "You are the Logistics Coordinator AI Agent, a senior operations coordinator managing warehouse inventory, "
                "shipment creation, tracking, and delivery estimation.\n\n"
                "CRITICAL RULES:\n"
                "1. Always check stock availability before creating a shipment.\n"
                "2. When creating a shipment, call 'create_shipment' with origin, destination, product, and quantity.\n"
                "3. NEVER invent shipment IDs, stock levels, or delivery dates. Only use data returned by the tools.\n"
                "4. If required parameters (e.g. quantity, origin, destination, product) are missing from the request, "
                "ask the user for clarification before executing.\n"
                "5. Distinguish clearly between successful operations and failed operations.\n"
                "6. Provide clear, professional summaries with shipment IDs, statuses, and delivery dates."
            )

            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": user_prompt},
            ]

            executed_tools: List[Dict[str, Any]] = []

            # Multi-turn tool execution loop (up to 5 steps)
            for _ in range(5):
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=LOGISTICS_TOOLS,
                    tool_choice="auto",
                    temperature=0.0,
                )

                msg = response.choices[0].message
                tool_calls = getattr(msg, "tool_calls", None)

                if not tool_calls:
                    # Model provided final natural language response
                    return {
                        "response": msg.content or "Operation completed.",
                        "tools_executed": executed_tools,
                        "mode": "ai",
                    }

                # Append assistant tool calls to message history
                messages.append(msg)

                for tc in tool_calls:
                    t_name = tc.function.name
                    try:
                        t_args = json.loads(tc.function.arguments)
                    except Exception:
                        t_args = {}

                    # Execute verified tool
                    tool_result = dispatch_tool(t_name, t_args, db_path=db_path)
                    executed_tools.append({
                        "tool": t_name,
                        "args": t_args,
                        "result": tool_result,
                    })

                    # Feed result back to OpenAI conversation
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(tool_result),
                    })

            # If loop finished without plain response, synthesize final summary
            return {
                "response": "Workflow steps executed.",
                "tools_executed": executed_tools,
                "mode": "ai",
            }

        except Exception as e:
            # Fall back to demo engine if OpenAI API call fails (e.g. network/quota/auth)
            demo_res = self.demo_agent.run(user_prompt, db_path=db_path)
            demo_res["warning"] = f"OpenAI API error ({str(e)}). Fell back to Demo Engine."
            return demo_res
