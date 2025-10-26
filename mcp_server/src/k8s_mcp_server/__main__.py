"""
Entry point for running the MCP server with proper Windows event loop setup.
This ensures subprocess calls work correctly on Windows.

IMPORTANT: On Windows, auto-reload is disabled because the reloader spawns
a child process that doesn't inherit the ProactorEventLoop policy.
"""
import sys
import asyncio

# CRITICAL: Set event loop policy BEFORE importing anything that uses asyncio
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    print("✓ Windows ProactorEventLoop policy configured")

if __name__ == "__main__":
    import uvicorn
    
    # Disable reload on Windows to avoid event loop policy issues
    use_reload = sys.platform != 'win32'
    
    if sys.platform == 'win32':
        print("✓ Auto-reload disabled on Windows (prevents event loop issues)")
        print("✓ Server starting on http://0.0.0.0:8080")
        print("  To apply code changes, stop (Ctrl+C) and restart the server")
    
    uvicorn.run(
        "k8s_mcp_server.server:app",
        host="0.0.0.0",
        port=8080,
        reload=use_reload,
        log_level="info"
    )
