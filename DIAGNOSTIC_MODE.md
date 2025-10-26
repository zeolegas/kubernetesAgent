# Chain-of-Thought Diagnostic Mode

## Overview
Your agent now supports **multi-step reasoning** for complex questions and planning scenarios.

## How It Works
1. **Keyword Detection**: Start your question with `diagnose` or `plan`
2. **Multi-Turn Loop**: The LLM:
   - Decides which kubectl operations to run
   - Calls your MCP server tools
   - Analyzes results
   - Repeats up to 5 iterations
   - Provides a synthesized answer or plan
3. **Safety Limits**: 
   - Max 5 reasoning iterations (steps)
   - Max 20 total LLM calls per diagnostic chain
   - Prevents infinite loops and controls costs

## Usage Examples

### Diagnostic Questions
```bash
diagnose are my pods healthy?
```
**What happens:**
- LLM calls `get_resources` for pods
- Analyzes pod status, restarts, ready counts
- Checks for recent events via `get_events`
- Summarizes health and flags issues

```bash
diagnose are there any bottlenecks in my cluster?
```
**What happens:**
- Calls `get_pod_resources` or `top_pods`
- Checks HPA status
- Reviews node resource usage
- Identifies CPU/memory pressure or scaling issues

### Planning Questions
```bash
plan how to deploy nginx with autoscale for 10 requests per second
```
**What happens:**
- LLM outlines steps:
  1. Create nginx deployment
  2. Expose as a service
  3. Set up HPA with CPU target
  4. Estimate resource requests for 10 rps
- Optionally checks if prerequisites exist (e.g., metrics-server)

```bash
plan how to expose my app externally with a LoadBalancer
```
**What happens:**
- Checks current services
- Recommends `expose_service` with type=LoadBalancer
- Explains DNS/IP assignment timeline

## Architecture

```
User Input
    ↓
Keyword Check (diagnose/plan)
    ↓
OpenAI Function Calling API
    ↓
Tool Schema (auto-generated from server instructions)
    ↓
Multi-Turn Loop (max 5 iterations)
    ├─ LLM decides next tool
    ├─ Call MCP Server
    ├─ Return result to LLM
    └─ Repeat or finalize
    ↓
Final Answer/Plan
```

## Technical Details

### Key Functions Added to `agent.py`
- `build_tool_schemas(instructions)`: Converts MCP instructions into OpenAI function schemas
- `run_diagnostic_loop(question, instructions)`: Multi-turn reasoning orchestrator

### Token Management
- Tool results truncated to 2000 chars (stdout) and 500 chars (stderr)
- Uses structured summaries when available from server
- Max 5 iterations prevents runaway costs

### Limitations
- No mutating operations during diagnostic (read-only by design)
- Max 5 reasoning iterations with 20 total LLM calls prevent runaway loops
- If LLM can't reach conclusion within limits, loop exits with warning
- Basic type inference (all params as strings; OpenAI adapts)

## Cost Considerations
- Diagnostic queries use more tokens than single-shot commands
- GPT-4o recommended for best reasoning quality
- Average diagnostic: 2-3 tool calls, ~3K-5K tokens total

## Examples in Action

### Example 1: Pod Health Check
```
🧠 Enter your K8s command (natural language): diagnose are my pods healthy?

🔍 Diagnostic mode activated. Analyzing your question...

💭 Reasoning step 1...
  🔧 Calling: get_resources with {'resource_type': 'pods', 'namespace': 'default', 'structured_output': 'true'}
💭 Reasoning step 2...
  🔧 Calling: get_events with {'namespace': 'default'}

✅ Diagnostic complete.

📋 **Analysis & Recommendations:**
Your pods are generally healthy:
- php-apache: Running, 1/1 ready, 0 restarts
- No recent error events

However, I notice:
- curltest and dnscheck pods are Completed (can be cleaned up with delete_completed_pods)

Recommendation: Run 'delete completed pods in default namespace' to remove test pods.
```

### Example 2: Deployment Planning
```
🧠 Enter your K8s command (natural language): plan deploy nginx with autoscale for 10 rps

🔍 Diagnostic mode activated. Analyzing your question...

💭 Reasoning step 1...

✅ Diagnostic complete.

📋 **Analysis & Recommendations:**
To deploy nginx with autoscaling for ~10 requests/second:

**Step 1: Create Deployment**
- Use `create_deployment` with:
  - image: nginx:latest
  - replicas: 2 (starting point)
  - cpu_request: 100m, memory_request: 128Mi
  - cpu_limit: 200m, memory_limit: 256Mi

**Step 2: Expose Service**
- Run `expose_service` with type=ClusterIP (or LoadBalancer for external access)
- target_port: 80

**Step 3: Set up HPA**
- Use `create_hpa` with:
  - min_replicas: 2
  - max_replicas: 10
  - cpu_utilization: 70

**Step 4: Test & Monitor**
- Use `start_http_load` to simulate traffic
- Monitor with `get_hpa_status` and `top_pods`

Estimated resource per replica for 5 rps: ~50m CPU, 64Mi memory.
```

## Tips
- For best results, ask specific questions
- Use "diagnose" for cluster state analysis
- Use "plan" for step-by-step guides
- Regular commands still work without keywords (single-shot mode)

## Future Enhancements
- Add memory/cost tracking per diagnostic session
- Support for multi-namespace analysis
- Integration with metrics-server for real-time data
- Execution mode: auto-run recommended steps with confirmation
