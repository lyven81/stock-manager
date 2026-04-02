"""Tool functions for Stock Manager agents."""

import os
import json
from decimal import Decimal
from dotenv import load_dotenv
import sqlalchemy
from sqlalchemy import text
import gspread
import google.auth

load_dotenv()

# --- Database connection ---
# Uses direct PostgreSQL connection via VPC connector in Cloud Run

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
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        columns = list(result.keys())
        rows = [{col: _convert(val) for col, val in zip(columns, row)} for row in result.fetchall()]
    return rows


# --- Sales Analyst Tools ---


def get_sales_summary(period_days: int = 7) -> dict:
    """Get average daily sales per product for the specified recent period.

    Args:
        period_days: Number of recent days to analyze. Default is 7.

    Returns:
        A dict with a list of products and their average daily sales, sorted by volume descending.
    """
    rows = _query("""
        SELECT p.product_id, p.product_name, p.category,
               COALESCE(SUM(s.quantity_sold), 0) AS total_sold,
               ROUND(COALESCE(SUM(s.quantity_sold), 0)::numeric / :days, 1) AS avg_daily
        FROM products p
        LEFT JOIN sales s ON p.product_id = s.product_id
            AND s.sale_date > (SELECT MAX(sale_date) FROM sales) - INTERVAL ':days days'
        GROUP BY p.product_id, p.product_name, p.category
        ORDER BY total_sold DESC
    """.replace(":days", str(int(period_days))))
    return {"period_days": period_days, "products": rows}


def get_sales_trends() -> dict:
    """Compare sales from the most recent 7 days vs the prior 7 days to detect rising or falling demand.

    Returns:
        A dict with each product's recent sales, previous sales, percentage change, and trend direction (rising, falling, or stable).
    """
    rows = _query("""
        WITH date_range AS (
            SELECT MAX(sale_date) AS max_date FROM sales
        ),
        recent AS (
            SELECT product_id, SUM(quantity_sold) AS recent_sold
            FROM sales, date_range
            WHERE sale_date > max_date - INTERVAL '7 days'
            GROUP BY product_id
        ),
        previous AS (
            SELECT product_id, SUM(quantity_sold) AS prev_sold
            FROM sales, date_range
            WHERE sale_date > max_date - INTERVAL '14 days'
              AND sale_date <= max_date - INTERVAL '7 days'
            GROUP BY product_id
        )
        SELECT p.product_id, p.product_name,
               COALESCE(r.recent_sold, 0) AS recent_sold,
               COALESCE(pr.prev_sold, 0) AS prev_sold,
               CASE
                   WHEN COALESCE(pr.prev_sold, 0) = 0 THEN 0
                   ELSE ROUND(((COALESCE(r.recent_sold, 0) - COALESCE(pr.prev_sold, 0))::numeric
                        / pr.prev_sold) * 100, 1)
               END AS pct_change
        FROM products p
        LEFT JOIN recent r ON p.product_id = r.product_id
        LEFT JOIN previous pr ON p.product_id = pr.product_id
        ORDER BY pct_change DESC
    """)
    for row in rows:
        pct = float(row["pct_change"])
        if pct >= 10:
            row["trend"] = "rising"
        elif pct <= -10:
            row["trend"] = "falling"
        else:
            row["trend"] = "stable"
    return {"comparison": "last 7 days vs prior 7 days", "products": rows}


# --- Inventory Checker Tools ---


def get_inventory_status() -> dict:
    """Get current stock levels for all products with their reorder points.

    Returns:
        A dict with each product's current stock, reorder point, and status (critical, low, or healthy).
    """
    rows = _query("""
        SELECT p.product_id, p.product_name, p.category,
               i.current_stock, p.reorder_point, p.reorder_quantity,
               s.supplier_name, s.supplier_id
        FROM products p
        JOIN inventory i ON p.product_id = i.product_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        ORDER BY (i.current_stock::float / NULLIF(p.reorder_point, 0)) ASC
    """)
    for row in rows:
        stock = int(row["current_stock"])
        reorder = int(row["reorder_point"])
        if stock < reorder * 0.5:
            row["status"] = "critical"
        elif stock < reorder:
            row["status"] = "low"
        else:
            row["status"] = "healthy"
    return {"products": rows}


def get_low_stock_items() -> dict:
    """Get only items that are below their reorder point.

    Returns:
        A dict with products that need restocking, including current stock, reorder point, and supplier info.
    """
    rows = _query("""
        SELECT p.product_id, p.product_name, p.category,
               i.current_stock, p.reorder_point, p.reorder_quantity,
               s.supplier_name, s.contact_phone, s.email, s.lead_time_days
        FROM products p
        JOIN inventory i ON p.product_id = i.product_id
        JOIN suppliers s ON p.supplier_id = s.supplier_id
        WHERE i.current_stock < p.reorder_point
        ORDER BY (i.current_stock::float / NULLIF(p.reorder_point, 0)) ASC
    """)
    return {"low_stock_count": len(rows), "items": rows}


# --- Order Generator Tools ---


def create_purchase_order(order_items_json: str) -> dict:
    """Create a purchase order and push it to Google Sheets.

    Args:
        order_items_json: A JSON string containing a list of items to order.
            Each item should have: product_name, quantity, supplier_name, contact_phone.
            Example: [{"product_name": "BBQ Pork Bun", "quantity": 200, "supplier_name": "Ah Kow", "contact_phone": "+60129876543"}]

    Returns:
        A dict confirming the purchase order was created with a link to the Google Sheet.
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

    header = ["Product", "Quantity", "Supplier", "Contact Phone"]
    rows = [header]

    current_supplier = None
    for item in sorted(items, key=lambda x: x.get("supplier_name", "")):
        supplier = item.get("supplier_name", "Unknown")
        if supplier != current_supplier:
            if current_supplier is not None:
                rows.append(["", "", "", ""])
            rows.append([f"--- {supplier} ---", "", "", ""])
            current_supplier = supplier
        rows.append([
            item.get("product_name", ""),
            str(item.get("quantity", 0)),
            supplier,
            item.get("contact_phone", ""),
        ])

    worksheet.update(range_name="A1", values=rows)

    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheets_id}/edit"
    return {
        "status": "success",
        "message": f"Purchase order created with {len(items)} items",
        "sheet_title": sheet_title,
        "sheet_url": sheet_url,
    }
