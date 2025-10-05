# ============================================================================
# Local Development - Manual Service Startup Commands
# Copy and paste these commands into separate PowerShell terminals
# ============================================================================

Write-Host " Agentic Framework - Local Development Setup" -ForegroundColor Cyan
Write-Host ""
Write-Host "Copy and paste these commands into separate PowerShell terminals:" -ForegroundColor Yellow
Write-Host ""

# Get the agentic_framework directory
$agenticFrameworkDir = Split-Path -Parent $PSScriptRoot

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "TERMINAL 1: SQL MCP (Port 8001)" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "cd '$agenticFrameworkDir\mcps\sql'"
Write-Host "python server.py"
Write-Host ""

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "TERMINAL 2: Graph MCP (Port 8002)" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "cd '$agenticFrameworkDir\mcps\graph'"
Write-Host "python server.py"
Write-Host ""

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "TERMINAL 3: Interpreter MCP (Port 8003)" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "cd '$agenticFrameworkDir\mcps\interpreter'"
Write-Host "python server.py"
Write-Host ""

# Build MCP endpoints for orchestrator
$mcpEndpoints = '{"sql_mcp": "http://localhost:8001/mcp", "graph_mcp": "http://localhost:8002/mcp", "interpreter_mcp": "http://localhost:8003/mcp"}'
$listOfMcps = "sql_mcp,graph_mcp,interpreter_mcp"

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "TERMINAL 4: Orchestrator (Port 8000)" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "cd '$agenticFrameworkDir'"
Write-Host "`$env:MCP_ENDPOINTS='$mcpEndpoints'"
Write-Host "`$env:LIST_OF_MCPS='$listOfMcps'"
Write-Host "python -m uvicorn orchestrator.app:app --host 0.0.0.0 --port 8000 --log-level info"
Write-Host ""

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "Service URLs (after startup):" -ForegroundColor Yellow
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  Orchestrator:      http://localhost:8000" -ForegroundColor Green
Write-Host "  - Healthz:         http://localhost:8000/healthz" -ForegroundColor White
Write-Host "  - Chat API:        POST http://localhost:8000/chat" -ForegroundColor White
Write-Host ""
Write-Host "  SQL MCP:           http://localhost:8001/mcp" -ForegroundColor Gray
Write-Host "  Graph MCP:         http://localhost:8002/mcp" -ForegroundColor Gray
Write-Host "  Interpreter MCP:   http://localhost:8003/mcp" -ForegroundColor Gray
Write-Host ""

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "Quick Health Check:" -ForegroundColor Yellow
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "Invoke-RestMethod -Uri http://localhost:8000/healthz -Method Get"
Write-Host "Invoke-RestMethod -Uri http://localhost:8001/mcp -Method Get"
Write-Host "Invoke-RestMethod -Uri http://localhost:8002/mcp -Method Get"
Write-Host "Invoke-RestMethod -Uri http://localhost:8003/mcp -Method Get"
Write-Host ""

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "Stop All Services:" -ForegroundColor Yellow
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force"
Write-Host ""
