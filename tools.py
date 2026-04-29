"""Tool functions for Stock Manager agents.

Refined architecture: Database-backed tools now call MCP Toolbox via HTTP
(localhost:5000) instead of executing SQL directly. The Order Generator's
Google Sheets push remains a direct integration since it's an external system,
not a database query.

This refactor:
  - Standardizes data access through MCP Toolbox (Cohort 1 lab pattern)
  - Adds find_similar_pattern_items for vector-based predictive restocking
  - Keeps direct SQLAlchemy access only for /api/inventory and the migration
"""

import os
import json
from decimal import Decimal
from dotenv import load_dotenv
import sqlalchemy
from sqlalchemy import text
import httpx
import gspread
import google.auth

load_dotenv()

MCP_TOOLBOX_URL = os.environ.get("MCP_TOOLBOX_URL", "http://localhost:5000")

# --- MCP Toolbox HTTP client ---


def _invoke_toolbox(tool_name: str, params: dict | None = None) -> dict:
    """Invoke an MCP Toolbox tool via HTTP and return the result.

    Handles response variations across toolbox versions:
      - {"result": [...rows...]}      → return list wrapped in {"data": [...]}
      - {"result": "json_string"}     → parse string and wrap
      - direct list/dict response     → return wrapped or as-is
    """
    url = f"{MCP_TOOLBOX_URL}/api/tool/{tool_name}/invoke"
    try:
        response = httpx.post(url, json=params or {}, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        result = data.get("result", data)
        # Toolbox may return result as a JSON-encoded string
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                pass
        # Wrap list results in a dict so ADK/Gemini can interpret them as a tool output
        if isinstance(result, list):
            return {"rows": result, "count": len(result)}
        if isinstance(result, dict):
            return result
        return {"result": result}
    except httpx.HTTPError as e:
        return {"error": f"MCP Toolbox call failed for {tool_name}: {e}"}


# --- Direct DB engine (for non-agent endpoints + migration) ---

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        db_host = os.environ["DB_HOST"]
        db_user = os.environ["DB_USER"]
        db_pass = os.environ["DB_PASS"]
        db_name = os.environ["DB_NAME"]
        _engine = sqlalchemy.create_engine(
            f"postgresql+pg8000://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
        )
    return _engine


def _convert(val):
    if isinstance(val, Decimal):
        return float(val)
    return val


def _query(sql, params=None):
    """Direct SQL query — used by /api/inventory and migration only."""
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        columns = list(result.keys())
        rows = [{col: _convert(val) for col, val in zip(columns, row)} for row in result.fetchall()]
    return rows


# --- Sales Analyst Tools (via MCP Toolbox) ---


def get_sales_summary(period_days: int = 7) -> dict:
    """Get average daily sales per product for the specified recent period.

    Calls MCP Toolbox tool: get-sales-summary

    Args:
        period_days: Number of recent days to analyze. Default is 7.

    Returns:
        Dict with products list — each has product_id, product_name, category,
        total_sold, avg_daily.
    """
    return _invoke_toolbox("get-sales-summary", {"period_days": period_days})


def get_sales_trends() -> dict:
    """Compare last 7 days vs prior 7 days to detect rising or falling demand per product.

    Calls MCP Toolbox tool: get-sales-trends

    Returns:
        Dict with products list — each has product_id, product_name, recent_sold,
        prev_sold, pct_change, trend (rising/falling/stable).
    """
    return _invoke_toolbox("get-sales-trends")


def find_similar_pattern_items(reference_product_id: str, top_n: int = 5) -> dict:
    """Vector similarity search: find products behaving like a given fast-mover.

    Uses AlloyDB AI vector embeddings on 6-week sales velocity patterns.
    Returns the top N products whose sales pattern is closest to the reference
    product's pattern, EXCLUDING the reference itself. These are candidates for
    PREDICTIVE restocking — items likely to become fast sellers.

    Calls MCP Toolbox tool: find-similar-pattern-items

    Args:
        reference_product_id: product_id of a known fast-mover
        top_n: how many similar items to return (default 5)

    Returns:
        Dict with products list — each has product_id, product_name,
        similarity_score (0-1, higher = more similar pattern), current_stock,
        reorder_point, reorder_quantity, supplier_name, contact_phone.
    """
    return _invoke_toolbox("find-similar-pattern-items", {
        "reference_product_id": reference_product_id,
        "top_n": top_n,
    })


# --- Inventory Checker Tools (via MCP Toolbox) ---


def get_inventory_status() -> dict:
    """Get current stock levels for all products with reorder points and supplier info.

    Calls MCP Toolbox tool: get-inventory-status

    Returns:
        Dict with products list — each has product_id, product_name, category,
        current_stock, reorder_point, reorder_quantity, supplier_name,
        supplier_id, status (critical/low/healthy).
    """
    return _invoke_toolbox("get-inventory-status")


def get_low_stock_items() -> dict:
    """Get only products below their reorder point (need restocking).

    Calls MCP Toolbox tool: get-low-stock-items

    Returns:
        Dict with items list — each has product_id, product_name, category,
        current_stock, reorder_point, reorder_quantity, supplier_name,
        contact_phone, email, lead_time_days.
    """
    return _invoke_toolbox("get-low-stock-items")


# --- Order Generator Tool (direct integration with Google Sheets) ---


def create_purchase_order(order_items_json: str) -> dict:
    """Create a purchase order and push it to Google Sheets via MCP.

    Args:
        order_items_json: JSON string with list of items. Each item must have:
            product_name, quantity, supplier_name, contact_phone, reason.
            'reason' is one of: "Low Stock", "Trending Up", "Similar Pattern".
            Example: [{"product_name": "BBQ Pork Bun", "quantity": 200,
                      "supplier_name": "Ah Kow", "contact_phone": "+60129876543",
                      "reason": "Low Stock"}]

    Returns:
        Dict confirming creation with sheet_url and sheet_title.
    """
    items = json.loads(order_items_json)
    if not items:
        return {"status": "error", "message": "No items provided"}

    sheets_id = os.environ.get("GOOGLE_SHEETS_ID")
    if not sheets_id:
        return {"status": "error", "message": "GOOGLE_SHEETS_ID not configured"}

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheets_id)

    from datetime import date
    sheet_title = f"PO-{date.today().isoformat()}"

    try:
        worksheet = sh.worksheet(sheet_title)
        worksheet.clear()
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sh.add_worksheet(title=sheet_title, rows=100, cols=10)

    header = ["Product", "Quantity", "Supplier", "Contact Phone", "Reason"]
    rows = [header]

    current_supplier = None
    for item in sorted(items, key=lambda x: x.get("supplier_name", "")):
        supplier = item.get("supplier_name", "Unknown")
        if supplier != current_supplier:
            if current_supplier is not None:
                rows.append(["", "", "", "", ""])
            rows.append([f"--- {supplier} ---", "", "", "", ""])
            current_supplier = supplier
        rows.append([
            item.get("product_name", ""),
            str(item.get("quantity", 0)),
            supplier,
            item.get("contact_phone", ""),
            item.get("reason", ""),
        ])

    worksheet.update(range_name="A1", values=rows)

    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheets_id}/edit"
    return {
        "status": "success",
        "message": f"Purchase order created with {len(items)} items",
        "sheet_title": sheet_title,
        "sheet_url": sheet_url,
    }
