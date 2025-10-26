"""
Basic health and availability tests for the MCP server.

These tests verify:
- Server starts and responds
- API endpoints are accessible
- Instructions are properly registered
"""

import pytest
from fastapi.testclient import TestClient
from k8s_mcp_server.server import app

# Create a test client (doesn't require actual server to be running)
client = TestClient(app)


def test_root_endpoint_responds():
    """Verify server health check endpoint is working"""
    response = client.get("/")
    
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "K8s MCP Server" in data["message"]


def test_instructions_endpoint_returns_commands():
    """Verify instructions endpoint lists available kubectl operations"""
    response = client.get("/mcp/instructions")
    
    assert response.status_code == 200
    data = response.json()
    
    # Should have an instructions key
    assert "instructions" in data
    instructions = data["instructions"]
    
    # Should have multiple commands available
    assert len(instructions) > 0
    
    # Verify some expected commands are present
    assert "get_resources" in instructions
    assert "create_deployment_apply" in instructions
    
    # Each instruction should have documentation and arguments
    for name, details in instructions.items():
        assert "__doc__" in details, f"{name} missing documentation"
        assert "arguments" in details, f"{name} missing arguments definition"


def test_missing_session_id_rejected():
    """Verify requests without session_id are rejected"""
    response = client.post(
        "/mcp/execute",  # Missing ?session_id=xxx
        json={
            "instruction": "get_resources",
            "params": {"resource_type": "pods"}
        }
    )
    
    assert response.status_code == 400
    assert "session_id is required" in response.json()["detail"]
