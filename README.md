# Kubernetes LLM Agent

A natural language interface to Kubernetes that abstracts kubectl complexity behind an LLM-powered agent. Ask questions in plain English and let the agent handle the kubectl operations.

## Features

- 🤖 **Natural Language Interface**: Interact with your cluster using conversational commands
- 🧠 **Chain-of-Thought Diagnostics**: Advanced multi-step reasoning for complex questions like "are my pods healthy?" or "plan how to deploy nginx with autoscale"
- 🔒 **Safety First**: Mutation confirmations with dry-run previews, input validation, structured logging
- 📊 **Rich Operations**: Deployments, services, HPA, scaling, rollouts, logs, events, and more
- 🎯 **Production-Ready Patterns**: Request tracing, timeout controls, redaction of sensitive data

## Architecture

```
┌─────────────────┐
│   User Input    │  "diagnose are my pods healthy?"
│  (Natural Lang) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Python Agent   │  Parses intent via OpenAI GPT-4
│   (agent.py)    │  Routes to diagnostic or single-shot mode
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  MCP Server     │  Validates, builds kubectl commands
│  (FastAPI)      │  Enforces safety gates
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    kubectl      │  Executes against local cluster
│   (Minikube)    │
└─────────────────┘
```

## Quick Start

### Prerequisites

- **Python 3.12+**
- **kubectl** installed and configured
- **Minikube** or access to a Kubernetes cluster
- **OpenAI API key**

### Installation

1. **Clone and setup**:
   ```bash
   git clone <your-repo-url>
   cd k8s-agent-mcp-project
   ```

2. **Configure environment**:
   ```bash
   # Agent setup
   cd agent
   cp .env.example .env
   # Edit .env and add your OPENAI_API_KEY
   
   # Server setup
   cd ../mcp_server
   cp .env.example .env
   ```

3. **Install dependencies**:
   
   **For the server** (using Poetry):
   ```bash
   cd mcp_server
   pip install poetry  # if not already installed
   poetry install
   ```
   
   **For the agent**:
   ```bash
   cd agent
   python -m venv .venv
   
   # On Windows:
   .\.venv\Scripts\Activate.ps1
   
   # On Mac/Linux:
   source .venv/bin/activate
   
   pip install -r requirements.txt
   ```

4. **Start Minikube** (if using local cluster):
   ```bash
   minikube start
   ```

5. **Run the server** (in one terminal):
   ```bash
   cd mcp_server
   # On Windows:
   $env:PYTHONPATH="src"; poetry run uvicorn k8s_mcp_server.server:app --host 0.0.0.0 --port 8080 --reload
   
   # On Mac/Linux:
   PYTHONPATH=src poetry run uvicorn k8s_mcp_server.server:app --host 0.0.0.0 --port 8080 --reload
   ```

6. **Run the agent** (in another terminal):
   ```bash
   cd agent
   # Activate your venv first, then:
   python agent.py
   ```

## Usage Examples

### Single-Shot Commands
```
🧠 Enter your K8s command: get all pods in default namespace

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

### Chain-of-Thought Diagnostics
```
🧠 Enter your K8s command: diagnose are my pods healthy?

🔍 Diagnostic mode activated. Analyzing your question...

💭 Reasoning step 1...
  🔧 Calling: get_resources with {'resource_type': 'pods', 'namespace': 'default'}
💭 Reasoning step 2...
  🔧 Calling: get_events with {'namespace': 'default'}

✅ Diagnostic complete.

📋 Analysis & Recommendations:
Your pods are generally healthy. All running pods show 1/1 ready...
```

### Planning Mode
```
🧠 Enter your K8s command: plan deploy nginx with autoscale for 10 rps

🔍 Diagnostic mode activated...

✅ Diagnostic complete.

📋 Analysis & Recommendations:
To deploy nginx with autoscaling for ~10 requests/second:

Step 1: Create Deployment
- Use create_deployment with: image=nginx:latest, replicas=2...
```

## Platform Notes

**Developed and tested on**: Windows 11 with PowerShell

**Platform compatibility**:
- ✅ **Windows**: Fully tested and working
- ⚠️ **Mac/Linux**: Core operations (get, describe, delete, scale) work cross-platform
- ⚠️ **Known limitation**: Advanced multi-line YAML apply operations use PowerShell's `-EncodedCommand` for proper string handling on Windows

**For Mac/Linux users**: If you encounter issues with deployment creation (which uses YAML apply), you may need to modify `mcp_server/src/k8s_mcp_server/prompts.py` to use bash heredoc syntax instead of PowerShell encoding. Basic kubectl operations will work without modification.

## Advanced Features

### Mutation Safety
The server requires confirmation for any mutating operation (create, delete, scale):
```
⚠️ This action modifies cluster state and requires confirmation.
Command: kubectl apply -f - (YAML embedded)

Dry-run preview:
[shows what will be created]

Proceed with execution? (y/N):
```

### Structured Logging
All operations are logged with request tracing:
```json
{
  "timestamp": "2025-10-26T10:30:00",
  "event": "execute_result",
  "request_id": "abc-123",
  "instruction": "get_resources",
  "returncode": 0
}
```

### Input Validation
- Namespace validation (DNS-label compliant)
- Resource type allowlists
- Label selector safety checks
- CPU/memory quantity validation

## Configuration

### Environment Variables

**Agent** (`agent/.env`):
- `OPENAI_API_KEY`: Your OpenAI API key (required)
- `MCP_SERVER_URL`: Server endpoint (default: `http://localhost:8080/mcp`)
- `LOG_LEVEL`: Logging verbosity (default: `INFO`)

**Server** (`mcp_server/.env`):
- `REQUIRE_CONFIRM_FOR_MUTATIONS`: Enable confirmation gates (default: `true`)
- `LOG_LEVEL`: Logging verbosity (default: `INFO`)

## Testing

**Manual testing**:
```bash
# Test server endpoint
curl -X POST "http://localhost:8080/mcp/execute?session_id=test" \
  -H "Content-Type: application/json" \
  -d '{
    "instruction": "get_resources",
    "params": {
      "resource_type": "pods",
      "namespace": "default"
    }
  }'
```

## Troubleshooting

### "Could not connect to MCP Server"
- Ensure the server is running on port 8080
- Check that `MCP_SERVER_URL` in `agent/.env` matches the server address

### "OpenAI API error"
- Verify your `OPENAI_API_KEY` in `agent/.env` is valid
- Check your OpenAI account has available credits

### kubectl commands fail
- Ensure `kubectl` is installed: `kubectl version`
- Verify cluster access: `kubectl cluster-info`
- Check current context: `kubectl config current-context`

## Future Improvements

- [ ] Docker containerization for easy deployment
- [ ] Comprehensive test suite (pytest)
- [ ] Full cross-platform support (bash/zsh for Mac/Linux)
- [ ] CI/CD pipeline
- [ ] Multi-cluster context switching
- [ ] WebUI for non-technical users

## Contributing

Contributions welcome! Areas of interest:
- Mac/Linux compatibility fixes
- Test coverage
- Additional kubectl operations
- Performance optimizations

## License

See [LICENSE](LICENSE) file for details.