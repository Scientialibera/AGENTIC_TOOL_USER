# Graph MCP Server
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY mcps/graph/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared library (from parent context)
COPY shared/ /app/shared/

# Copy MCP server
COPY mcps/__init__.py /app/mcps/
COPY mcps/graph/ /app/mcps/graph/

# Set Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

# Run the server
CMD ["python", "-m", "mcps.graph.server"]
