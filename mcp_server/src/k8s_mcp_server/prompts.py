"""
Kubernetes kubectl command builders for the MCP server.

This module generates kubectl commands for various Kubernetes operations.
Functions return command strings that are executed by the server.
"""

import textwrap
import base64


# =============================================================================
# GENERIC RESOURCE OPERATIONS
# =============================================================================

def get_resources(
    resource_type: str,
    resource_name: str = "",
    namespace: str = "default",
    all_namespaces: bool = False,
    structured_output: bool = False,
    label_selector: str = "",
) -> str:
    """
    Gets one or more resources.
    
    Args:
        resource_type: The type of resource (e.g., 'pods', 'svc', 'deployments').
        resource_name: The specific name of the resource (optional).
        namespace: The namespace to query (ignored if all_namespaces is True).
        all_namespaces: If True, query across all namespaces (uses -A).
        structured_output: If True, append '-o json' to the command.
        label_selector: Optional Kubernetes label selector string (e.g., 'app=myapp,env in (staging,prod)').
                        Ignored when resource_name is provided.
    """
    selector_part = f"-l \"{label_selector}\"" if (label_selector and not resource_name) else ""
    if all_namespaces:
        cmd = f"kubectl get {resource_type} -A {selector_part}".strip()
        return f"{cmd} -o json" if structured_output else cmd
    if resource_name:
        cmd = f"kubectl get {resource_type} {resource_name} -n {namespace}"
        return f"{cmd} -o json" if structured_output else cmd
    cmd = f"kubectl get {resource_type} -n {namespace} {selector_part}".strip()
    return f"{cmd} -o json" if structured_output else cmd


def describe_resource(
    resource_type: str,
    resource_name: str,
    namespace: str = "default",
    full_yaml: bool = False,
    structured_output: bool = False,
) -> str:
    """
    Describes a specific resource.
    
    Args:
        resource_type: The type of resource (e.g., 'pods', 'deployments').
        resource_name: The specific name of the resource (required).
        namespace: The namespace to query.
        full_yaml: If True, returns the full resource definition in YAML format 
                   (uses 'kubectl get -o yaml' instead of 'describe').
    """
    if structured_output:
        return f"kubectl get {resource_type} {resource_name} -n {namespace} -o json"
    if full_yaml:
        return f"kubectl get {resource_type} {resource_name} -n {namespace} -o yaml"
    return f"kubectl describe {resource_type} {resource_name} -n {namespace}"


def get_events(namespace: str = "default", watch: bool = False, sort_by_time: bool = True) -> str:
    """
    Gets cluster events.
    
    Args:
        namespace: The namespace to query (or use -A for all).
        watch: If True, streams the events as they occur (-w).
        sort_by_time: If True, sorts events by timestamp (recommended).
    """
    watch_str = "-w" if watch else ""
    sort_str = "--sort-by='.lastTimestamp'" if sort_by_time else ""
    
    if namespace.lower() in ("all", "*"):
         return f"kubectl get events -A {watch_str} {sort_str}".strip()
    return f"kubectl get events -n {namespace} {watch_str} {sort_str}".strip()


# =============================================================================
# POD OPERATIONS
# =============================================================================

def get_pod_logs(
    pod_name: str = "",
    namespace: str = "default",
    container: str = "",
    previous: bool = False,
    follow: bool = False,
    label_selector: str = "",
    all_containers: bool = False,
) -> str:
    """
    Gets the logs of a pod.
    
    Args:
        pod_name: The name of the pod. If omitted, you can use label_selector to target pods.
        namespace: The namespace to query.
        container: The container name within the pod (optional).
        previous: If True, retrieve logs for the previously terminated container instance (-p).
        follow: If True, stream new logs as they appear (-f).
        label_selector: Optional Kubernetes label selector (uses '-l'). Ignored if pod_name is provided.
        all_containers: If True, include logs from all containers in the selected pod(s).
    """
    container_part = f"-c {container}" if (container and not all_containers) else ""
    previous_part = "-p" if previous else ""
    follow_part = "-f" if follow else ""
    all_cont_part = "--all-containers" if all_containers else ""
    selector_part = f"-l \"{label_selector}\"" if (label_selector and not pod_name) else ""
    
    flags = f"{container_part} {all_cont_part} {previous_part} {follow_part} {selector_part}".strip()
    base = f"kubectl logs -n {namespace}"
    if selector_part:
        return f"{base} {flags}".strip()
    if not pod_name:
        return "# Error: Provide 'pod_name' or 'label_selector' to select target pods for logs"
    return f"{base} {pod_name} {flags}".strip()


def get_pod_usage(
    resource_type: str = "pods",
    resource_name: str = "",
    namespace: str = "default",
    all_namespaces: bool = False,
    sort_by: str = ""
) -> str:
    """
    Retrieves current resource (CPU/Memory) consumption metrics for pods or nodes.
    Requires the Kubernetes Metrics Server to be running in the cluster.

    Args:
        resource_type: The type of resource to get metrics for ('pods' or 'nodes').
        resource_name: The specific name of the resource (optional).
        namespace: The namespace to query (ignored if all_namespaces is True).
        all_namespaces: If True, query across all namespaces (uses -A).
        sort_by: Optional sort column ('cpu', 'memory', or '').
    """
    cmd = f"kubectl top {resource_type}"

    if resource_name:
        cmd += f" {resource_name}"
        
    if all_namespaces:
        cmd += " -A"
    elif namespace and not resource_name:
        cmd += f" -n {namespace}"
    
    if sort_by:
        if resource_type == 'pods':
            cmd += f" --sort-by='.{sort_by}'"
        else:
            cmd += f" --sort-by={sort_by}"

    return cmd


def delete_pod(
    pod_name: str,
    namespace: str = "default",
    ignore_not_found: bool = True,
    wait: bool = False,
    force: bool = False,
    grace_period: int = 0,
) -> str:
    """
    Deletes a single Pod by name. Intended for isolated, --restart=Never diagnostic pods
    like 'curltest' or 'dnscheck'. Safe to call even if the pod is already gone.

    Args:
        pod_name: Name of the pod to delete.
        namespace: Target namespace.
        ignore_not_found: If True, don't error if the pod doesn't exist.
        wait: If False, return immediately without waiting for deletion to complete.
        force: If True, force immediate deletion (adds --force with grace-period=0). Use only if stuck.
        grace_period: Seconds to wait before terminating the pod. 0 for immediate.
    """
    parts = [
        "kubectl delete pod",
        pod_name,
        f"-n {namespace}",
    ]
    if ignore_not_found:
        parts.append("--ignore-not-found")
    parts.append(f"--grace-period={int(grace_period)}")
    if not wait:
        parts.append("--wait=false")
    if force:
        parts.append("--force")
    return " ".join(parts).strip()


def delete_completed_pods(
    namespace: str = "default",
    label_selector: str = "",
    ignore_not_found: bool = True,
    wait: bool = False,
) -> str:
    """
    Deletes pods in phase Succeeded (typically Completed) in a namespace.
    Optionally scopes by label selector (e.g., app=myapp).

    Args:
        namespace: Namespace to target.
        label_selector: Optional Kubernetes label selector string.
        ignore_not_found: If True, don't error if no pods match.
        wait: If False, return immediately without waiting for deletion to finish.

    Notes:
        - Uses a field selector to match only Succeeded pods (Completed jobs/one-shots).
        - Label selector is combined (logical AND) with the field selector when provided.
    """
    selector_part = f"-l \"{label_selector}\"" if label_selector else ""
    parts = [
        "kubectl delete pod",
        f"-n {namespace}",
        selector_part,
        "--field-selector=status.phase=Succeeded",
    ]
    if ignore_not_found:
        parts.append("--ignore-not-found")
    if not wait:
        parts.append("--wait=false")
    return " ".join(p for p in parts if p).strip()


def dns_lookup(name: str, namespace: str = "default", pod_name: str = "dnscheck", replace_existing: bool = False) -> str:
    """
    Performs an in-cluster DNS lookup using the official dnsutils image.

    Args:
        name: DNS name to resolve (e.g., 'php-apache.default.svc.cluster.local').
        namespace: Namespace to create the short-lived pod in.
        pod_name: Name of the diagnostic pod to create.

    Usage:
        - Run this instruction, then use get_pod_logs(pod_name, follow=False) to see results,
          and delete the pod when done.
    """
    image = "registry.k8s.io/e2e-test-images/jessie-dnsutils:1.3"
    run_cmd = (
        f"kubectl run {pod_name} -n {namespace} --image={image} --restart=Never -- "
        f"nslookup {name}"
    )
    if replace_existing:
        return f"kubectl delete pod {pod_name} -n {namespace} --ignore-not-found; {run_cmd}"
    return run_cmd


def curl_test(url: str, namespace: str = "default", pod_name: str = "curltest", replace_existing: bool = False) -> str:
    """
    Performs a one-shot HTTP reachability test from inside the cluster using curl.

    Args:
        url: The URL to test (e.g., 'http://php-apache.default.svc.cluster.local/').
        namespace: Namespace to create the short-lived pod in.
        pod_name: Name of the diagnostic pod to create.

    Notes:
        - Avoids curl -w percent format to keep it Windows-shell friendly.
        - Prints 'OK' on 2xx, 'FAIL' otherwise. View via get_pod_logs.
    """
    run_cmd = (
        f"kubectl run {pod_name} -n {namespace} --image=curlimages/curl --restart=Never -- "
        f"sh -c \"if curl -s -o /dev/null -f {url}; then echo OK; else echo FAIL; fi\""
    )
    if replace_existing:
        return f"kubectl delete pod {pod_name} -n {namespace} --ignore-not-found; {run_cmd}"
    return run_cmd


# =============================================================================
# DEPLOYMENT OPERATIONS
# =============================================================================

def create_deployment_apply(
    deployment_name: str,
    image: str,
    replicas: int = 1, 
    namespace: str = "default",
    container_port: int = 80,
    cpu_request: str = "100m", 
    memory_request: str = "128Mi",
    cpu_limit: str = "500m",        
    memory_limit: str = "512Mi",
    volume_mount_path: str = "",        
    pvc_claim_name: str = ""
) -> str:
    """
    Creates or updates a Kubernetes Deployment using 'kubectl apply --wait=false' 
    for any container image. The command returns immediately.
    
    Args:
        deployment_name: The unique name for the Deployment resource.
        image: The container image to use (e.g., 'nginx:latest', 'redis:6', 'my-app:v2').
        replicas: The desired number of Pod replicas for the Deployment.
        namespace: The namespace to deploy the resource into.
        container_port: The port the container inside the Pod is listening on.
        cpu_request: The guaranteed minimum CPU to allocate (e.g., '100m'). Essential for HPA.
        memory_request: The guaranteed minimum Memory to allocate (e.g., '128Mi').
        cpu_limit: The maximum CPU the container is allowed to burst to (e.g., '500m').
        memory_limit: The maximum Memory the container is allowed to use (e.g., '512Mi').
        volume_mount_path: Path inside the container where the volume should be mounted (e.g., '/var/lib/data'). Required if pvc_claim_name is set.
        pvc_claim_name: Name of an existing PersistentVolumeClaim to mount (for persistent storage).

    Returns:
        A string command for 'powershell -EncodedCommand'. This method is
        the most robust way to run multi-line scripts on Windows, as it
        bypasses all 'cmd.exe' parsing and quoting issues.
    """
    container_name = deployment_name 

    volume_spec = ""
    volume_mount_spec = ""
    
    if pvc_claim_name and volume_mount_path:
        volume_mount_spec = f"""
        volumeMounts:
        - name: app-storage
          mountPath: {volume_mount_path}
        """
        volume_spec = f"""
      volumes:
      - name: app-storage
        persistentVolumeClaim:
          claimName: {pvc_claim_name}
        """
        
    yaml_template = textwrap.dedent(f"""
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: {deployment_name}
          namespace: {namespace}
          labels:
            app: {deployment_name}
        spec:
          replicas: {replicas}
          selector:
            matchLabels:
              app: {deployment_name}
          template:
            metadata:
              labels:
                app: {deployment_name}
            spec:
              containers:
              - name: {container_name}
                image: {image}
                ports:
                - containerPort: {container_port}
                resources:
                  requests:
                    cpu: "{cpu_request}"
                    memory: "{memory_request}"
                  limits:
                    cpu: "{cpu_limit}"
                    memory: "{memory_limit}"
                {volume_mount_spec.strip()}
              {volume_spec.strip()}
    """)

    # PowerShell here-string wraps YAML for kubectl apply
    ps_script = f"""
$yaml = @'
{yaml_template.strip()}
'@
Write-Output $yaml | kubectl apply --wait=false -f -
"""

    # Encode as UTF-16LE Base64 for PowerShell -EncodedCommand (Windows-safe)
    encoded_script = base64.b64encode(
        ps_script.encode('utf-16-le')
    ).decode('ascii')

    return f"powershell -EncodedCommand {encoded_script}"


def delete_deployment_and_related(
    deployment_name: str, 
    namespace: str = "default",
    cleanup_related: bool = False
) -> str:
    """
    Deletes a Kubernetes Deployment and optionally cleans up related resources
    like the Service (svc) and Horizontal Pod Autoscaler (hpa).
    
    Args:
        deployment_name: The name of the Deployment to delete.
        namespace: The target namespace.
        cleanup_related: If True, deletes the Deployment, Service, and HPA 
                         if they share the same name.
    """
    if cleanup_related:
        resources_to_delete = "deployment,svc,hpa"
        return (
            f"kubectl delete {resources_to_delete} {deployment_name} "
            f"-n {namespace} --ignore-not-found"
        )
    return f"kubectl delete deployment {deployment_name} -n {namespace}"


def scale_deployment(
    deployment_name: str, 
    namespace: str = "default", 
    replicas: int = 1,
    force_manual_scale: bool = False
) -> str:
    """
    Manually scales a Deployment to a specified replica count.
    
    Args:
        deployment_name: The name of the Deployment to scale.
        namespace: The namespace where the Deployment resides.
        replicas: The desired number of Pod replicas.
        force_manual_scale: If True, this manual scale will override 
                            any active Horizontal Pod Autoscaler (HPA), 
                            which is typically NOT recommended.
    
    Notes:
        In Kubernetes, manually setting replicas when an HPA is active
        is usually pointless, as the HPA will immediately scale it back.
    """
    # Accepted for API completeness but doesn't change command (avoids lint warning)
    _ = force_manual_scale
    
    return f"kubectl scale deployment/{deployment_name} -n {namespace} --replicas={replicas}"


def set_deployment_resources(
    deployment_name: str, 
    namespace: str = "default", 
    container_name: str = "*",
    cpu_request: str = "", 
    memory_request: str = "", 
    cpu_limit: str = "", 
    memory_limit: str = ""
) -> str:
    """
    Sets CPU/Memory resource requests and limits for containers in a Deployment's Pod template.
    
    Args:
        deployment_name: The Deployment name.
        namespace: The target namespace.
        container_name: The container name to modify (use '*' for all containers).
        cpu_request, memory_request: Minimum guaranteed resources.
        cpu_limit, memory_limit: Maximum allowed resources.
    """
    requests_args = []
    if cpu_request:
        requests_args.append(f"cpu={cpu_request}")
    if memory_request:
        requests_args.append(f"memory={memory_request}")
    
    requests_str = f"--requests={','.join(requests_args)}" if requests_args else ""

    limits_args = []
    if cpu_limit:
        limits_args.append(f"cpu={cpu_limit}")
    if memory_limit:
        limits_args.append(f"memory={memory_limit}")

    limits_str = f"--limits={','.join(limits_args)}" if limits_args else ""
    container_str = f"-c {container_name}" 
    
    command_parts = [
        f"kubectl set resources deployment/{deployment_name}",
        f"-n {namespace}",
        container_str,
        requests_str,
        limits_str
    ]

    return " ".join(part for part in command_parts if part).strip()


def get_rollout_history(deployment_name: str, namespace: str = "default", watch_status: bool = False) -> str:
    """
    Gets the rollout history of a Deployment, or watches the status of the current rollout.
    
    Args:
        deployment_name: The name of the Deployment.
        namespace: The target namespace.
        watch_status: If True, uses 'kubectl rollout status -w' to monitor the current rollout.
    """
    if watch_status:
        return f"kubectl rollout status deployment/{deployment_name} -n {namespace} -w"
    return f"kubectl rollout history deployment/{deployment_name} -n {namespace}"


def undo_rollout(deployment_name: str, namespace: str = "default", revision: int = 0) -> str:
    """
    Reverts a Deployment to a previous revision.
    
    Args:
        deployment_name: The name of the Deployment.
        namespace: The target namespace.
        revision: The specific revision number to revert to (defaults to the immediately prior revision if 0).
    """
    revision_str = f"--to-revision={revision}" if revision > 0 else ""
    return f"kubectl rollout undo deployment/{deployment_name} -n {namespace} {revision_str}".strip()


# =============================================================================
# SERVICE OPERATIONS
# =============================================================================

def expose_deployment(
    deployment_name: str, 
    namespace: str = "default", 
    port: int = 80, 
    target_port: int = 80,
    service_type: str = "ClusterIP"
) -> str:
    """
    Creates a Service to expose a Deployment.
    
    Args:
        deployment_name: The name of the Deployment to expose.
        namespace: The target namespace.
        port: The Service port (what clients connect to).
        target_port: The container port (what the pod listens on).
        service_type: Type of Service ('ClusterIP', 'NodePort', or 'LoadBalancer').
    """
    valid_types = ["ClusterIP", "NodePort", "LoadBalancer"]
    if service_type not in valid_types:
        return f"# Error: Invalid service_type '{service_type}'. Must be one of: {', '.join(valid_types)}"

    target_port_str = f"--target-port={target_port}"
    return (
        f"kubectl expose deployment/{deployment_name} -n {namespace} "
        f"--port={port} {target_port_str} --type={service_type}"
    )


def get_service_endpoints(service_name: str, namespace: str = "default", structured_output: bool = False) -> str:
    """
    Retrieves Endpoints for a Service, useful to debug if traffic is routing to ready Pods.

    Args:
        service_name: The Service name.
        namespace: Namespace of the Service.
        structured_output: If True, return JSON (-o json); otherwise a human-readable wide view.
    """
    cmd = f"kubectl get endpoints {service_name} -n {namespace}"
    return f"{cmd} -o json" if structured_output else f"{cmd} -o wide"


# =============================================================================
# HPA (HORIZONTAL POD AUTOSCALER) OPERATIONS
# =============================================================================

def create_hpa(
    deployment_name: str, 
    namespace: str = "default", 
    min_replicas: int = 1, 
    max_replicas: int = 10, 
    cpu_utilization: int = 80,
    memory_utilization: int = 0
) -> str:
    """
    Creates a HorizontalPodAutoscaler (HPA). Note: Deployment must have resource requests set.
    
    Args:
        deployment_name: The name of the Deployment to autoscale.
        namespace: The target namespace.
        min_replicas: The minimum number of replicas.
        max_replicas: The maximum number of replicas.
        cpu_utilization: Target CPU utilization percentage (e.g., 80).
        memory_utilization: Target Memory utilization percentage (optional, e.g., 75).
    """
    # kubectl autoscale only supports one metric target
    if memory_utilization > 0 and cpu_utilization > 0:
        return "# Error: kubectl autoscale only supports one metric target. Please choose CPU or Memory."
        
    if memory_utilization > 0:
        metric_str = f"--memory-percent={memory_utilization}"
    else:
        metric_str = f"--cpu-percent={cpu_utilization}"
        
    return (
        f"kubectl autoscale deployment/{deployment_name} -n {namespace} "
        f"--min={min_replicas} --max={max_replicas} {metric_str}"
    )


def check_hpa_readiness(namespace: str = "default") -> str:
    """
    Checks if the cluster is ready for HPA in a given namespace.

    Verifies two things:
      1) Metrics API availability (via 'kubectl top nodes').
      2) Each Deployment in the namespace has CPU requests set on at least one container.

    Returns JSON via PowerShell with fields:
      {
        "namespace": "<ns>",
        "metricsServer": true|false,
        "deploymentsWithCpuRequests": <int>,
        "deploymentsMissingCpuRequests": <int>,
        "deployments": [ { name, hasCpuRequests } ]
      }

    On Windows, uses -EncodedCommand for reliability.
    """
    ps_script = textwrap.dedent("""
        $ErrorActionPreference = 'SilentlyContinue'
        $ns = '__NS__'

        # 1) Check metrics API availability
        $metricsOk = $false
        try {
            kubectl top nodes | Out-Null
            $metricsOk = $true
        } catch {
            $metricsOk = $false
        }

        # 2) Get deployments and check CPU requests
        $deployJson = kubectl get deploy -n $ns -o json | ConvertFrom-Json
        $items = @()
        if ($deployJson -and $deployJson.items) {
            foreach ($item in $deployJson.items) {
                $hasCpu = $false
                $containers = $item.spec.template.spec.containers
                foreach ($c in $containers) {
                    if ($c.resources -and $c.resources.requests -and $c.resources.requests.cpu) {
                        $hasCpu = $true
                    }
                }
                $items += [pscustomobject]@{ name = $item.metadata.name; hasCpuRequests = $hasCpu }
            }
        }

        $withCpu = ($items | Where-Object { $_.hasCpuRequests }).Count
        $withoutCpu = ($items | Where-Object { -not $_.hasCpuRequests }).Count

        $summary = [pscustomobject]@{
            namespace = $ns
            metricsServer = $metricsOk
            deploymentsWithCpuRequests = $withCpu
            deploymentsMissingCpuRequests = $withoutCpu
            deployments = $items
        }
        $summary | ConvertTo-Json -Depth 6
    """)
    ps_script = ps_script.replace('__NS__', namespace)
    encoded = base64.b64encode(ps_script.encode('utf-16-le')).decode('ascii')
    return f"powershell -EncodedCommand {encoded}"


# =============================================================================
# CONFIGMAP OPERATIONS
# =============================================================================

def create_configmap(configmap_name: str, namespace: str = "default", data: dict = None, from_file: str = "") -> str:
    """
    Creates or UPDATES a ConfigMap (idempotent operation) using the
    kubectl dry-run/apply pattern. This ensures the ConfigMap is created
    if it doesn't exist, or modified if it does.
    
    The command is encoded via Base64 for reliable execution on Windows.

    Args:
        configmap_name: The name for the new/existing ConfigMap.
        namespace: The target namespace.
        data: A dictionary of key/value pairs to include (e.g., {'key': 'value'}).
              This is used with --from-literal.
        from_file: Path to a local file/directory to use (uses --from-file).
                   If provided, 'data' is ignored.
    
    Returns:
        A string command for 'powershell -EncodedCommand' that handles the
        ConfigMap creation or update.
    """
    if from_file:
        base_cmd = f"kubectl create configmap {configmap_name} -n {namespace} --from-file='{from_file}'"
    elif data:
        from_literal = " ".join([f"--from-literal={key}='{value}'" for key, value in data.items()])
        base_cmd = f"kubectl create configmap {configmap_name} -n {namespace} {from_literal}"
    else:
        return f"# Error: Must provide 'data' (dict) or 'from_file' (str) to create/update configmap {configmap_name}"

    ps_script = textwrap.dedent(f"""
        {base_cmd} --dry-run=client -o yaml | kubectl apply -f -
    """)
    
    # Encode as UTF-16LE Base64 for PowerShell -EncodedCommand (Windows-safe)
    encoded_script = base64.b64encode(ps_script.encode('utf-16-le')).decode('ascii')
    return f"powershell -EncodedCommand {encoded_script}"


def delete_configmap(configmap_name: str, namespace: str = "default") -> str:
    """Deletes a ConfigMap by name. Safe to call even if it doesn't exist."""
    return f"kubectl delete configmap {configmap_name} -n {namespace} --ignore-not-found"


# =============================================================================
# CONTEXT AND NAMESPACE MANAGEMENT
# =============================================================================

def list_contexts() -> str:
    """Lists all kubeconfig contexts."""
    return "kubectl config get-contexts"


def get_current_context() -> str:
    """Gets the current kubeconfig context."""
    return "kubectl config current-context"


def use_context(context_name: str) -> str:
    """Switches the current kubeconfig context."""
    return f"kubectl config use-context {context_name}"


def list_namespaces() -> str:
    """Lists all namespaces in the cluster."""
    return "kubectl get ns"


# =============================================================================
# LOAD TESTING AND DIAGNOSTIC HELPERS
# =============================================================================

def start_http_load(
    pod_name: str = "curlgen",
    namespace: str = "default",
    url: str = "http://php-apache.default.svc.cluster.local/?load=2000",
    generator: str = "curl",
) -> str:
    """
    Starts a simple in-cluster HTTP load generator Pod to drive HPA demos.

    Args:
        pod_name: Name of the load generator pod to create.
        namespace: Namespace where the pod will run.
        url: Target URL to hit repeatedly. Defaults to php-apache service with extra CPU load.
        generator: 'curl' (default, uses curlimages/curl) or 'busybox' (uses busybox + wget).

    Returns:
        kubectl command string to create the pod.

    Notes:
        - Runs as a single-line command safe for Windows shells; the ';' are inside the container shell.
        - Use with 'get hpa -w' and 'get deploy -w' to observe scaling.
    """
    gen = (generator or "curl").lower()
    if gen == "busybox":
        return (
            f"kubectl run {pod_name} -n {namespace} --image=busybox --restart=Never -- "
            f"/bin/sh -c \"while true; do wget -q -O- {url} > /dev/null; done\""
        )
    return (
        f"kubectl run {pod_name} -n {namespace} --image=curlimages/curl --restart=Never -- "
        f"sh -c \"while true; do curl -s {url} > /dev/null; done\""
    )


def stop_http_load(pod_name: str = "curlgen", namespace: str = "default") -> str:
    """Stops and deletes the load generator pod created by start_http_load."""
    return f"kubectl delete pod {pod_name} -n {namespace} --ignore-not-found"


def start_http_load_stats(
    pod_name: str = "curlstats",
    namespace: str = "default",
    url: str = "http://php-apache.default.svc.cluster.local/?load=2000",
    generator: str = "curl",
    burst_per_second: int = 50,
) -> str:
    """
    Starts a stats pod that prints approximate hits per second to stdout.

    Args:
        pod_name: Pod name to create for stats.
        namespace: Namespace to run in.
        url: URL to hit repeatedly.
        generator: 'curl' (curlimages/curl) or 'busybox' (wget). Defaults to 'curl'.
        burst_per_second: Number of requests per loop iteration (~per second).

    Returns:
        A kubectl command that creates the stats pod. Use get_pod_logs(..., follow=True)
        to stream the printed lines.
    """
    gen = (generator or "curl").lower()
    b = max(1, int(burst_per_second))
    if gen == "busybox":
        return (
            f"kubectl run {pod_name} -n {namespace} --image=busybox --restart=Never -- "
            f"/bin/sh -c \"while true; do c=0; i=0; while [ $i -lt {b} ]; do wget -q -O- {url} > /dev/null && c=$((c+1)); i=$((i+1)); done; echo $(date) hits/s=$c; done\""
        )
    return (
        f"kubectl run {pod_name} -n {namespace} --image=curlimages/curl --restart=Never -- "
        f"sh -c \"while true; do c=0; i=0; while [ $i -lt {b} ]; do curl -s -o /dev/null {url} && c=$((c+1)); i=$((i+1)); done; echo $(date) hits/s=$c; done\""
    )


def stop_http_load_stats(pod_name: str = "curlstats", namespace: str = "default") -> str:
    """Stops and deletes the stats pod created by start_http_load_stats."""
    return f"kubectl delete pod {pod_name} -n {namespace} --ignore-not-found"


