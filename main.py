"""FastAPI app for Stock Manager multi-agent restocking system."""

import os
import uuid
import asyncio
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents import manager_agent

app = FastAPI(title="Stock Manager", version="1.0.0")

session_service = InMemorySessionService()

runner = Runner(
    agent=manager_agent,
    app_name="stock_manager",
    session_service=session_service,
)

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.post("/api/restock")
async def restock(request: Request):
    data = await request.json()
    user_message = data.get("message", "What should I restock this week?")
    session_id = data.get("session_id", str(uuid.uuid4()))
    user_id = "shop_owner"

    # Create session if it doesn't exist
    session = await session_service.get_session(
        app_name="stock_manager", user_id=user_id, session_id=session_id
    )
    if session is None:
        session = await session_service.create_session(
            app_name="stock_manager", user_id=user_id, session_id=session_id
        )

    content = types.Content(
        role="user", parts=[types.Part(text=user_message)]
    )

    # Retry up to 3 times on rate limit errors
    max_retries = 3
    for attempt in range(max_retries):
        try:
            all_texts = []
            async for event in runner.run_async(
                user_id=user_id, session_id=session_id, new_message=content
            ):
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text and part.text.strip():
                            all_texts.append(part.text.strip())

            response_text = all_texts[-1] if all_texts else "Sorry, I could not process your request. Please try again."
            return JSONResponse({"response": response_text, "session_id": session_id})

        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                if attempt < max_retries - 1:
                    await asyncio.sleep(5 * (attempt + 1))
                    # Create a fresh session for retry
                    session_id = str(uuid.uuid4())
                    await session_service.create_session(
                        app_name="stock_manager", user_id=user_id, session_id=session_id
                    )
                    continue
            return JSONResponse(
                {"response": "The system is busy right now. Please wait a moment and try again.", "session_id": session_id}
            )


@app.get("/api/inventory")
async def inventory():
    from tools import _query
    rows = _query("""
        SELECT p.product_name, p.category, i.current_stock, p.reorder_point,
               CASE
                   WHEN i.current_stock < p.reorder_point * 0.5 THEN 'critical'
                   WHEN i.current_stock < p.reorder_point THEN 'low'
                   ELSE 'healthy'
               END AS status
        FROM products p
        JOIN inventory i ON p.product_id = i.product_id
        ORDER BY (i.current_stock::float / NULLIF(p.reorder_point, 0)) ASC
    """)
    return JSONResponse({"products": rows})


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
