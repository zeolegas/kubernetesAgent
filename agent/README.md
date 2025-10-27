# K8s Agent - Natural Language Interface

A GPT-4 powered conversational agent that translates natural language into Kubernetes operations.

## Code Quality: 8.0/10 ✅

**Recent Improvements:**
- Comprehensive module docstring
- Organized configuration section
- Clear code sections with headers
- Security-focused with data redaction

## Features

- 🤖 **Natural Language Processing**: Powered by OpenAI GPT-4
- 🧠 **Chain-of-Thought Diagnostics**: Multi-step reasoning for complex questions
- 🔒 **Security**: Sensitive data redaction in logs
- 📊 **Structured Logging**: JSON logs with request tracing
- ⚡ **Two Modes**:
  - **Single-Shot**: Quick kubectl operations (`get pods`, `scale deployment`)
  - **Diagnostic**: Complex multi-step analysis (`diagnose: are my pods healthy?`)

## Prerequisites

- **Python 3.12+**
- **OpenAI API key** (GPT-4 access)
- **MCP Server running** (see `../mcp_server/README.md`)

## Quick Start

### 1. Setup Virtual Environment

```powershell
# Windows
cd agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Mac/Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### 4. Run Agent

```bash
python agent.py
```

## Usage Examples

### Single-Shot Commands

```
🧠 Enter your K8s command: get all pods

✅ Parsed command:
{
  "instruction": "get_resources",
  "params": {
    "resource_type": "pods",
    "namespace": "default"
  }
}

📦 MCP Output:
NAME                    READY   STATUS    RESTARTS   AGE
php-apache-xxx          1/1     Running   0          2d
```

### Diagnostic Mode

Prefix your question with `diagnose` or `plan`:

```
🧠 Enter your K8s command: diagnose are my pods healthy?

🔍 Diagnostic mode activated. Analyzing your question...

💭 Reasoning step 1...
  🔧 Calling: get_resources with {'resource_type': 'pods', 'namespace': 'default'}
💭 Reasoning step 2...
  🔧 Calling: get_events with {'namespace': 'default'}

✅ Diagnostic complete.

📋 Analysis & Recommendations:
All pods are running successfully. No recent errors or warnings detected...
```

### Planning Mode

```
🧠 Enter your K8s command: plan how to deploy nginx with autoscaling

🔍 Diagnostic mode activated...

✅ Diagnostic complete.

📋 Analysis & Recommendations:
Here's a step-by-step plan to deploy nginx with horizontal autoscaling:

1. Create Deployment with resource requests (required for HPA)
2. Expose the deployment as a Service
3. Create HorizontalPodAutoscaler targeting CPU utilization
4. Generate load to test autoscaling...
```

## Configuration

### Environment Variables (`agent/.env`)

```bash
OPENAI_API_KEY=sk-...                          # Required: Your OpenAI API key
MCP_SERVER_URL=http://localhost:8080/mcp      # MCP server endpoint
```

### Agent Settings (in `agent.py`)

- `MAX_DIAGNOSTIC_ITERATIONS = 5` - Maximum reasoning steps
- `MAX_LLM_CALLS = 20` - Safety limit to prevent runaway costs
- `SESSION_ID` - Unique identifier for request tracing

## Architecture

The agent uses a two-mode architecture:

1. **Single-Shot Mode** (default):
   - User input → GPT-4 parses → Single MCP call → Display result

2. **Diagnostic Mode** (keyword: `diagnose` or `plan`):
   - User question → GPT-4 reasons → Multiple tool calls → Synthesize answer
   - Uses OpenAI function calling to invoke kubectl operations iteratively
   - Safety limits prevent runaway loops

## Logging

Logs are written to `logs/agent.log` in JSON format:

```json
{
  "timestamp": "2025-10-27T10:30:00",
  "event": "user_input",
  "session_id": "vscode-session",
  "request_id": "abc-123",
  "input": "get pods"
}
```

Sensitive data (API keys, tokens) is automatically redacted.

## Troubleshooting

### "Could not connect to MCP Server"
- Ensure MCP server is running: `curl http://localhost:8080`
- Check `MCP_SERVER_URL` in `.env` matches server address

### "OpenAI API error"
- Verify `OPENAI_API_KEY` in `.env` is valid
- Check OpenAI account has available credits
- Ensure no extra spaces/quotes in `.env` file

### Agent freezes on startup
- Server must be running BEFORE starting agent
- Agent connects to server on startup to fetch available commands
- Check server is responding: `curl http://localhost:8080/mcp/instructions`

## Code Structure

```python
agent.py (558 lines)
├── Configuration (API keys, settings)
├── Logging Setup (JSON formatter, redaction)
├── get_instructions_from_server() - Fetch available commands
├── parse_nl_to_command() - GPT-4 parsing
├── call_mcp_server() - Execute kubectl operations
├── run_diagnostic_loop() - Multi-step reasoning
└── main() - Interactive loop
```

## Dependencies

```
openai==0.28       # GPT-4 API
httpx              # Async HTTP client
python-dotenv      # Environment management
```

## Future Improvements

- [ ] Async input handling (`asyncio.to_thread`)
- [ ] Extract main() function complexity (currently 71)
- [ ] Add agent-side caching
- [ ] Support for multiple concurrent sessions
- [ ] WebSocket streaming for real-time updates
