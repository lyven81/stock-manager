"""Stock Manager agent definitions using Google ADK.

Refined for Top 100 stage:
  - Sales Analyst now also calls find_similar_pattern_items (vector search)
  - All AlloyDB access flows through MCP Toolbox (see tools.py)
  - Restock Decider considers 3 trigger types: low stock, trending up, similar pattern
"""

from google.adk.agents import Agent, SequentialAgent
from tools import (
    get_sales_summary,
    get_sales_trends,
    find_similar_pattern_items,
    get_inventory_status,
    get_low_stock_items,
    create_purchase_order,
)

# Sub-agent 1: Sales Analyst — now with vector similarity search
sales_analyst = Agent(
    name="sales_analyst",
    model="gemini-2.5-flash",
    instruction="""You are the Sales Analyst agent for a steam bun shop.

Analyze sales data in three steps:

STEP 1 — Call get_sales_summary(period_days=7) to find average daily sales per product.

STEP 2 — Call get_sales_trends to detect rising/falling demand week-over-week.

STEP 3 — Identify the TOP fast mover (highest avg_daily). Then call
find_similar_pattern_items(reference_product_id=<that_top_fast_mover_id>, top_n=5)
to find products whose 6-week sales velocity pattern is similar to that fast mover.
These are candidates for PREDICTIVE restocking — they may not be fast movers yet,
but they are behaving like one.

Return a concise summary with three sections:
1. TOP 5 fast movers (highest daily sales, with product name + avg_daily)
2. RISING products (10%+ increase week-over-week, with pct_change)
3. SIMILAR-PATTERN candidates: top 5 products that share a sales pattern with the
   #1 fast mover. For each, show product_name + similarity_score (0-1).

All tool calls go through MCP Toolbox — do not bypass it.""",
    tools=[get_sales_summary, get_sales_trends, find_similar_pattern_items],
)

# Sub-agent 2: Inventory Checker
inventory_checker = Agent(
    name="inventory_checker",
    model="gemini-2.5-flash",
    instruction="""You are the Inventory Checker agent for a steam bun shop.

Check stock levels by calling BOTH tools (both via MCP Toolbox):
1. Call get_inventory_status for all products with stock levels, reorder points, supplier info.
2. Call get_low_stock_items for items below their reorder point.

Return a concise summary listing:
- All CRITICAL items (status='critical', below 50% of reorder point) with: product_name,
  current_stock, reorder_point, reorder_quantity, supplier_name, contact_phone
- All LOW items (status='low', below reorder point) with same details
- Note which items have HEALTHY stock

Be concise. Use product names and numbers.""",
    tools=[get_inventory_status, get_low_stock_items],
)

# Sub-agent 3: Restock Decision Maker — now handles 3 trigger types
restock_decider = Agent(
    name="restock_decider",
    model="gemini-2.5-flash",
    instruction="""You are the Restock Decision agent for a steam bun shop.

Review the sales analysis and inventory check from previous agents. Decide which items
to restock based on THREE trigger conditions (any one is enough):

TRIGGER 1 — LOW STOCK: current_stock < reorder_point. Reason = "Low Stock".

TRIGGER 2 — TRENDING UP: trend = 'rising' (>=10% week-over-week increase) AND
current_stock is within 1.5x of reorder_point. Reason = "Trending Up".

TRIGGER 3 — SIMILAR PATTERN (NEW): the product appears in the Sales Analyst's
similar-pattern candidates list (similarity_score >= 0.7) AND its current_stock is
within 1.5x of reorder_point. These are predictive restocks — items behaving like
fast sellers that may stockout earlier than basic alerts would catch.
Reason = "Similar Pattern".

Skip products with healthy stock that don't trigger any condition.

For each item to restock, capture:
  product_name, quantity (= reorder_quantity), supplier_name, contact_phone, reason

Then call create_purchase_order with a JSON string of items. Each JSON item must have
these keys: product_name, quantity, supplier_name, contact_phone, reason.

After the purchase order is created, return a clear summary:
- Total items to restock
- Breakdown by reason: how many Low Stock vs Trending Up vs Similar Pattern
- A table: Product | Current Stock | Reorder Point | Order Qty | Reason
- The Google Sheets link from the confirmation""",
    tools=[create_purchase_order],
)

# Manager: SequentialAgent chains all sub-agents in order
manager_agent = SequentialAgent(
    name="stock_manager",
    sub_agents=[sales_analyst, inventory_checker, restock_decider],
)
