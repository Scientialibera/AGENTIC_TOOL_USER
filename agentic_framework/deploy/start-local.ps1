# ============================================================================
# Local Development Startup Script
# Starts all MCP servers and the orchestrator on different ports
# ============================================================================

param(
    [Parameter(Mandatory=$false)]
    [switch]$SkipPythonCheck,
    
    [Parameter(Mandatory=$false)]
    [switch]$KillExisting
)

$ErrorActionPreference = "Stop"

Write-Host " Starting Agentic Framework (Local Development)" -ForegroundColor Cyan
Write-Host ""

# Get the agentic_framework directory
$agenticFrameworkDir = Split-Path -Parent $PSScriptRoot

# Check if Python is available
if (-not $SkipPythonCheck) {
    Write-Host "Checking Python..." -ForegroundColor Cyan
    try {
        $pythonVersion = python --version 2>&1
        Write-Host " Python found: $pythonVersion" -ForegroundColor Green
    } catch {
        Write-Host " Error: Python not found in PATH" -ForegroundColor Red
        Write-Host "Please install Python or add it to PATH" -ForegroundColor Yellow
        exit 1
    }
}

# Kill existing Python processes if requested
if ($KillExisting) {
    Write-Host "`n Stopping existing Python processes..." -ForegroundColor Yellow
    Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
    Write-Host " Stopped existing processes" -ForegroundColor Green
}

# Check for port conflicts
Write-Host "`n Checking for port conflicts..." -ForegroundColor Cyan
$portsToCheck = @(8000, 8001, 8002, 8003)
$portsInUse = @()

foreach ($port in $portsToCheck) {
    $connection = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($connection) {
        $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
        $portsInUse += @{
            Port = $port
            Process = $process.Name
            PID = $connection.OwningProcess
        }
    }
}

if ($portsInUse.Count -gt 0) {
    Write-Host " Warning: The following ports are already in use:" -ForegroundColor Yellow
    foreach ($portInfo in $portsInUse) {
        Write-Host "  Port $($portInfo.Port): $($portInfo.Process) (PID: $($portInfo.PID))" -ForegroundColor Yellow
    }
    Write-Host ""
    $confirm = Read-Host "Do you want to kill these processes and continue? (y/N)"
    if ($confirm -eq "y" -or $confirm -eq "Y") {
        foreach ($portInfo in $portsInUse) {
            Stop-Process -Id $portInfo.PID -Force
        }
        Start-Sleep -Seconds 2
        Write-Host " Processes stopped" -ForegroundColor Green
    } else {
        Write-Host "Exiting. Please stop the processes manually or use -KillExisting flag" -ForegroundColor Yellow
        exit 1
    }
}

# ============================================================================
# DYNAMIC MCP DISCOVERY
# ============================================================================
Write-Host "`n Discovering MCP servers..." -ForegroundColor Cyan

$mcpsDir = Join-Path $agenticFrameworkDir "mcps"

# Discover all MCP folders
$mcpFolders = Get-ChildItem -Path $mcpsDir -Directory | Where-Object {
    $_.Name -notmatch '^(__pycache__|TEMPLATE|\.)'
}

# Build MCP metadata array
$mcpServers = @()
$startPort = 8001  # MCPs start at 8001

foreach ($mcpFolder in $mcpFolders) {
    $mcpName = $mcpFolder.Name
    $mcpServerPath = Join-Path $mcpFolder.FullName "server.py"
    
    # Check if server.py exists
    if (Test-Path $mcpServerPath) {
        $mcpServers += @{
            Name = $mcpName
            Port = $startPort
            Path = $mcpFolder.FullName
            ServerFile = $mcpServerPath
        }
        
        Write-Host "  Found MCP: $mcpName (port $startPort)" -ForegroundColor Green
        $startPort++
    } else {
        Write-Host "  Skipping $mcpName (no server.py found)" -ForegroundColor Yellow
    }
}

Write-Host " Discovered $($mcpServers.Count) MCP server(s)" -ForegroundColor Green

# Build MCP_ENDPOINTS for orchestrator
$mcpEndpointsHash = @{}
foreach ($mcp in $mcpServers) {
    $mcpEndpointsHash["$($mcp.Name)_mcp"] = "http://localhost:$($mcp.Port)/mcp"
}

$mcpEndpointsJson = ($mcpEndpointsHash | ConvertTo-Json -Compress)
$listOfMcps = ($mcpServers | ForEach-Object { "$($_.Name)_mcp" }) -join ","

Write-Host "`n MCP Configuration:" -ForegroundColor Cyan
Write-Host "  LIST_OF_MCPS: $listOfMcps" -ForegroundColor Gray
Write-Host "  MCP_ENDPOINTS: $mcpEndpointsJson" -ForegroundColor Gray

# ============================================================================
# START SERVICES
# ============================================================================
Write-Host "`n Starting services..." -ForegroundColor Cyan
Write-Host "All services will run in new PowerShell windows" -ForegroundColor Yellow
Write-Host ""

# Start each MCP server in a new window
foreach ($mcp in $mcpServers) {
    Write-Host "Starting $($mcp.Name) MCP on port $($mcp.Port)..." -ForegroundColor Yellow
    
    # Set environment variables for FastMCP to use correct host/port
    $startCommand = "cd '$($mcp.Path)'; `$env:FASTMCP_HOST='0.0.0.0'; `$env:FASTMCP_PORT='$($mcp.Port)'; Write-Host ' $($mcp.Name) MCP Server (Port $($mcp.Port))' -ForegroundColor Cyan; Write-Host 'Host: 0.0.0.0, Port: $($mcp.Port)' -ForegroundColor Gray; Write-Host ''; python server.py"
    
    Start-Process -FilePath "powershell" -ArgumentList "-NoExit", "-Command", $startCommand
    Start-Sleep -Milliseconds 1000  # Delay between starts to avoid race conditions
}

# Start Orchestrator in a new window
Write-Host "Starting Orchestrator on port 8000..." -ForegroundColor Yellow

# Set MCP_ENDPOINTS and LIST_OF_MCPS as environment variables for orchestrator
$env:MCP_ENDPOINTS = $mcpEndpointsJson
$env:LIST_OF_MCPS = $listOfMcps

$orchCommand = "cd '$agenticFrameworkDir'; `$env:MCP_ENDPOINTS='$mcpEndpointsJson'; `$env:LIST_OF_MCPS='$listOfMcps'; Write-Host ' Orchestrator API (Port 8000)' -ForegroundColor Cyan; Write-Host ''; Write-Host 'MCP_ENDPOINTS: $mcpEndpointsJson' -ForegroundColor Gray; Write-Host 'LIST_OF_MCPS: $listOfMcps' -ForegroundColor Gray; Write-Host ''; python -m uvicorn orchestrator.app:app --host 0.0.0.0 --port 8000 --log-level info"

Start-Process -FilePath "powershell" -ArgumentList "-NoExit", "-Command", $orchCommand

# ============================================================================
# SUMMARY
# ============================================================================
Start-Sleep -Seconds 2

Write-Host "`n Services Started!" -ForegroundColor Green
Write-Host "`n Service URLs:" -ForegroundColor Cyan
Write-Host "  Orchestrator API: http://localhost:8000" -ForegroundColor Green
Write-Host "  - Health (no auth): http://localhost:8000/healthz" -ForegroundColor White
Write-Host "  - Health (with auth): http://localhost:8000/health" -ForegroundColor White
Write-Host "  - Chat API: POST http://localhost:8000/chat" -ForegroundColor White

Write-Host "`n MCP Servers:" -ForegroundColor Cyan
foreach ($mcp in $mcpServers) {
    Write-Host "  $($mcp.Name) MCP: http://localhost:$($mcp.Port)/mcp" -ForegroundColor Gray
}

Write-Host "`n Quick Test Commands:" -ForegroundColor Cyan
Write-Host "  # Test orchestrator health (no auth required)" -ForegroundColor Gray
Write-Host "  Invoke-RestMethod -Uri http://localhost:8000/healthz -Method Get" -ForegroundColor White
Write-Host ""
Write-Host "  # Test MCP health" -ForegroundColor Gray
foreach ($mcp in $mcpServers) {
    Write-Host "  Invoke-RestMethod -Uri http://localhost:$($mcp.Port)/mcp -Method Get" -ForegroundColor White
}

Write-Host "`n Notes:" -ForegroundColor Yellow
Write-Host "  - All services are running in separate PowerShell windows" -ForegroundColor Gray
Write-Host "  - Close the windows or press Ctrl+C in each to stop services" -ForegroundColor Gray
Write-Host "  - Check .env file for DEV_MODE and BYPASS_TOKEN settings" -ForegroundColor Gray
Write-Host "  - Logs are visible in each service window" -ForegroundColor Gray
Write-Host ""
