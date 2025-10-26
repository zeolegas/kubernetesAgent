"""
K8s Agent with Natural Language Interface

A conversational agent that translates natural language commands into Kubernetes operations.
Supports simple commands and multi-step diagnostic reasoning powered by GPT-4.
"""

# Standard library
import asyncio
import json
import logging
import os
import time
import uuid
from logging.handlers import RotatingFileHandler

# Third-party
import httpx
import openai
from dotenv import load_dotenv

# Load configuration
load_dotenv()


# ============================================================================
# CONFIGURATION
# ============================================================================

# API Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY
MCP_SERVER_URL = "http://localhost:8080/mcp"
SESSION_ID = "vscode-session"

# Diagnostic Mode Settings
MAX_DIAGNOSTIC_ITERATIONS = 5
MAX_LLM_CALLS = 20  # Safety limit to prevent runaway costs


# ============================================================================
# LOGGING SETUP
# ============================================================================
logs_dir = os.path.join(os.getcwd(), "logs")
os.makedirs(logs_dir, exist_ok=True)
agent_log_path = os.path.join(logs_dir, "agent.log")

agent_logger = logging.getLogger("k8s_agent")
agent_logger.setLevel(logging.INFO)
if not agent_logger.handlers:
    handler = RotatingFileHandler(agent_log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    class AgentJsonFormatter(logging.Formatter):
        def format(self, record):
            base = {
                "timestamp": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "logger": record.name,
            }
            try:
                msg = record.msg
                if isinstance(msg, dict):
                    base.update(msg)
                else:
                    base["message"] = str(msg)
            except Exception:
                base["message"] = record.getMessage()
            return json.dumps(base, ensure_ascii=False)
    handler.setFormatter(AgentJsonFormatter())
    agent_logger.addHandler(handler)

# --- Simple redaction helper ---
SENSITIVE_KEYS = {"openai_api_key", "api_key", "authorization", "token", "password"}

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

# Fetch available instructions from the MCP server
async def get_instructions_from_server() -> dict | None:
    instructions_url = f"{MCP_SERVER_URL}/instructions"
    print(f"🤖 Fetching available commands from {instructions_url}...")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(instructions_url)
            if response.status_code == 200:
                instructions = response.json()["instructions"]
                print(f"✅ Found {len(instructions)} available commands.")
                return instructions
            else:
                print(f"❌ Error fetching commands: {response.text}")
                return None
        except httpx.RequestError:
            print(f"❌ Could not connect to MCP Server at {instructions_url}.")
            print("Please make sure the server is running.")
            return None

# Generates the prompt template dynamically based on the available instructions
def get_prompt_template(instructions: list) -> str:
    # Use [INSTRUCTIONS] as a placeholder to avoid conflicts with JSON braces.
    template = """
You're a command parser for Kubernetes.

Given a user message, convert it to a JSON object with:
- `instruction`: one of [INSTRUCTIONS]
- `params`: a dictionary of parameters for the instruction.

Return **only the JSON** object.

General rules:
- If the user mentions "all namespaces", set `all_namespaces: true` and omit `namespace`.
- If the user doesn't specify a namespace, default to `"namespace": "default"`.
- Use concise parameter names per the instruction list; avoid adding unknown keys.
- Prefer exact resource types (pods, deployments, services, etc.).
- Do not include explanatory text — only return the JSON.

**Examples:**

User message: "list all pods in the default namespace"
```json
{
  "instruction": "get_resources",
  "params": {
    "resource_type": "pods",
    "namespace": "default"
  }
}
```

User message: "get the pod named 'my-pod-123'"
```json
{
  "instruction": "get_resources",
  "params": {
    "resource_type": "pod",
    "resource_name": "my-pod-123"
  }
}
```

User message: "describe the deployment 'my-deployment'"
```json
{
  "instruction": "describe_resource",
  "params": {
    "resource_type": "deployment",
    "resource_name": "my-deployment"
  }
}
```

User message: "[MESSAGE]"
"""
    return template.replace("[INSTRUCTIONS]", str(instructions))

# --- Helper: interactively fill missing required params (minimal, user-friendly) ---
def fill_missing_required_params(command_json: dict, instructions_schema: dict) -> tuple[dict, bool]:
    """Returns (updated_command_json, cancelled). Prompts user for missing required params.
    For 'namespace', suggests 'default' when missing.
    """
    try:
        inst = (command_json or {}).get("instruction")
        params = (command_json or {}).get("params") or {}
        tool = (instructions_schema or {}).get(inst) or {}
        args = (tool or {}).get("arguments") or {}
        missing = [k for k, v in args.items() if str(v).upper() == "REQUIRED" and k not in params]
        for key in missing:
            if key == "namespace":
                answer = input("No namespace provided. Press Enter to use 'default' or type a namespace: ").strip()
                params["namespace"] = answer if answer else "default"
            else:
                answer = input(f"Missing required parameter '{key}'. Please provide a value (or press Enter to cancel): ").strip()
                if not answer:
                    print("⚠️ Cancelled due to missing required parameter.")
                    return command_json, True
                params[key] = answer
        command_json["params"] = params
        return command_json, False
    except Exception:
        # On any error, don't block execution; proceed without changes
        return command_json, False

# Ask ChatGPT to parse natural language
async def parse_nl_to_command(message: str, prompt_template: str) -> dict | None:
    # Use .replace() for safety, avoiding conflicts with braces in the prompt.
    prompt = prompt_template.replace("[MESSAGE]", message)
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",  # or gpt-4-turbo / gpt-3.5-turbo
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=150,
    )
    raw_output = response.choices[0].message.content.strip()

    # Remove markdown code block backticks if present
    if raw_output.startswith("```") and raw_output.endswith("```"):
        lines = raw_output.splitlines()
        # A bit more robust way to remove ```json ... ```
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_output = "\n".join(lines).strip()

    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        print("⚠️ Failed to parse response from ChatGPT:")
        print(raw_output)
        return None

# Send parsed command to MCP Server
async def call_mcp_server(command_json: dict):
    execute_url = f"{MCP_SERVER_URL}/execute"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(execute_url, json=command_json, params={"session_id": SESSION_ID}, timeout=30.0)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ An unexpected error occurred with the MCP Server: {response.status_code} {response.text}")
                return None
        except httpx.RequestError:
            print(f"❌ Could not connect to MCP Server at {execute_url}.")
            return None


# --- Chain-of-thought diagnostic mode ---

def build_tool_schemas(instructions: dict) -> list:
    """Convert MCP server instructions into OpenAI function schemas."""
    tools = []
    for name, details in instructions.items():
        params_props = {}
        required_params = []
        args = details.get("arguments", {})
        for arg_name, arg_default in args.items():
            # Basic type inference (all strings for simplicity; OpenAI is flexible)
            params_props[arg_name] = {"type": "string", "description": f"Parameter {arg_name}"}
            if str(arg_default).upper() == "REQUIRED":
                required_params.append(arg_name)
        
        tool_schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": details.get("__doc__", "No description available."),
                "parameters": {
                    "type": "object",
                    "properties": params_props,
                    "required": required_params,
                },
            },
        }
        tools.append(tool_schema)
    return tools


async def run_diagnostic_loop(user_question: str, instructions: dict):
    """
    Multi-turn reasoning loop: LLM decides which tools to call, interprets results, and provides final answer.
    Safety: max 5 reasoning iterations, max 20 total LLM calls to prevent runaway loops and control costs.
    """
    print("\n🔍 Diagnostic mode activated. Analyzing your question...\n")
    
    tools = build_tool_schemas(instructions)
    request_id = str(uuid.uuid4())
    
    # System prompt for diagnostic mode
    system_prompt = """You are a Kubernetes diagnostic assistant.
The user will ask a question about their cluster (e.g., "are my pods healthy?" or "how do I deploy nginx with autoscale?").

Your job:
1. Decide which kubectl operations to run via the available functions.
2. Analyze the results.
3. Repeat as needed (up to a few iterations).
4. Provide a final, concise answer or step-by-step plan.

For diagnostic questions: call get_resources, describe_resource, get_events, etc. to gather data, then summarize health/issues.
For planning questions: outline the steps (e.g., "create deployment → expose service → set up HPA") and optionally call functions to check prerequisites.

Keep your final answer brief and actionable."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_question},
    ]
    
    max_iterations = 5
    max_llm_calls = 20  # Safety limit to prevent infinite loops and control costs
    iteration = 0
    llm_call_count = 0
    
    while iteration < max_iterations:
        iteration += 1
        llm_call_count += 1
        
        # Safety check: prevent runaway LLM calls
        if llm_call_count > max_llm_calls:
            print(f"\n⚠️ Reached maximum LLM call limit ({max_llm_calls}). Stopping diagnostic loop for safety.")
            print("The assistant may not have reached a final conclusion.")
            agent_logger.warning({
                "event": "diagnostic_llm_limit_reached",
                "request_id": request_id,
                "llm_calls": llm_call_count,
                "iterations": iteration,
            })
            return
        
        print(f"💭 Reasoning step {iteration}...")
        
        try:
            response = await openai.ChatCompletion.acreate(
                model="gpt-4o",
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0,
            )
        except Exception as e:
            print(f"❌ OpenAI API error: {e}")
            return
        
        message = response.choices[0].message
        messages.append(message.to_dict())
        
        # If no tool calls, the LLM has provided a final answer
        if not message.get("tool_calls"):
            final_answer = message.get("content", "")
            print("\n✅ Diagnostic complete.\n")
            print("📋 **Analysis & Recommendations:**")
            print(final_answer)
            agent_logger.info({
                "event": "diagnostic_complete",
                "request_id": request_id,
                "llm_calls": llm_call_count,
                "iterations": iteration,
            })
            return
        
        # Execute each tool call
        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            try:
                func_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                func_args = {}
            
            print(f"  🔧 Calling: {func_name} with {func_args}")
            
            # Call MCP server
            command_json = {
                "instruction": func_name,
                "params": func_args,
            }
            # Attach request_id
            command_json["params"]["request_id"] = request_id
            
            result = await call_mcp_server(command_json)
            
            # Format result for LLM (include summary if available, else stdout/stderr)
            if result:
                tool_result = {
                    "returncode": result.get("returncode", -1),
                }
                if result.get("summary"):
                    tool_result["summary"] = result["summary"]
                elif result.get("stdout"):
                    tool_result["stdout"] = result["stdout"][:2000]  # Truncate for token limits
                if result.get("stderr"):
                    tool_result["stderr"] = result["stderr"][:500]
            else:
                tool_result = {"error": "Failed to execute command"}
            
            # Append tool result to conversation
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(tool_result, ensure_ascii=False),
            })
    
    print("\n⚠️ Reached maximum reasoning iterations. Stopping diagnostic loop.")
    print("The assistant may not have reached a final conclusion.")
    agent_logger.warning({
        "event": "diagnostic_max_iterations",
        "request_id": request_id,
        "llm_calls": llm_call_count,
        "iterations": iteration,
    })


# Run agent loop
async def main():
    """Runs the main agent loop to process user commands."""
    
    # 1. Get instructions from server
    instructions = await get_instructions_from_server()
    if not instructions:
        print("👋 Exiting agent.")
        return
        
    prompt_template = get_prompt_template(instructions)

    print("\n🤖 K8s Agent is running. Type 'exit' or 'quit' to stop.")
    print("💡 Tip: Start your question with 'diagnose' or 'plan' for multi-step reasoning.\n")
    while True:
        try:
            user_input = input("\n🧠 Enter your K8s command (natural language): ")
            if user_input.lower() in ["exit", "quit"]:
                print("👋 Exiting agent.")
                break

            # --- Detect diagnostic mode keywords ---
            user_input_lower = user_input.lower()
            if user_input_lower.startswith("diagnose ") or user_input_lower.startswith("plan "):
                # Strip keyword and run diagnostic loop
                question = user_input.split(maxsplit=1)[1] if len(user_input.split(maxsplit=1)) > 1 else user_input
                await run_diagnostic_loop(question, instructions)
                continue

            # Log the raw user input
            request_id = str(uuid.uuid4())
            t0 = time.time()
            agent_logger.info(redact_dict({
                "event": "user_input",
                "session_id": SESSION_ID,
                "request_id": request_id,
                "input": user_input,
            }))

            # 2. Parse into instruction
            command_json = await parse_nl_to_command(user_input, prompt_template)
            if not command_json:
                print("❌ Failed to parse natural language.")
                continue

            # 2a. Fill missing required params interactively when needed
            command_json, cancelled = fill_missing_required_params(command_json, instructions)
            if cancelled:
                continue

            # Log parsed command
            parse_ms = int((time.time() - t0) * 1000)
            agent_logger.info(redact_dict({
                "event": "parsed_command",
                "session_id": SESSION_ID,
                "request_id": request_id,
                "parse_ms": parse_ms,
                "parsed": command_json,
            }))

            print(f"\n✅ Parsed command:\n{json.dumps(command_json, indent=2)}")

            # 3. Send to MCP and get detailed result
            # Attach request_id into params so server logs the same id
            try:
                params = command_json.get("params") or {}
                params["request_id"] = request_id
                command_json["params"] = params
            except Exception:
                pass

            http_t0 = time.time()
            result = await call_mcp_server(command_json)
            if result:
                # Log server result summary
                http_ms = int((time.time() - http_t0) * 1000)
                agent_logger.info(redact_dict({
                    "event": "mcp_result",
                    "session_id": SESSION_ID,
                    "request_id": request_id,
                    "http_ms": http_ms,
                    "instruction": command_json.get("instruction"),
                    "command": result.get("command"),
                    "returncode": result.get("returncode"),
                }))
                # Handle confirmation-required flow
                if isinstance(result, dict) and result.get("confirmation_required"):
                    print("\n⚠️  This action modifies cluster state and requires confirmation.")
                    print(f"  Request ID: {request_id}")
                    print(f"  Instruction: {command_json.get('instruction')}")
                    disp_cmd = result.get('display_command') or result.get('command')
                    print(f"  Command: {disp_cmd}")
                    msg = result.get("message")
                    if msg:
                        print(f"  Note: {msg}")
                    preview = result.get("preview") or {}
                    if preview.get("supported"):
                        print("\n� Dry-run preview:")
                        print(f"  Preview Command: {preview.get('command')}")
                        if preview.get("stdout"):
                            print(f"\n  Preview Stdout:\n{preview.get('stdout')}")
                        if preview.get("stderr"):
                            print(f"\n  Preview Stderr:\n{preview.get('stderr')}")
                    ans = input("\nProceed with execution? (y/N): ").strip().lower()
                    if ans in ("y", "yes"): 
                        # Resubmit with confirm=true
                        try:
                            params = command_json.get("params") or {}
                            params["confirm"] = True
                            command_json["params"] = params
                        except Exception:
                            pass
                        result = await call_mcp_server(command_json)
                    else:
                        print("🚫 Cancelled by user.")
                        continue

                print("\n� MCP Execution Details:")
                print(f"  Request ID: {request_id}")
                # If server provided a concise summary, print it first for a clean demo output
                if isinstance(result, dict) and result.get("summary"):
                    print("\n📄 Summary:")
                    print(result["summary"])  # Already human-friendly lines
                disp_cmd = result.get('display_command') or result.get('command')
                print(f"  Command: {disp_cmd}")
                print(f"  Return Code: {result.get('returncode')}")

                stdout_text = result.get('stdout')
                if stdout_text:
                    print(f"\n  Stdout:\n{stdout_text}")

                stderr_text = result.get('stderr')
                if stderr_text:
                    print(f"\n  Stderr:\n{stderr_text}")

                # Provide a clear success/failure message based on the return code
                if result.get('returncode') == 0:
                    print("\n✅ Command executed successfully.")
                else:
                    print("\n❌ Command finished with an error or warning.")

        except KeyboardInterrupt:
            print("\n👋 Exiting agent.")
            break

# Entry point
if __name__ == "__main__":
    asyncio.run(main())