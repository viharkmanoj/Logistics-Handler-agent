"""
Streamlit Web Dashboard for Logistics Handler AI Agent.
Provides a clean, professional interface for agent interaction, manual shipment operations,
tracking, status management, warehouse inventory overview, and self-healing demonstrations.
"""

import streamlit as st
import pandas as pd
from datetime import datetime

from logistics.config import (
    STATUS_CREATED,
    STATUS_IN_TRANSIT,
    STATUS_OUT_FOR_DELIVERY,
    STATUS_DELIVERED,
    STATUS_CANCELLED,
    ALL_STATUSES,
    VALID_TRANSITIONS,
)
from logistics.database import init_db, get_connection
from logistics.inventory import get_inventory, check_inventory
from logistics.shipments import (
    create_shipment,
    track_shipment,
    update_shipment_status,
    get_shipments,
)
from logistics.routing import estimate_delivery
from logistics.logging_utils import get_agent_activity, log_activity
from logistics.agent import LogisticsCoordinatorAgent, DemoLogisticsAgent
from logistics.recovery import execute_with_recovery, set_simulated_failures

# Ensure DB is initialized
init_db()

# Page Configuration
st.set_page_config(
    page_title="Logistics Handler AI Agent",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling for Professional Logistics Interface
st.markdown("""
<style>
    .main-title {
        font-size: 2.1rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        color: #64748B;
        font-size: 1.05rem;
        margin-bottom: 1.2rem;
    }
    .mode-badge-ai {
        background-color: #DCFCE7;
        color: #166534;
        padding: 4px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.85rem;
        display: inline-block;
        border: 1px solid #86EFAC;
    }
    .mode-badge-demo {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 4px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.85rem;
        display: inline-block;
        border: 1px solid #FCD34D;
    }
    .metric-card {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 16px;
        text-align: center;
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #0F172A;
    }
    .metric-label {
        font-size: 0.85rem;
        color: #64748B;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
</style>
""", unsafe_allow_html=True)

# Initialize Session State
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "agent_mode_override" not in st.session_state:
    st.session_state.agent_mode_override = "Auto-Detect"

# Instantiate Agent
coordinator = LogisticsCoordinatorAgent()
is_live_ai = coordinator.is_ai_mode_active

# Sidebar Settings
with st.sidebar:
    st.header("⚙️ Agent Settings")
    mode_selection = st.selectbox(
        "Operating Mode",
        options=["Auto-Detect", "Force Demo Mode", "Force AI Mode (Requires API Key)"],
        index=0,
    )

    if mode_selection == "Force Demo Mode":
        effective_mode = "demo"
    elif mode_selection == "Force AI Mode (Requires API Key)":
        effective_mode = "ai" if is_live_ai else "demo"
    else:
        effective_mode = "ai" if is_live_ai else "demo"

    st.divider()
    st.markdown("### 📋 System Information")
    st.markdown(f"**Database:** SQLite (`data/logistics.db`)")
    st.markdown(f"**MCP Server:** Ready on `mcp_server.server`")
    st.markdown(f"**Testing:** 21 automated pytest cases")

    st.divider()
    if st.button("🧹 Clear Chat History", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()

# Top Header & Mode Indicator
col_title, col_badge = st.columns([3, 1])
with col_title:
    st.markdown('<div class="main-title">🚚 Logistics Handler AI Agent</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Intelligent shipment processing, automated stock validation, and self-healing operations</div>', unsafe_allow_html=True)

with col_badge:
    st.write("")
    if effective_mode == "ai" and is_live_ai:
        st.markdown('<div class="mode-badge-ai">🤖 Google ADK Mode (Gemini)</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="mode-badge-demo">⚡ Demo Mode (Local Rule-Based Engine)</div>', unsafe_allow_html=True)
        st.caption("No Google Gemini API key configured. Fully functional local workflow engine active.")

# Fetch Metrics Data
shipments_list = get_shipments()
total_shipments = len(shipments_list)
created_count = sum(1 for s in shipments_list if s["status"] == STATUS_CREATED)
transit_count = sum(1 for s in shipments_list if s["status"] in [STATUS_IN_TRANSIT, STATUS_OUT_FOR_DELIVERY])
delivered_count = sum(1 for s in shipments_list if s["status"] == STATUS_DELIVERED)

inv_res = get_inventory()
inv_data = inv_res.get("data", {}).get("inventory", [])
total_avail_stock = sum(item["available_quantity"] for item in inv_data)

# Metric KPI Cards
m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.markdown(f'<div class="metric-card"><div class="metric-value">{total_shipments}</div><div class="metric-label">Total Shipments</div></div>', unsafe_allow_html=True)
with m2:
    st.markdown(f'<div class="metric-card"><div class="metric-value">{created_count}</div><div class="metric-label">Created (Pending)</div></div>', unsafe_allow_html=True)
with m3:
    st.markdown(f'<div class="metric-card"><div class="metric-value">{transit_count}</div><div class="metric-label">In-Transit</div></div>', unsafe_allow_html=True)
with m4:
    st.markdown(f'<div class="metric-card"><div class="metric-value">{delivered_count}</div><div class="metric-label">Delivered</div></div>', unsafe_allow_html=True)
with m5:
    st.markdown(f'<div class="metric-card"><div class="metric-value">{total_avail_stock}</div><div class="metric-label">Available Stock</div></div>', unsafe_allow_html=True)

st.write("")

# Navigation Tabs
tab_chat, tab_create, tab_track, tab_inventory, tab_logs = st.tabs([
    "💬 Conversational AI Agent",
    "📦 Create Shipment",
    "🔍 Track & Advance Status",
    "📊 Warehouse Inventory",
    "🔄 Feedback & Self-Healing Demo",
])

# TAB 1: Conversational AI Agent
with tab_chat:
    st.markdown("#### Natural-Language Logistics Assistant")
    st.markdown("Issue conversational instructions to check stock, create shipments, track deliveries, or query system activity.")

    # Quick Prompt Buttons
    st.markdown("**Sample Operations:**")
    qp1, qp2, qp3, qp4 = st.columns(4)
    preset_prompt = None
    if qp1.button("📦 Ship 5 Laptops", use_container_width=True):
        preset_prompt = "Create a shipment for 5 laptops from Chennai to Bengaluru and check inventory availability."
    if qp2.button("📊 Stock for 10 Laptops", use_container_width=True):
        preset_prompt = "Check stock for 10 laptops."
    if qp3.button("⏱️ Transit Chennai to BLR", use_container_width=True):
        preset_prompt = "Estimate delivery time from Chennai to Bengaluru."
    if qp4.button("❓ Why Did Shipment Fail?", use_container_width=True):
        preset_prompt = "Why did my shipment fail?"

    # Display Chat History
    for chat in st.session_state.chat_history:
        with st.chat_message(chat["role"]):
            st.markdown(chat["content"])
            if "tools" in chat and chat["tools"]:
                with st.expander(f"🛠️ Tools Executed ({len(chat['tools'])})"):
                    for t in chat["tools"]:
                        st.markdown(f"**Tool:** `{t['tool']}`")
                        st.json({"arguments": t["args"], "result": t["result"]})

    # Chat Input
    user_input = st.chat_input("Enter logistics request (e.g., 'Ship 5 phones from Chennai to Bengaluru')...")
    active_prompt = preset_prompt or user_input

    if active_prompt:
        # Display user message
        st.session_state.chat_history.append({"role": "user", "content": active_prompt})
        with st.chat_message("user"):
            st.markdown(active_prompt)

        # Run agent
        with st.spinner("Agent interpreting request and coordinating tools..."):
            if effective_mode == "ai" and is_live_ai:
                result = coordinator.run(active_prompt)
            else:
                demo_agent = DemoLogisticsAgent()
                result = demo_agent.run(active_prompt)

        # Display agent response
        with st.chat_message("assistant"):
            st.markdown(result["response"])
            if result.get("tools_executed"):
                with st.expander(f"🛠️ Tools Executed ({len(result['tools_executed'])})"):
                    for t in result["tools_executed"]:
                        st.markdown(f"**Tool:** `{t['tool']}`")
                        st.json({"arguments": t["args"], "result": t["result"]})

        st.session_state.chat_history.append({
            "role": "assistant",
            "content": result["response"],
            "tools": result.get("tools_executed", []),
        })
        st.rerun()

# TAB 2: Manual Shipment Creation Form
with tab_create:
    st.markdown("#### Create New Verified Shipment")
    st.markdown("Direct form entry with automatic stock verification, atomic database deduction, and duplicate prevention.")

    with st.form("create_shipment_form"):
        fc1, fc2 = st.columns(2)
        with fc1:
            product_choice = st.selectbox("Product", options=["Laptop", "Phone", "Headphones"])
            quantity_choice = st.number_input("Quantity", min_value=1, max_value=500, value=5, step=1)
            custom_idemp = st.text_input("Idempotency Key (Optional)", placeholder="e.g. ORDER-REQ-9871")
        with fc2:
            origin_choice = st.text_input("Origin City", value="Chennai")
            dest_choice = st.text_input("Destination City", value="Bengaluru")

        submit_shipment = st.form_submit_button("Create & Verify Shipment", use_container_width=True)

    if submit_shipment:
        with st.spinner("Processing transaction and verifying database state..."):
            ship_result = execute_with_recovery(
                create_shipment,
                origin=origin_choice,
                destination=dest_choice,
                product=product_choice,
                quantity=quantity_choice,
                idempotency_key=custom_idemp if custom_idemp.strip() else None,
                operation_name="manual_create_shipment",
            )

        if ship_result["success"]:
            d = ship_result["data"]
            st.success(f"✅ {ship_result['message']}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Shipment ID", d["shipment_id"])
            c2.metric("Status", d["status"])
            c3.metric("Remaining Warehouse Stock", f"{d['remaining_stock']} units")
            st.info(f"📅 Estimated Delivery: **{d['estimated_delivery']}** ({d['origin']} ➔ {d['destination']})")
        else:
            st.error(f"❌ Failed: {ship_result['message']}")
            st.warning(f"Error Code: `{ship_result.get('error_code')}`")

# TAB 3: Track & Advance Status
with tab_track:
    st.markdown("#### Track & Advance Shipment Lifecycle")
    tc1, tc2 = st.columns([2, 1])

    with tc1:
        search_id = st.text_input("Enter Shipment ID to Track", placeholder="e.g. SHP-A1B2C3D4")
        if st.button("Track Shipment", use_container_width=True):
            if search_id.strip():
                track_res = track_shipment(search_id)
                if track_res["success"]:
                    st.session_state["active_tracked"] = track_res["data"]
                else:
                    st.error(f"❌ {track_res['message']}")
                    st.session_state["active_tracked"] = None
            else:
                st.warning("Please enter a valid Shipment ID.")

    if "active_tracked" in st.session_state and st.session_state["active_tracked"]:
        tracked = st.session_state["active_tracked"]
        st.divider()
        st.markdown(f"### Shipment Details: `{tracked['shipment_id']}`")

        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Status", tracked["status"])
        sc2.metric("Product", f"{tracked['quantity']}x {tracked['product']}")
        sc3.metric("Route", f"{tracked['origin']} ➔ {tracked['destination']}")
        sc4.metric("Est. Delivery", tracked["estimated_delivery"])

        # Status Update Workflow
        current_st = tracked["status"]
        allowed = VALID_TRANSITIONS.get(current_st, [])

        st.markdown("#### Advance Lifecycle Status")
        if allowed:
            uc1, uc2 = st.columns([2, 1])
            with uc1:
                target_status = st.selectbox("Select Valid Next Status", options=allowed)
            with uc2:
                st.write("")
                if st.button("Update Status", use_container_width=True):
                    up_res = update_shipment_status(tracked["shipment_id"], target_status)
                    if up_res["success"]:
                        st.success(up_res["message"])
                        # Refresh tracked info
                        refreshed = track_shipment(tracked["shipment_id"])
                        st.session_state["active_tracked"] = refreshed.get("data")
                        st.rerun()
                    else:
                        st.error(up_res["message"])
        else:
            st.info(f"Shipment is in terminal state '{current_st}'. No further status transitions allowed.")

    st.divider()
    st.markdown("#### Recent Shipment Registry")
    if shipments_list:
        df_shipments = pd.DataFrame(shipments_list)
        st.dataframe(df_shipments, use_container_width=True)
    else:
        st.caption("No shipments registered in database yet.")

# TAB 4: Warehouse Inventory
with tab_inventory:
    st.markdown("#### Warehouse Inventory Overview")
    st.caption("Live stock levels with atomic consistency and real-time tracking.")

    if inv_data:
        df_inv = pd.DataFrame(inv_data)
        st.dataframe(
            df_inv[["product_id", "product_name", "available_quantity", "reserved_quantity", "updated_at"]],
            column_config={
                "product_id": "Catalog SKU",
                "product_name": "Product Name",
                "available_quantity": "Available Stock",
                "reserved_quantity": "Reserved",
                "updated_at": "Last Updated",
            },
            use_container_width=True,
        )

        st.markdown("#### Stock Capacity Levels")
        for item in inv_data:
            # Baseline capacity ratio relative to initial seed
            base_capacity = 100 if item["product_name"] == "Phone" else (50 if item["product_name"] == "Laptop" else 30)
            avail = item["available_quantity"]
            ratio = min(1.0, max(0.0, avail / base_capacity))
            st.write(f"**{item['product_name']}** ({avail} / {base_capacity} units)")
            st.progress(ratio)
    else:
        st.warning("No inventory records found.")

# TAB 5: Feedback & Self-Healing Demo
with tab_logs:
    st.markdown("#### Feedback Loop & Self-Healing Demonstration")
    st.markdown(
        "Demonstrates safe, bounded retries with exponential backoff and idempotency protection. "
        "Reviewers can trigger a controlled transient failure to observe automated recovery in real-time."
    )

    hc1, hc2 = st.columns([2, 1])
    with hc1:
        st.info(
            "💡 **Self-Healing Simulation:** When you click the button below, the system will deliberately "
            "simulate 1 transient glitch (e.g. simulated network hiccup or temporary DB lock). "
            "The recovery engine will catch the error, log a `RECOVERY_ATTEMPT`, wait with exponential backoff, "
            "retry the operation, and verify the resulting database state."
        )
    with hc2:
        st.write("")
        if st.button("⚡ Simulate Glitch & Test Self-Healing", type="primary", use_container_width=True):
            with st.spinner("Simulating failure and executing bounded self-healing..."):
                heal_res = execute_with_recovery(
                    create_shipment,
                    origin="Chennai",
                    destination="Bengaluru",
                    product="Laptop",
                    quantity=1,
                    operation_name="simulated_recovery_demo",
                    simulate_fail_count=1,
                )

            if heal_res["success"]:
                st.success(f"🎉 **Self-Healing Succeeded!** Shipment `{heal_res['data']['shipment_id']}` was created after recovering from simulated failure.")
            else:
                st.error(f"Recovery failed: {heal_res['message']}")

    st.divider()
    st.markdown("#### Agent Activity & Audit Trail")

    activity_res = get_agent_activity(limit=50)
    activities = activity_res.get("data", {}).get("activities", [])

    if activities:
        df_act = pd.DataFrame(activities)
        # Select key columns
        display_cols = ["id", "timestamp", "action", "tool_name", "status", "error_code", "recovery_attempted", "recovery_success"]
        st.dataframe(df_act[display_cols], use_container_width=True)
    else:
        st.caption("No activity records found.")
