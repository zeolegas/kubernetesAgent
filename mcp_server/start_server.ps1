# Start MCP Server with Windows-compatible asyncio loop
# This script ensures subprocess calls work properly on Windows

$env:PYTHONPATH = "src"
$pythonExe = "C:\Users\joseo\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\Local\pypoetry\Cache\virtualenvs\k8s-mcp-server-ZzDOt2Ac-py3.12\Scripts\python.exe"

Write-Host "Starting K8s MCP Server on http://0.0.0.0:8080..."
Write-Host "Using ProactorEventLoop for Windows subprocess support"
Write-Host ""

& $pythonExe -m k8s_mcp_server
