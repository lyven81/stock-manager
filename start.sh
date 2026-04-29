#!/bin/bash
# Container startup orchestration:
#   1. Run idempotent schema migration (adds vector column + populates embeddings)
#   2. Start MCP Toolbox sidecar in background (localhost:5000)
#   3. Wait until MCP Toolbox is healthy
#   4. Start FastAPI app (PORT=8080 by default)
set -e

echo "=== Stock Manager startup ==="

# Step 1: schema migration
echo "[start] running schema migration..."
python migrate_schema.py

# Step 2: launch MCP Toolbox sidecar in background
echo "[start] launching MCP Toolbox on localhost:5000..."
toolbox --tools-file tools.yaml --address 127.0.0.1 --port 5000 &
TOOLBOX_PID=$!
echo "[start] MCP Toolbox PID: $TOOLBOX_PID"

# Step 3: wait for toolbox to be ready (max 30 seconds)
echo "[start] waiting for MCP Toolbox to become healthy..."
for i in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:5000/api/toolset/stock-manager-tools >/dev/null 2>&1; then
        echo "[start] MCP Toolbox is ready"
        break
    fi
    if [ "$i" = "30" ]; then
        echo "[start] WARNING: MCP Toolbox did not become healthy within 30s"
    fi
    sleep 1
done

# Step 4: start FastAPI (foreground — Cloud Run waits on this)
echo "[start] starting FastAPI on port ${PORT:-8080}..."
exec python main.py
