"""
Integration tests that execute actual kubectl commands.

These tests verify:
- Subprocess execution works (Windows ProactorEventLoop)
- Real kubectl commands can be executed
- Command output is properly captured

NOTE: These tests require kubectl to be installed and configured.
They will attempt to connect to the current kubectl context.
"""

import pytest
from fastapi.testclient import TestClient
from k8s_mcp_server.server import app

client = TestClient(app)


@pytest.mark.integration
def test_get_pods_executes_real_kubectl_command():
    """
    Test that actually executes kubectl command via subprocess.
    
    This test verifies:
    1. Windows asyncio ProactorEventLoop is working
    2. Subprocess creation succeeds
    3. kubectl command executes (may fail if no cluster)
    4. Output is captured and returned
    
    This is the test that would have caught the Windows NotImplementedError bug!
    """
    response = client.post(
        "/mcp/execute?session_id=test-integration",
        json={
            "instruction": "get_resources",
            "params": {
                "resource_type": "pods",
                "namespace": "default"
            }
        }
    )
    
    # Should return 200 regardless of kubectl success/failure
    assert response.status_code == 200
    
    data = response.json()
    
    # Verify response structure
    assert "command" in data, "Response missing 'command' field"
    assert "stdout" in data, "Response missing 'stdout' field"
    assert "stderr" in data, "Response missing 'stderr' field"
    assert "returncode" in data, "Response missing 'returncode' field"
    
    # Verify kubectl command was constructed
    assert "kubectl" in data["command"].lower()
    assert "get" in data["command"].lower()
    assert "pods" in data["command"].lower()
    
    # If returncode is 0, kubectl succeeded (cluster available)
    # If returncode is non-zero, kubectl failed (no cluster, but subprocess worked!)
    # Either way, we got a response = subprocess execution worked!
    
    print(f"\n✅ Subprocess execution successful!")
    print(f"Command: {data['command']}")
    print(f"Return code: {data['returncode']}")
    
    if data['returncode'] == 0:
        print(f"✅ kubectl succeeded - cluster is available")
        print(f"Output length: {len(data['stdout'])} chars")
    else:
        print(f"⚠️  kubectl failed (likely no cluster configured) but subprocess worked!")
        print(f"Error: {data['stderr'][:200]}")  # First 200 chars of error


@pytest.mark.integration
def test_namespace_validation_before_execution():
    """
    Verify validation happens BEFORE subprocess execution.
    
    Invalid namespace should be rejected without executing kubectl.
    """
    response = client.post(
        "/mcp/execute?session_id=test-integration",
        json={
            "instruction": "get_resources",
            "params": {
                "resource_type": "pods",
                "namespace": "invalid_name_with_underscore"
            }
        }
    )
    
    # Should fail validation with 400, never reaching subprocess
    assert response.status_code == 400
    assert "Invalid namespace" in response.json()["detail"]
