# Logistics Handler AI Agent

An autonomous, enterprise-grade AI Logistics Agent and management dashboard capable of interpreting natural-language shipping requests, validating warehouse stock, executing atomic shipment creation, tracking delivery lifecycles, and recovering from transient operational failures through bounded self-healing.

---

## 📑 Table of Contents

- [Overview](#-overview)
- [Problem Statement](#-problem-statement)
- [Proposed Solution](#-proposed-solution)
- [Key Features](#-key-features)
- [Architecture & Design](#-architecture--design)
- [Technologies Used](#-technologies-used)
- [Prerequisites](#-prerequisites)
- [Quick Start Guide](#-quick-start-guide)
  - [1. Clone Repository & Setup Virtual Environment](#1-clone-repository--setup-virtual-environment)
  - [2. Install Dependencies](#2-install-dependencies)
  - [3. Configure Environment Variables](#3-configure-environment-variables)
- [Running the Application](#-running-the-application)
  - [Running in Demo Mode (No API Key Required)](#running-in-demo-mode-no-api-key-required)
  - [Running in AI Mode (OpenAI Tool Calling)](#running-in-ai-mode-openai-tool-calling)
  - [Launching the Streamlit Web Dashboard](#launching-the-streamlit-web-dashboard)
  - [Running the Model Context Protocol (MCP) Server](#running-the-model-context-protocol-mcp-server)
- [Automated Testing](#-automated-testing)
- [Example Requests & Expected Responses](#-example-requests--expected-responses)
- [Feedback Loop Implementation](#-feedback-loop-implementation)
- [Self-Healing & Fault Recovery](#-self-healing--fault-recovery)
- [Known Limitations](#-known-limitations)
- [Future Enhancements](#-future-enhancements)
- [GitHub Preparation](#-github-preparation)

---

## 🔎 Overview

The **Logistics Handler AI Agent** bridges the gap between unstructured human operational queries and strict, transaction-safe logistics databases. Operating as an intelligent coordinator, it translates instructions like *"Create a shipment for 5 laptops from Chennai to Bengaluru and check inventory availability"* into verified multi-step tool calls, guards against double-deduction on retries, enforces lifecycle state transitions, and logs an immutable audit trail in SQLite.

---

## ⚠️ Problem Statement

Modern logistics coordination faces critical challenges:
1. **Unstructured Communication:** Dispatchers and clients communicate in natural language, leading to manual data entry errors, missing parameters, and inventory mismatch.
2. **Double Deductions & Race Conditions:** When network drops or database locks occur during shipment creation, blind retries frequently result in duplicate orders and incorrect stock deductions.
3. **Lack of Truthful Grounding:** Many AI agents "hallucinate" tracking numbers, stock levels, or operational success without database verification.
4. **Transient Failures:** Microservice hiccups, transient SQLite locks, and temporary network faults cause job failures unless handled by a bounded self-healing loop.

---

## 💡 Proposed Solution

A modular, highly observable agent system that incorporates:
- **OpenAI Tool Calling & Deterministic Demo Fallback:** Automatically switches between live GPT-4o-mini and a local rule-based intent engine if an API key is not present.
- **ACID Database Transactions:** SQLite with Write-Ahead Logging (WAL) and `CHECK` constraints ensuring inventory deductions and shipment records are committed atomically.
- **Strict Verification Step:** An operation is reported as successful **only** when a post-transaction query confirms the database state.
- **Safe Self-Healing:** Exponential backoff with idempotency key enforcement. Permanent business errors (e.g. `INSUFFICIENT_STOCK`) fail fast, while transient errors recover automatically.
- **Model Context Protocol (MCP) Interface:** Enables external agent hosts and IDEs to execute logistics tools directly over standard MCP protocols.

---

## ✨ Key Features

| Feature | Description |
| :--- | :--- |
| **Conversational Assistant** | Interprets natural language, extracts entities (origin, destination, product, quantity), and coordinates multi-step workflows. |
| **Clarification Handling** | Politely asks for missing parameters (e.g., missing destination or quantity) before executing. |
| **Atomic Inventory Control** | Deducts stock in real-time with zero risk of negative balances or concurrency race conditions. |
| **Idempotent Shipment Creation** | Prevents duplicate shipments during automated retries or identical resubmissions. |
| **Lifecycle State Machine** | Enforces valid status transitions (`CREATED` ➔ `IN_TRANSIT` ➔ `OUT_FOR_DELIVERY` ➔ `DELIVERED` or `CANCELLED`). |
| **Delivery Estimation** | Calculates transit distance and estimated arrival dates with explicit labeling for simulated distance matrices. |
| **Full Audit Trail** | Logs every action, tool execution, feedback outcome, and recovery event in SQLite. |
| **Interactive Self-Healing Demo** | One-click button in Streamlit to inject a transient error and observe automated recovery. |
| **Model Context Protocol (MCP)** | Standardized MCP server exposing all core logistics tools. |

---

## 🏛️ Architecture & Design

For in-depth diagrams and state transition specifications, see [`docs/architecture.md`](file:///Users/manojvihar/Desktop/agent/docs/architecture.md).

```
logistics-handler/
│
├── app.py                     # Streamlit Web Dashboard application
├── requirements.txt           # Verified, stable dependencies
├── .env.example               # Environment template
├── .gitignore                 # Standard Python/SQLite exclusions
├── README.md                  # Complete technical documentation
│
├── logistics/                 # Core domain & agent package
│   ├── __init__.py
│   ├── config.py              # Centralized constants, statuses, and configuration
│   ├── database.py            # SQLite connection, WAL mode, schema & seed logic
│   ├── inventory.py           # check_inventory(), get_inventory(), name normalization
│   ├── routing.py             # estimate_delivery() with simulated distance matrix
│   ├── shipments.py           # create_shipment(), track_shipment(), update_shipment_status()
│   ├── recovery.py            # execute_with_recovery(), backoff, transient simulation
│   ├── logging_utils.py       # format_result(), log_activity(), get_agent_activity()
│   └── agent.py               # LogisticsCoordinatorAgent (OpenAI + Demo Mode fallback)
│
├── mcp_server/                # Model Context Protocol integration
│   ├── __init__.py
│   └── server.py              # MCP Server exposing all 6 logistics tools
│
├── tests/                     # Automated pytest suite (21 test cases)
│   ├── __init__.py
│   ├── conftest.py            # Isolated SQLite fixture for test runs
│   ├── test_inventory.py      # Tests for stock checking, invalid quantity, deduction
│   ├── test_shipments.py      # Tests for creation, persistence, tracking, transitions
│   ├── test_recovery.py       # Tests for idempotency, self-healing, exhaustion
│   └── test_agent_tools.py    # Tests for natural language flows, routing, clarification
│
└── docs/
    └── architecture.md        # Technical architecture and sequence diagrams
```

---

## 🛠️ Technologies Used

- **Language:** Python 3.10+ (tested on Python 3.14.5)
- **AI Orchestration:** OpenAI Agents / Function Calling SDK (`openai>=1.30.0`)
- **Database:** SQLite 3 (WAL mode enabled, ACID atomic transactions)
- **User Interface:** Streamlit (`streamlit>=1.35.0`)
- **Integration Protocol:** Model Context Protocol SDK (`mcp>=1.0.0`)
- **Testing:** Pytest (`pytest>=8.0.0`)
- **Data Handling:** Pydantic (`pydantic>=2.7.0`), Pandas (`pandas>=2.0.0`)

---

## 📋 Prerequisites

- macOS, Linux, or Windows with Python 3.10, 3.11, 3.12, 3.13, or 3.14 installed.
- Git installed.
- *(Optional)* An OpenAI API key if you wish to run in live LLM mode.

---

## 🚀 Quick Start Guide

### 1. Clone Repository & Setup Virtual Environment

```bash
# Clone the repository
git clone <repository-url>
cd agent

# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
# On macOS/Linux:
source .venv/bin/activate
# On Windows:
# .venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Environment Variables

```bash
# Copy example configuration
cp .env.example .env
```

Open `.env` in any text editor. By default, it runs in **Demo Mode**:
```ini
# Leave blank to use the fully functional local Demo Mode
OPENAI_API_KEY=

# Model to use when OPENAI_API_KEY is supplied
OPENAI_MODEL=gpt-4o-mini

# Database path (defaults to data/logistics.db)
LOGISTICS_DB_PATH=data/logistics.db

# Mode: auto | ai | demo
AGENT_MODE=auto

# Logging level
LOG_LEVEL=INFO

# Set to 0 for normal operation, or an integer N to simulate N transient failures
SIMULATE_TRANSIENT_FAILURES=0
```

---

## 🖥️ Running the Application

### Running in Demo Mode (No API Key Required)
When `OPENAI_API_KEY` is omitted or empty, the application runs in **Demo Mode**. It utilizes a deterministic rule-based intent engine and entity extractor that executes the exact same underlying tools and atomic database transactions.

### Running in AI Mode (OpenAI Tool Calling)
To enable live AI tool-calling with GPT-4o-mini, add your key to `.env`:
```ini
OPENAI_API_KEY=sk-proj-yourActualKeyHere
```

### Launching the Streamlit Web Dashboard

```bash
streamlit run app.py
```
Open your browser to: **`http://localhost:8501`**

#### What you will see:
1. **KPI Metrics:** Total Shipments, Created, In-Transit, Delivered, and Available Warehouse Inventory.
2. **Conversational Assistant Tab:** Chat interface with quick prompt buttons and interactive tool execution traces.
3. **Create Shipment Tab:** Form with real-time stock verification, custom idempotency keys, and estimated transit times.
4. **Track & Advance Status Tab:** Shipment tracking and status transitions with strict state machine validation.
5. **Warehouse Inventory Tab:** Live stock table with visual progress indicators.
6. **Feedback & Self-Healing Tab:** Activity log viewer and a **"Simulate Glitch & Test Self-Healing"** button.

---

### Running the Model Context Protocol (MCP) Server

The MCP server allows any MCP-compatible client (such as Claude Desktop, Cursor, or an MCP agent orchestrator) to call the logistics tools:

```bash
python -m mcp_server.server
```

#### Example MCP Client Configuration (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "logistics-handler": {
      "command": "/absolute/path/to/agent/.venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "env": {
        "LOGISTICS_DB_PATH": "/absolute/path/to/agent/data/logistics.db"
      }
    }
  }
}
```

Exposed MCP Tools:
- `check_inventory(product, quantity)`
- `create_shipment(origin, destination, product, quantity, idempotency_key)`
- `track_shipment(shipment_id)`
- `estimate_delivery(origin, destination)`
- `get_inventory()`
- `get_agent_activity(limit)`

---

## 🧪 Automated Testing

The automated test suite uses `pytest` and runs against isolated temporary SQLite databases without requiring an OpenAI API key:

```bash
# Run all tests
pytest -v
```

### Test Coverage Summary:
- **Test 1:** Successful inventory check (`test_1_successful_inventory_check`)
- **Test 2:** Insufficient inventory detection (`test_2_insufficient_inventory`)
- **Test 3:** Invalid quantity rejection (`test_3_invalid_quantity`)
- **Test 4:** Successful shipment creation (`test_4_successful_shipment_creation`)
- **Test 5:** Shipment persistence across independent SQLite connections (`test_5_shipment_persistence`)
- **Test 6:** Shipment tracking by ID (`test_6_shipment_tracking`)
- **Test 7:** Unknown shipment ID handling (`test_7_unknown_shipment_id`)
- **Test 8:** Inventory deduction post-shipment (`test_8_inventory_deduction`)
- **Test 9:** Duplicate shipment prevention via idempotency keys (`test_9_duplicate_shipment_prevention_during_retries`)
- **Test 10:** Temporary failure and successful self-healing (`test_10_temporary_failure_and_successful_recovery`)
- **Test 11:** Recovery exhaustion handling (`test_11_recovery_exhaustion`)
- **Test 12:** Invalid status transition rejection (`test_12_invalid_shipment_status_transition`)
- **Test 13:** Database consistency rollback (`test_13_database_consistency`)
- **Plus:** Agent clarification requests, multi-step workflows, delivery labeling, and failure explanation queries.

---

## 💬 Example Requests & Expected Responses

### Example 1: End-to-End Shipment Creation
**User:**
> "Create a shipment for 5 laptops from Chennai to Bengaluru and check inventory availability."

**Agent Response:**
> ### Shipment Confirmed & Created Successfully!
> - **Shipment ID:** `SHP-A7E29F10`
> - **Status:** `CREATED`
> - **Product:** 5x Laptop
> - **Route:** Chennai ➔ Bengaluru
> - **Estimated Delivery:** 2026-10-18
> - **Remaining Warehouse Stock:** 45 units
>
> All details were persisted and verified in SQLite database.
> *Demo Mode (Rule-Based Intent Engine)*

---

### Example 2: Stock Check
**User:**
> "Check stock for 10 laptops."

**Agent Response:**
> **Stock Availability Check**
> - **Product:** Laptop
> - **Available Stock:** 50 units
> - **Requested Quantity (10):** Sufficient
>
> *Demo Mode (Rule-Based Intent Engine)*

---

### Example 3: Missing Information / Clarification
**User:**
> "Ship laptops"

**Agent Response:**
> **Clarification Needed:**
> To process your shipment request, please provide the missing information:
> - quantity (e.g. 5)
> - origin city (e.g. Chennai)
> - destination city (e.g. Bengaluru)
>
> *Example:* 'Create a shipment for 5 laptops from Chennai to Bengaluru.'
> *Demo Mode (Rule-Based Intent Engine)*

---

### Example 4: Delivery Estimation
**User:**
> "Estimate delivery time from Chennai to Bengaluru."

**Agent Response:**
> **Delivery Estimate**
> - **Route:** Chennai ➔ Bengaluru
> - **Distance:** ~346 km
> - **Transit Time:** ~1 business day(s) (~6.9 hrs transit)
> - **Estimated Delivery Date:** 2026-10-18
> - **Provider:** Simulated Logistics Estimation Engine (Deterministic Distance Matrix)
>
> *Demo Mode (Rule-Based Intent Engine)*

---

### Example 5: Root Cause of Failure
**User:**
> "Why did my shipment fail?"

**Agent Response:**
> **Failure Analysis from Recent Activity Logs:**
> - **Action:** `CREATE_SHIPMENT`
> - **Error Code:** `INSUFFICIENT_STOCK`
> - **Reason:** Cannot create shipment: Insufficient stock for 'Laptop'. Requested 99999, available 45.
> - **Timestamp:** 2026-10-17 12:35:12
>
> *Demo Mode (Rule-Based Intent Engine)*

---

## 🔄 Feedback Loop Implementation

Every operation follows an immutable 7-stage feedback loop recorded in SQLite table `agent_activity`:
1. **User Request Logged:** Records timestamp, input text, and session mode.
2. **Tool Selection:** Identifies tool to dispatch (`check_inventory`, `create_shipment`, etc.).
3. **Execution & Metric Check:** Checks operational outcomes against expected preconditions.
4. **Failure Capture:** Distinguishes transient errors from business rule violations.
5. **Self-Healing Action:** Triggers bounded exponential retry if transient.
6. **State Verification:** Queries database independently to verify final entity state.
7. **Structured Envelope:** Returns standard envelope `{success, message, data, error_code}`.

---

## 🛡️ Self-Healing & Fault Recovery

### Recovery Guarantees:
- **Bounded Attempts:** Maximum 3 attempts with exponential backoff: $t = 0.1 \times 2^{(\text{attempt}-1)}$.
- **No Useless Retries:** Business errors (e.g. `INSUFFICIENT_STOCK`, `UNKNOWN_PRODUCT`, `INVALID_QUANTITY`, `INVALID_STATUS_TRANSITION`) fail fast.
- **Duplicate Prevention:** Every shipment creation passes an `idempotency_key`. If an operation is retried, the existing verified shipment is returned without duplicate creation or double-deduction.
- **Reviewer Simulation Mode:** Click the **"Simulate Glitch & Test Self-Healing"** button on the Streamlit dashboard or run `test_10_temporary_failure_and_successful_recovery` to see self-healing in action!

---

## 📌 Known Limitations

1. **Simulated Route Matrix:** Routing estimates use a deterministic distance matrix for major Indian logistics hubs. Real-time satellite GPS/traffic routing requires a live Google Maps or Mapbox API key.
2. **Local SQLite Concurrency:** SQLite in WAL mode safely handles concurrent reads and serializes writes. For very high-throughput distributed write workloads, PostgreSQL is recommended.
3. **Catalog Seed:** Default seed contains Laptop (50), Phone (100), and Headphones (30). Seed runs once on database initialization and preserves state across restarts.

---

## 🔮 Future Enhancements

- **Carrier Webhooks:** Automated status progression triggered by carrier tracking updates.
- **Barcode & QR Code Generation:** Real-time generation of printable shipping labels.
- **Multi-Warehouse Routing:** Dynamic allocation to whichever warehouse has closest proximity and sufficient stock.
- **Telegram / WhatsApp Bot Adapter:** Direct integration for field drivers and warehouse staff.

---

## 📦 GitHub Preparation

To push this project to a new GitHub repository:

```bash
# Check repository status
git status

# Add files
git add .

# Commit changes
git commit -m "feat: complete reviewer-ready Logistics Handler AI Agent"

# Link to your remote GitHub repository
# git remote add origin https://github.com/<your-username>/logistics-handler-ai-agent.git
# git branch -M main
# git push -u origin main
```

*(Note: Never commit your `.env` file containing live API keys. `.env` is already configured in `.gitignore`.)*
