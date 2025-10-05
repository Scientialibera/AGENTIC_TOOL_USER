# Interpreter MCP Server
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    gnupg2 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY mcps/interpreter/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared library (from parent context)
COPY shared/ /app/shared/

# Copy MCP server
COPY mcps/__init__.py /app/mcps/
COPY mcps/interpreter/ /app/mcps/interpreter/

# Set Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8003

# Run the server
CMD ["python", "-m", "mcps.interpreter.server"]
