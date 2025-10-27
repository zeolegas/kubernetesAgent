# Start MCP Server with Windows-compatible asyncio loop
# This script ensures subprocess calls work properly on Windows

$env:PYTHONPATH = "src"

Write-Host "Starting K8s MCP Server on http://0.0.0.0:8080..."
Write-Host "Using ProactorEventLoop for Windows subprocess support"
Write-Host ""

python -m k8s_mcp_server
