"""
Input validation tests - security-critical paths.

These tests verify that the server properly validates and rejects:
- Invalid namespace names (security: prevent command injection)
- Unknown resource types (prevent arbitrary kubectl commands)
- Invalid CPU/memory quantities (catch common mistakes early)
"""

import pytest
from fastapi.testclient import TestClient
from k8s_mcp_server.server import app

client = TestClient(app)


def test_invalid_namespace_with_underscore_rejected():
    """
    Namespaces must follow DNS label rules: lowercase alphanumeric and hyphens only.
    Underscores and other special chars should be rejected to prevent injection.
    """
    response = client.post(
        "/mcp/execute?session_id=test-validation",
        json={
            "instruction": "get_resources",
            "params": {
                "resource_type": "pods",
                "namespace": "invalid_namespace_name"  # Underscore is invalid!
            }
        }
    )
    
    assert response.status_code == 400
    assert "Invalid namespace" in response.json()["detail"]


def test_invalid_namespace_with_special_chars_rejected():
    """Verify special characters in namespace are rejected"""
    response = client.post(
        "/mcp/execute?session_id=test-validation",
        json={
            "instruction": "get_resources",
            "params": {
                "resource_type": "pods",
                "namespace": "namespace;rm -rf /"  # Injection attempt!
            }
        }
    )
    
    assert response.status_code == 400
    assert "Invalid" in response.json()["detail"]


def test_invalid_resource_type_rejected():
    """
    Only allowlisted resource types should be accepted.
    This prevents arbitrary kubectl commands.
    """
    response = client.post(
        "/mcp/execute?session_id=test-validation",
        json={
            "instruction": "get_resources",
            "params": {
                "resource_type": "malicious-resource-type",
                "namespace": "default"
            }
        }
    )
    
    assert response.status_code == 400
    assert "Invalid resource_type" in response.json()["detail"]


def test_invalid_memory_quantity_rejected():
    """
    Memory quantities must have valid units (Ki, Mi, Gi, etc.)
    Common typo "4i" should be caught with helpful suggestion.
    """
    response = client.post(
        "/mcp/execute?session_id=test-validation",
        json={
            "instruction": "create_deployment_apply",
            "params": {
                "deployment_name": "test-deployment",
                "image": "nginx",
                "namespace": "default",
                "memory_limit": "4i"  # Invalid! Should be "4Mi"
            }
        }
    )
    
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Invalid memory_limit" in detail
    # Server should suggest the fix
    assert "4Mi" in detail or "Did you mean" in detail


def test_invalid_cpu_quantity_rejected():
    """CPU must be a number (cores) or millicores with 'm' suffix"""
    response = client.post(
        "/mcp/execute?session_id=test-validation",
        json={
            "instruction": "create_deployment_apply",
            "params": {
                "deployment_name": "test-deployment",
                "image": "nginx",
                "namespace": "default",
                "cpu_limit": "invalid-cpu"
            }
        }
    )
    
    assert response.status_code == 400
    assert "Invalid cpu_limit" in response.json()["detail"]


def test_unknown_instruction_rejected():
    """Verify requests for non-existent instructions are rejected"""
    response = client.post(
        "/mcp/execute?session_id=test-validation",
        json={
            "instruction": "hack_the_planet",
            "params": {}
        }
    )
    
    assert response.status_code == 400
    assert "Unknown instruction" in response.json()["detail"]
