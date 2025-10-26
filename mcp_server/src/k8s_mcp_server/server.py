"""
MCP Server for Kubernetes Agent

A FastAPI-based server that exposes kubectl operations through an MCP (Model Context Protocol)
interface. The server dynamically discovers available operations from the prompts module,
validates all inputs for security, and provides optional confirmation gates for mutating operations.

Key Features:
- Dynamic operation discovery from prompts module
- Input validation and sanitization (prevents injection attacks)
- Confirmation gates for cluster-modifying operations
- Structured logging with sensitive data redaction
- Dry-run preview support for kubectl commands
- Context caching to reduce kubectl overhead

Security:
- Validates namespace names (DNS label format)
- Allowlists for resource types and service types
- Validates CPU/memory quantities with regex
- Detects and blocks shell control characters
- Requires explicit confirmation for mutations (configurable)
"""

import asyncio
import inspect
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from k8s_mcp_server import prompts


# ============================================================================
# WINDOWS COMPATIBILITY FIX
# ============================================================================
# Windows requires ProactorEventLoop for subprocess support
# This is set here as a fallback, but __main__.py sets it before uvicorn starts
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


# ============================================================================
# LOGGING SETUP
# ============================================================================

logs_dir = os.path.join(os.getcwd(), "logs")
os.makedirs(logs_dir, exist_ok=True)
server_log_path = os.path.join(logs_dir, "mcp_server.log")

logger = logging.getLogger("k8s_mcp_server")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = RotatingFileHandler(server_log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    # Simple JSON formatter
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            base = {
                "timestamp": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "logger": record.name,
            }
            # If the message is already a dict, merge it; otherwise include under 'message'
            try:
                msg = record.msg
                if isinstance(msg, dict):
                    base.update(msg)
                else:
                    base["message"] = str(msg)
            except Exception:
                base["message"] = record.getMessage()
            return json.dumps(base, ensure_ascii=False)

    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)


app = FastAPI(title="K8s MCP Server")

@app.on_event("startup")
async def startup_event():
    """Ensure Windows uses ProactorEventLoop for subprocess support"""
    if sys.platform == 'win32':
        loop = asyncio.get_event_loop()
        if not isinstance(loop, asyncio.ProactorEventLoop):
            logger.warning("Windows detected but not using ProactorEventLoop - subprocess calls may fail")
    logger.info("MCP Server startup complete")


# ============================================================================
# CONSTANTS & CONFIGURATION
# ============================================================================

# Dynamic operation discovery: automatically find all prompt functions
PROMPT_FUNCTIONS: Dict[str, Any] = {
    name: func
    for name, func in inspect.getmembers(prompts, inspect.isfunction)
    if not name.startswith("_")
}

# Security: require confirmation for cluster-modifying operations (env configurable)
REQUIRE_CONFIRM_FOR_MUTATIONS = str(os.getenv("REQUIRE_CONFIRM_FOR_MUTATIONS", "true")).lower() in {"1", "true", "yes"}

# Mutation detection heuristics - operations that modify cluster state
MUTATING_PREFIXES = (
    "create_", "delete_", "scale_", "set_", "expose_", "undo_", "start_", "stop_",
)
MUTATING_TOKENS = (
    " kubectl delete ", " kubectl apply ", " kubectl create ", " kubectl expose ",
    " kubectl autoscale ", " kubectl scale ", " kubectl set ", " kubectl rollout undo ",
    " kubectl run ",
)

# Sensitive data keys for log redaction
SENSITIVE_KEYS = {"OPENAI_API_KEY", "api_key", "token", "password", "secret", "credential"}

# Allowed resource types (security allowlist)
ALLOWED_RESOURCE_TYPES = {
    # Core resources
    "pod", "pods", "deployment", "deployments", "service", "services", "svc",
    "endpoint", "endpoints", "endpointslice", "endpointslices",
    "node", "nodes", "event", "events", "namespace", "namespaces", "ns",
    # Workloads
    "daemonset", "daemonsets", "statefulset", "statefulsets", "job", "jobs", "cronjob", "cronjobs",
    # Config & Storage
    "configmap", "configmaps", "cm", "secret", "secrets",
    "persistentvolumeclaim", "persistentvolumeclaims", "pvc",
    "persistentvolume", "persistentvolumes", "pv",
    # Networking
    "ingress", "ingresses",
    # Autoscaling
    "horizontalpodautoscaler", "hpa",
}

# Allowed service types (security allowlist)
ALLOWED_SERVICE_TYPES = {"ClusterIP", "NodePort", "LoadBalancer"}

# Resource quantity validation patterns
_CPU_QTY_RE = re.compile(r"^(?:\d+(?:\.\d+)?|\d+m)$")
_MEM_SUFFIXES = "Ki|Mi|Gi|Ti|Pi|Ei|K|M|G|T|P|E"
_MEM_QTY_RE = re.compile(rf"^\d+(?:\.\d+)?(?:({_MEM_SUFFIXES}))?$")


# ============================================================================
# DISPLAY HELPERS
# ============================================================================

def _display_command(cmd: str) -> str:
    """Return a human-friendly command for UI, hiding Base64 PowerShell encoding details"""
    try:
        if "powershell -EncodedCommand" in cmd:
            # We know our encoded scripts pipe YAML to kubectl apply -f -
            return "[PowerShell encoded script: kubectl apply -f - (YAML embedded)]"
        return cmd
    except Exception:
        return cmd

# --- Basic resource quantity validation (catch common mistakes early) ---
_CPU_QTY_RE = re.compile(r"^(?:\d+(?:\.\d+)?|\d+m)$")
_MEM_SUFFIXES = "Ki|Mi|Gi|Ti|Pi|Ei|K|M|G|T|P|E"
_MEM_QTY_RE = re.compile(rf"^\d+(?:\.\d+)?(?:({_MEM_SUFFIXES}))?$")


# ============================================================================
# VALIDATION HELPERS
# ============================================================================

def _is_valid_cpu_qty(val: str) -> bool:
    """Validate CPU quantity format (e.g., '0.5', '1', '100m')"""
    try:
        return bool(_CPU_QTY_RE.fullmatch(str(val)))
    except Exception:
        return False

def _is_valid_mem_qty(val: str) -> bool:
    """Validate memory quantity format (e.g., '128Mi', '1Gi')"""
    try:
        return bool(_MEM_QTY_RE.fullmatch(str(val)))
    except Exception:
        return False

def _suggest_mem_fix(val: str) -> Optional[str]:
    """Suggest fix for common memory quantity typos (e.g., '4i' → '4Mi')"""
    try:
        s = str(val)
        if re.fullmatch(r"^\d+i$", s):
            return s[:-1] + "Mi"
        return None
    except Exception:
        return None


# ============================================================================
# REQUEST MODELS
# ============================================================================

class MCPRequest(BaseModel):
    """MCP-style request with instruction name and optional parameters"""
    instruction: str
    params: Optional[Dict[str, Any]] = {}


# ============================================================================
# SECURITY & REDACTION
# ============================================================================

def redact_value(val: str) -> str:
    if not isinstance(val, str):
        return val
    if len(val) <= 8:
        return "***"
    return val[:4] + "***" + val[-4:]

def redact_dict(d: dict) -> dict:
    try:
        red = {}
        for k, v in d.items():
            lk = str(k).lower()
            if lk in SENSITIVE_KEYS:
                red[k] = redact_value(str(v))
            elif isinstance(v, dict):
                red[k] = redact_dict(v)
            elif isinstance(v, list):
                red[k] = [redact_dict(x) if isinstance(x, dict) else x for x in v]
            else:
                red[k] = v
        return red
    except Exception:
        return d


# ============================================================================
# KUBECTL CONTEXT (CACHED)
# ============================================================================

_ctx_cache = {"ts": 0, "data": {"current_context": None, "default_namespace": None}}

async def _get_kube_context_info() -> Dict[str, Any]:
    """Get current kubectl context with 60-second caching to reduce overhead"""
    now = time.time()
    if now - _ctx_cache["ts"] < 60 and _ctx_cache["data"]["current_context"] is not None:
        return _ctx_cache["data"]

    async def run(cmd: str) -> str:
        p = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await p.communicate()
        return out.decode(errors="replace").strip()

    try:
        current_context = await run("kubectl config current-context")
    except Exception:
        current_context = ""
    try:
        default_ns = await run("kubectl config view --minify --output 'jsonpath={..namespace}'")
    except Exception:
        default_ns = ""

    data = {"current_context": current_context or None, "default_namespace": default_ns or None}
    _ctx_cache["data"] = data
    _ctx_cache["ts"] = now
    return data


# ============================================================================
# API ENDPOINTS
# ============================================================================

# --- Validation Helper Functions ---

def _is_valid_k8s_name(name: str) -> bool:
    """Validate Kubernetes DNS label format (namespace, pod name, etc.)"""
    return bool(re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", name)) and len(name) <= 63


def _has_dangerous_chars(value: str) -> bool:
    """Check for shell control characters that could enable injection attacks"""
    return any(ch in value for ch in [';', '&', '|', '`', '\n', '\r'])


def _is_mutating(instruction_name: str, command: str) -> bool:
    """Determine if an instruction/command modifies cluster state"""
    # Check function attribute escape hatch
    try:
        fn = PROMPT_FUNCTIONS.get(instruction_name)
        if fn is not None and getattr(fn, "_mcp_mutating", False):
            return True
    except Exception:
        pass
    # Prefix-based heuristic
    if any(instruction_name.startswith(prefix) for prefix in MUTATING_PREFIXES):
        return True
    # Command substring heuristics
    if any(tok in command for tok in MUTATING_TOKENS):
        return True
    return False


async def _validate_request_params(req: MCPRequest, params: Dict[str, Any]) -> None:
    """Validate and sanitize all request parameters. Raises HTTPException on validation errors."""
    
    # Validate namespace
    if "namespace" in params:
        ns = params["namespace"]
        if isinstance(ns, str) and ns.lower() in {"all", "*"}:
            pass  # allowed special cases
        elif not (isinstance(ns, str) and _is_valid_k8s_name(ns)):
            raise HTTPException(status_code=400, detail=f"Invalid namespace: {ns}")
        if isinstance(ns, str) and _has_dangerous_chars(ns):
            raise HTTPException(status_code=400, detail="Invalid characters in namespace")

    # Validate resource_type
    if "resource_type" in params:
        rt = str(params["resource_type"]).lower()
        if rt not in ALLOWED_RESOURCE_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid resource_type: {params['resource_type']}")

    # Validate service_type
    if "service_type" in params:
        st = str(params["service_type"])
        if st not in ALLOWED_SERVICE_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid service_type: {st}")

    # Numeric validations
    def ensure_int_in(params_dict, key, min_v=None, max_v=None):
        if key in params_dict and params_dict[key] is not None:
            try:
                iv = int(params_dict[key])
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail=f"Parameter '{key}' must be an integer")
            if min_v is not None and iv < min_v:
                raise HTTPException(status_code=400, detail=f"Parameter '{key}' must be >= {min_v}")
            if max_v is not None and iv > max_v:
                raise HTTPException(status_code=400, detail=f"Parameter '{key}' must be <= {max_v}")
            params_dict[key] = iv

    for k in ["replicas", "min_replicas", "max_replicas", "port", "target_port", "container_port", "cpu_utilization", "memory_utilization"]:
        ensure_int_in(params, k, 0)

    # Validate name fields don't contain dangerous characters
    for k in ["pod_name", "deployment_name", "configmap_name", "resource_name", "pvc_claim_name"]:
        if k in params and isinstance(params[k], str) and _has_dangerous_chars(params[k]):
            raise HTTPException(status_code=400, detail=f"Invalid characters in {k}")

    # Validate label selector
    if "label_selector" in params and isinstance(params["label_selector"], str):
        if _has_dangerous_chars(params["label_selector"]):
            raise HTTPException(status_code=400, detail="Invalid characters in label_selector")

    # Validate CPU/Memory quantities
    for k in ("cpu_request", "cpu_limit"):
        if k in params and params[k] is not None:
            v = str(params[k])
            if not _is_valid_cpu_qty(v):
                raise HTTPException(status_code=400, detail=f"Invalid {k}: '{v}'. CPU must be a number (cores, e.g., 0.5 or 1) or millicores with 'm' (e.g., 100m).")
    
    for k in ("memory_request", "memory_limit"):
        if k in params and params[k] is not None:
            v = str(params[k])
            if not _is_valid_mem_qty(v):
                suggestion = _suggest_mem_fix(v)
                if suggestion:
                    raise HTTPException(status_code=400, detail=f"Invalid {k}: '{v}'. Did you mean '{suggestion}'?")
                raise HTTPException(status_code=400, detail=f"Invalid {k}: '{v}'. Memory must be a number optionally suffixed with Ki, Mi, Gi, Ti, Pi, Ei (or decimal K, M, G...). E.g., 128Mi, 1Gi.")


async def _execute_dry_run_preview(cmd: str, session_id: str, request_id: Optional[str], instruction: str) -> Dict[str, Any]:
    """Execute a dry-run preview of a command. Returns result dict."""
    preview_cmd = cmd
    can_execute_preview = True
    
    if "powershell -EncodedCommand" in cmd:
        can_execute_preview = False
    elif " kubectl apply " in cmd:
        preview_cmd = cmd.replace(" kubectl apply ", " kubectl apply --dry-run=client -o yaml ")
    elif " kubectl create " in cmd or " kubectl expose " in cmd or " kubectl autoscale " in cmd:
        preview_cmd = cmd + " --dry-run=client -o yaml"
    else:
        can_execute_preview = False

    if not can_execute_preview:
        return {
            "session_id": session_id,
            "request_id": request_id,
            "command": cmd,
            "stdout": "",
            "stderr": "Dry-run preview not supported for this command form; returning command only.",
            "returncode": 0,
            "preview_only": True,
        }

    # Execute preview command
    process = await asyncio.create_subprocess_shell(
        preview_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except asyncio.TimeoutError:
        process.kill()
        return {
            "session_id": session_id,
            "command": preview_cmd,
            "stdout": "",
            "stderr": "Dry-run preview timed out after 30s",
            "returncode": -1,
            "timed_out": True,
        }

    result = {
        "session_id": session_id,
        "request_id": request_id,
        "command": preview_cmd,
        "display_command": _display_command(preview_cmd),
        "stdout": stdout.decode(errors='replace').strip(),
        "stderr": stderr.decode(errors='replace').strip(),
        "returncode": process.returncode,
        "dry_run": True,
    }
    
    logger.info(redact_dict({
        "event": "execute_result",
        "session_id": session_id,
        "request_id": request_id,
        "instruction": instruction,
        "returncode": result["returncode"],
        "stdout_present": bool(result["stdout"]),
        "stderr_present": bool(result["stderr"]),
        "dry_run": True,
    }))
    
    return result


async def _execute_command(cmd: str, timeout_seconds: int) -> tuple:
    """Execute a shell command with timeout. Returns (stdout, stderr, returncode, timed_out, duration_ms)."""
    start_ts = time.time()
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()
        timed_out = True

    duration_ms = int((time.time() - start_ts) * 1000)
    return stdout, stderr, process.returncode, timed_out, duration_ms


def _parse_structured_output(result: Dict[str, Any], params: Dict[str, Any]) -> None:
    """Parse JSON output and add structured summary if requested. Modifies result dict in-place."""
    if not (bool(params.get("structured_output")) and result["returncode"] == 0 and result["stdout"]):
        return

    structured = None
    try:
        structured = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return

    if structured is None:
        return

    def parse_ts(ts: str) -> datetime:
        try:
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except Exception:
            return datetime.now(timezone.utc)

    def fmt_age(dt: datetime) -> str:
        delta = datetime.now(timezone.utc) - dt
        total = int(delta.total_seconds())
        days, rem = divmod(total, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        if days > 0:
            return f"{days}d{hours}h"
        if hours > 0:
            return f"{hours}h{minutes}m"
        if minutes > 0:
            return f"{minutes}m{seconds}s"
        return f"{seconds}s"

    def summarize_item(obj: dict) -> str:
        kind = obj.get("kind", "").lower()
        meta = obj.get("metadata", {})
        name = meta.get("name", "")
        ns = meta.get("namespace", "")
        created = meta.get("creationTimestamp")
        age = fmt_age(parse_ts(created)) if created else "-"

        if kind == "pod":
            status = obj.get("status", {})
            phase = status.get("phase", "")
            cs = status.get("containerStatuses", []) or []
            restarts = sum(int(c.get("restartCount", 0) or 0) for c in cs)
            ready_total = len(cs)
            ready_count = sum(1 for c in cs if c.get("ready"))
            pod_ip = status.get("podIP", "-")
            node = (obj.get("spec", {}) or {}).get("nodeName", "-")
            return f"pod/{name} ns={ns} ip={pod_ip} node={node} phase={phase} ready={ready_count}/{ready_total} restarts={restarts} age={age}"
        
        if kind == "deployment":
            spec = obj.get("spec", {})
            status = obj.get("status", {})
            replicas = spec.get("replicas", status.get("replicas", 0))
            ready = status.get("readyReplicas", 0)
            available = status.get("availableReplicas", 0)
            updated = status.get("updatedReplicas", 0)
            return f"deployment/{name} ns={ns} replicas={replicas} ready={ready} updated={updated} available={available} age={age}"
        
        if kind == "service":
            spec = obj.get("spec", {})
            stype = spec.get("type", "")
            ports = spec.get("ports", [])
            port_str = ",".join(str(p.get("port")) for p in ports)
            cluster_ips = []
            if "clusterIPs" in spec and isinstance(spec["clusterIPs"], list):
                cluster_ips = spec["clusterIPs"]
            elif spec.get("clusterIP") and spec.get("clusterIP") != "None":
                cluster_ips = [spec["clusterIP"]]
            external_ips = list(spec.get("externalIPs", []) or [])
            lb_ing = (obj.get("status", {}).get("loadBalancer", {}) or {}).get("ingress", []) or []
            for ing in lb_ing:
                if isinstance(ing, dict):
                    if ing.get("ip"):
                        external_ips.append(ing["ip"])
                    if ing.get("hostname"):
                        external_ips.append(ing["hostname"])
            cip = ",".join(cluster_ips) if cluster_ips else "-"
            eip = ",".join(external_ips) if external_ips else "-"
            return f"service/{name} ns={ns} type={stype} clusterIP={cip} external=[{eip}] ports=[{port_str}] age={age}"
        
        # default
        return f"{kind}/{name} ns={ns} age={age}"

    # Support both single object and list
    items = []
    if isinstance(structured, dict) and "items" in structured:
        items = structured.get("items", [])
    elif isinstance(structured, dict):
        items = [structured]
    elif isinstance(structured, list):
        items = structured

    lines = [summarize_item(o) for o in items if isinstance(o, dict)]
    result["structured"] = structured
    result["summary"] = "\n".join(lines)


@app.get("/mcp/instructions")
async def get_instructions():
    """Returns a list of available instructions with their docstrings and arguments"""
    
    instructions_with_details = {}
    
    for tool_name, tool_func in PROMPT_FUNCTIONS.items():
        
        # --- 1. Extract Docstring (Instruction) ---
        # Get the function's docstring, stripping whitespace
        docstring = inspect.getdoc(tool_func) or "No documentation provided."
        
        # --- 2. Extract Function Signature (Arguments and Defaults) ---
        signature = inspect.signature(tool_func)
        args_with_defaults = {}
        
        for name, parameter in signature.parameters.items():
            
            if parameter.default is not inspect.Parameter.empty:
                # Store default value (e.g., 10, 'default', or "None")
                default_value = str(parameter.default) if parameter.default is None else parameter.default
                args_with_defaults[name] = default_value
            else:
                # Indicate that the argument is REQUIRED
                args_with_defaults[name] = "REQUIRED"

        # --- 3. Assemble the Full Tool Definition ---
        instructions_with_details[tool_name] = {
            "__doc__": docstring,  # <-- NEW: The tool's primary instruction/description
            "arguments": args_with_defaults,
        }
        
    return {"instructions": instructions_with_details}


@app.post("/mcp/execute")
async def execute_mcp(req: MCPRequest, session_id: Optional[str] = Query(None)):
    """Execute an MCP instruction with validation, confirmation gates, and dry-run support"""
    
    # Basic validation
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    if req.instruction not in PROMPT_FUNCTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown instruction: {req.instruction}")

    # Extract and validate parameters
    params: Dict[str, Any] = dict(req.params or {})
    request_id = params.pop("request_id", None)
    timeout_param = params.pop("timeout", None)
    duration_param = params.pop("duration", None)
    dry_run_param = params.pop("dry_run", False)
    confirm_param = params.pop("confirm", False)

    # Validate all parameters
    await _validate_request_params(req, params)

    # Generate kubectl command
    try:
        cmd = PROMPT_FUNCTIONS[req.instruction](**params)
        display_cmd = _display_command(cmd)
        
        # Log the request
        ctx = await _get_kube_context_info()
        logger.info(redact_dict({
            "event": "execute_requested",
            "session_id": session_id,
            "request_id": request_id,
            "instruction": req.instruction,
            "params": params,
            "selected_function": PROMPT_FUNCTIONS[req.instruction].__name__,
            "generated_command": cmd,
            "context": ctx,
        }))
    except TypeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameters for instruction: {e}")

    # Check if command is mutating and requires confirmation
    is_mutating = _is_mutating(req.instruction, cmd)

    if REQUIRE_CONFIRM_FOR_MUTATIONS and is_mutating and not dry_run_param and not bool(confirm_param):
        # Generate best-effort preview for user
        preview = await _generate_confirmation_preview(cmd)
        
        logger.info(redact_dict({
            "event": "confirmation_required",
            "session_id": session_id,
            "request_id": request_id,
            "instruction": req.instruction,
            "mutating": True,
            "preview_supported": preview.get("supported", False),
        }))

        return {
            "session_id": session_id,
            "request_id": request_id,
            "instruction": req.instruction,
            "command": cmd,
            "display_command": display_cmd,
            "confirmation_required": True,
            "message": "This action modifies cluster state. Resubmit with confirm=true to proceed, or dry_run=true to preview only.",
            "preview": preview,
            "returncode": 0,
        }

    # Handle dry-run preview request
    if dry_run_param:
        return await _execute_dry_run_preview(cmd, session_id, request_id, req.instruction)

    # Determine timeout strategy
    timeout_seconds = _calculate_timeout(cmd, timeout_param, duration_param)

    # Execute the command
    stdout, stderr, returncode, timed_out, duration_ms = await _execute_command(cmd, timeout_seconds)

    # Build result
    result = {
        "session_id": session_id,
        "request_id": request_id,
        "command": cmd,
        "display_command": display_cmd,
        "stdout": stdout.decode(errors='replace').strip(),
        "stderr": stderr.decode(errors='replace').strip(),
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_ms": duration_ms,
    }

    # Parse structured output if requested
    _parse_structured_output(result, params)

    # Attach context info
    try:
        result["context"] = await _get_kube_context_info()
    except Exception:
        pass

    # Log execution result
    logger.info(redact_dict({
        "event": "execute_result",
        "session_id": session_id,
        "request_id": request_id,
        "instruction": req.instruction,
        "returncode": result["returncode"],
        "stdout_present": bool(result["stdout"]),
        "stderr_present": bool(result["stderr"]),
        "timed_out": timed_out,
        "duration_ms": result["duration_ms"],
        "context": result.get("context"),
    }))

    return result


async def _generate_confirmation_preview(cmd: str) -> Dict[str, Any]:
    """Generate a best-effort preview for confirmation prompts"""
    preview_cmd = cmd
    preview = {
        "supported": False,
        "command": cmd,
        "stdout": "",
        "stderr": "",
        "returncode": 0,
    }
    
    if "powershell -EncodedCommand" in cmd:
        return preview
    
    if " kubectl apply " in cmd:
        preview_cmd = cmd.replace(" kubectl apply ", " kubectl apply --dry-run=client -o yaml ")
    elif (" kubectl create " in cmd) or (" kubectl expose " in cmd) or (" kubectl autoscale " in cmd):
        preview_cmd = cmd + " --dry-run=client -o yaml"
    else:
        return preview

    process = await asyncio.create_subprocess_shell(
        preview_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        pstdout, pstderr = await asyncio.wait_for(process.communicate(), timeout=30)
        preview.update({
            "supported": True,
            "command": preview_cmd,
            "stdout": pstdout.decode(errors='replace').strip(),
            "stderr": pstderr.decode(errors='replace').strip(),
            "returncode": process.returncode,
            "dry_run": True,
        })
    except asyncio.TimeoutError:
        preview.update({
            "supported": True,
            "command": preview_cmd,
            "stdout": "",
            "stderr": "Dry-run preview timed out after 30s",
            "returncode": -1,
            "dry_run": True,
        })
    
    return preview


def _calculate_timeout(cmd: str, timeout_param: Optional[Any], duration_param: Optional[Any]) -> int:
    """Calculate appropriate timeout for command execution"""
    DEFAULT_TIMEOUT_SECONDS = 60
    
    try:
        timeout_seconds = int(timeout_param) if timeout_param is not None else DEFAULT_TIMEOUT_SECONDS
    except (ValueError, TypeError):
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
    
    # For streaming commands (follow/watch), cap at reasonable duration
    streaming_hint = (" -f" in cmd) or (" -w" in cmd)
    if streaming_hint:
        try:
            duration_seconds = int(duration_param) if duration_param is not None else 15
        except (ValueError, TypeError):
            duration_seconds = 15
        timeout_seconds = min(timeout_seconds, max(1, duration_seconds))
    
    return timeout_seconds


@app.get("/")
def root():
    return {"message": "K8s MCP Server is running"}