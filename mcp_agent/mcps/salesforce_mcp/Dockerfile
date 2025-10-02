FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including ODBC driver for SQL Server
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    unixodbc \
    unixodbc-dev \
    curl \
    gnupg \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared module
COPY ../../shared /app/shared

# Copy salesforce_mcp source
COPY src /app

# Set Python path to include shared module
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8001

# Run the application
CMD ["python", "main.py"]
