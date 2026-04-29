FROM python:3.11-slim

WORKDIR /app

# Install curl + ca-certs for downloading MCP Toolbox binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install MCP Toolbox for Databases (sidecar binary)
# Pin to a specific version for reproducibility
ARG TOOLBOX_VERSION=v0.15.0
RUN curl -fsSL "https://storage.googleapis.com/genai-toolbox/${TOOLBOX_VERSION}/linux/amd64/toolbox" \
    -o /usr/local/bin/toolbox \
    && chmod +x /usr/local/bin/toolbox

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Make startup script executable
RUN chmod +x start.sh

EXPOSE 8080

CMD ["./start.sh"]
