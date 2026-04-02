"""Stock Manager agent definitions using Google ADK."""

from google.adk.agents import Agent, SequentialAgent
from tools import (
    get_sales_summary,
    get_sales_trends,
    get_inventory_status,
    get_low_stock_items,
    create_purchase_order,
)

# Sub-agent 1: Sales Analyst
sales_analyst = Agent(
    name="sales_analyst",
    model="gemini-2.5-flash",
    instruction="""You are the Sales Analyst agent for a steam bun shop.

Analyze sales data by calling BOTH tools:
1. Call get_sales_summary for average daily sales per product.
2. Call get_sales_trends to detect rising or falling demand week-over-week.

Return a summary listing:
- Top 5 fast movers (highest daily sales)
- Top 5 slow movers (lowest daily sales)
- All products with RISING trends (10%+ increase) — these are important for early restocking decisions

Be concise. Use product names and numbers.""",
    tools=[get_sales_summary, get_sales_trends],
)

# Sub-agent 2: Inventory Checker
inventory_checker = Agent(
    name="inventory_checker",
    model="gemini-2.5-flash",
    instruction="""You are the Inventory Checker agent for a steam bun shop.

Check stock levels by calling BOTH tools:
1. Call get_inventory_status for all products with stock levels, reorder points, and supplier info.
2. Call get_low_stock_items for items below their reorder point.

Return a summary listing:
- All critical items (below 50% of reorder point) with: product name, current stock, reorder point, reorder quantity, supplier name, contact phone
- All low items (below reorder point) with same details
- Note which items have healthy stock

Be concise. Use product names and numbers.""",
    tools=[get_inventory_status, get_low_stock_items],
)

# Sub-agent 3: Restock Decision Maker
restock_decider = Agent(
    name="restock_decider",
    model="gemini-2.5-flash",
    instruction="""You are the Restock Decision agent for a steam bun shop.

Review the sales analysis and inventory check from previous agents in this conversation.
Decide which items to restock based on these rules:

1. LOW STOCK: current stock is below reorder point → ALWAYS restock
2. TRENDING UP: demand is rising (10%+ increase) AND stock is within 1.5x of reorder point → restock early to prevent future stockout
3. HEALTHY + STABLE/FALLING: skip — no restock needed

Create a final restock list. For each item include:
- product_name, quantity (use the reorder_quantity), supplier_name, contact_phone, reason (Low Stock or Trending Up)

Then call create_purchase_order with a JSON string of items to order.
Each item in the JSON must have: product_name, quantity, supplier_name, contact_phone.

After the purchase order is created, return a clear summary:
- Total items to restock
- A table: Product | Current Stock | Reorder Point | Order Qty | Reason
- The Google Sheets link from the purchase order confirmation""",
    tools=[create_purchase_order],
)

# Manager: SequentialAgent chains all sub-agents in order
manager_agent = SequentialAgent(
    name="stock_manager",
    sub_agents=[sales_analyst, inventory_checker, restock_decider],
)
