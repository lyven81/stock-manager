# Stock Manager — Top 100 Refinement Build

Smart restocking system for a steam bun shop. Built with Google ADK multi-agent architecture, refined with MCP Toolbox for Databases and AlloyDB AI vector embeddings.

**Live Demo:** [https://stock-manager-522143897885.asia-southeast1.run.app](https://stock-manager-522143897885.asia-southeast1.run.app)

## Problem

A steam bun shop stocks the wrong buns; agents analyze data to match supply with demand. Existing inventory tools only flag what is already low — by then, you have already lost sales. Stock Manager goes further by detecting which products are *behaving* like fast sellers, so they get restocked before they stock out.

## Refinement (vs. original submission)

This refined version applies two Cohort 1 lab patterns that were not yet in the original prototype:

1. **MCP Toolbox for Databases** — agents now query AlloyDB through a standardized, secure MCP layer instead of direct Python SQL calls. Same MCP discipline as the Google Sheets output integration.
2. **AlloyDB AI vector embeddings** — products are embedded as 6-week sales velocity vectors. A new `find_similar_pattern_items` tool finds products whose pattern matches a known fast seller, surfacing predictive restock candidates before they show strong sales.

## Architecture

```
User (Browser)
   ↓ HTTP
Cloud Run (FastAPI)
   ↓
[Google ADK]
 Manager Agent (SequentialAgent)
   ├── Sales Analyst Agent      → MCP Toolbox → AlloyDB
   │   • get_sales_summary
   │   • get_sales_trends
   │   • find_similar_pattern_items  ← vector similarity search
   ├── Inventory Checker Agent  → MCP Toolbox → AlloyDB
   │   • get_inventory_status
   │   • get_low_stock_items
   └── Restock Decider Agent    → Google Sheets via MCP
       • create_purchase_order
```

The MCP Toolbox runs as a sidecar inside the same Cloud Run container (not a separate service) — keeping cost low while making the architectural layer explicit.

## Tech Stack

| Technology | Role | Why |
|-----------|------|-----|
| Google ADK | Multi-agent system | Orchestrates manager + sub-agents |
| Gemini 2.5 Flash | AI model | Fast, accurate decision-making |
| AlloyDB AI | Data + vectors | Structured data + similarity search |
| MCP Toolbox | Data access | Secure, standardized agent queries |
| MCP (Sheets) | Output | Ready-to-use purchase orders |
| Cloud Run | Deployment | Auto-scale, low maintenance |
| FastAPI | Backend | Simple API integration |

## Restock Triggers (3 conditions, any one fires a restock)

| Trigger | Condition | Source |
|---|---|---|
| **Low Stock** | `current_stock < reorder_point` | Inventory Checker (SQL) |
| **Trending Up** | `pct_change >= 10%` AND `current_stock < 1.5x reorder_point` | Sales Analyst (SQL) |
| **Similar Pattern** *(new)* | `similarity_score >= 0.7` to a fast mover AND `current_stock < 1.5x reorder_point` | Sales Analyst (vector search) |

## Files

- `main.py` — FastAPI app with `/api/restock` endpoint
- `agents.py` — ADK agent definitions + prompts
- `tools.py` — Tool functions (HTTP wrappers calling MCP Toolbox)
- `tools.yaml` — MCP Toolbox tool definitions
- `migrate_schema.py` — Idempotent schema migration (adds vector column + populates embeddings)
- `start.sh` — Container startup orchestration (migration -> toolbox -> FastAPI)
- `Dockerfile` — Python 3.11 + MCP Toolbox v0.15 binary
- `static/index.html` — Two-panel UI (inventory + chat)

## Deploy

```bash
gcloud run deploy stock-manager \
  --source . \
  --region asia-southeast1 \
  --vpc-connector stock-manager-connector \
  --allow-unauthenticated
```

The migration runs automatically on each container startup (idempotent — safe to redeploy).

## Cohort

Built for Google Cloud Gen AI Academy APAC 2026 — Top 100 Prototype Refinement Phase. Track: Multi-Agent Productivity Assistant.
