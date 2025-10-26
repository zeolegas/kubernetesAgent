"""
Unit tests for kubectl command generation in prompts.py

These tests verify that prompt functions build correct kubectl commands.
They don't execute kubectl - just check the command string is correct.
"""

import pytest
from k8s_mcp_server.prompts import (
    get_resources,
    scale_deployment,
    describe_resource,
    delete_pod,
)


def test_get_resources_builds_correct_command():
    """Verify get_resources generates proper kubectl get command"""
    cmd = get_resources(
        resource_type="pods",
        namespace="production",
        all_namespaces=False
    )
    
    # Should contain the kubectl command
    assert "kubectl get pods" in cmd
    
    # Should target the correct namespace
    assert "-n production" in cmd or "--namespace production" in cmd or "--namespace=production" in cmd
    
    # Should NOT have --all-namespaces flag
    assert "--all-namespaces" not in cmd and "-A" not in cmd


def test_get_resources_with_all_namespaces():
    """Verify --all-namespaces flag is added when requested"""
    cmd = get_resources(
        resource_type="deployments",
        all_namespaces=True
    )
    
    assert "kubectl get deployments" in cmd or "kubectl get deployment" in cmd
    assert "--all-namespaces" in cmd or "-A" in cmd


def test_scale_deployment_includes_replicas():
    """Verify scale command includes deployment name and replica count"""
    cmd = scale_deployment(
        deployment_name="my-app",
        replicas=5,
        namespace="staging"
    )
    
    assert "kubectl scale" in cmd
    assert "my-app" in cmd
    assert "replicas=5" in cmd or "--replicas=5" in cmd or "--replicas 5" in cmd
    assert "-n staging" in cmd or "--namespace staging" in cmd or "--namespace=staging" in cmd


def test_describe_resource_command():
    """Verify describe builds correct command with resource type and name"""
    cmd = describe_resource(
        resource_type="pod",
        resource_name="test-pod-123",
        namespace="default"
    )
    
    assert "kubectl describe" in cmd
    assert "pod" in cmd
    assert "test-pod-123" in cmd
    assert "-n default" in cmd or "--namespace default" in cmd or "--namespace=default" in cmd


def test_delete_pod_command():
    """Verify delete pod command is built correctly"""
    cmd = delete_pod(
        pod_name="old-pod",
        namespace="default",
        ignore_not_found=True,
        wait=False
    )
    
    assert "kubectl delete pod" in cmd
    assert "old-pod" in cmd
    assert "--ignore-not-found" in cmd
    assert "-n default" in cmd or "--namespace default" in cmd or "--namespace=default" in cmd


def test_delete_pod_with_force():
    """Verify force delete includes grace period and force flags"""
    cmd = delete_pod(
        pod_name="stuck-pod",
        namespace="default",
        force=True,
        grace_period=0
    )
    
    assert "kubectl delete pod" in cmd
    assert "stuck-pod" in cmd
    assert "--force" in cmd
    assert "--grace-period=0" in cmd or "--grace-period 0" in cmd
