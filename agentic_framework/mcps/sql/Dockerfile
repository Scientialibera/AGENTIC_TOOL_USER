# SQL MCP Server
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    unixodbc-dev \
    curl \
    gnupg2 \
    && rm -rf /var/lib/apt/lists/*

# Install Microsoft ODBC Driver for SQL Server (updated method for Debian 12+)
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY mcps/sql/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared library (from parent context)
COPY shared/ /app/shared/

# Copy MCP server
COPY mcps/__init__.py /app/mcps/
COPY mcps/sql/ /app/mcps/sql/

# Set Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8001

# Run the server
CMD ["python", "-m", "mcps.sql.server"]
