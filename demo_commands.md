# 🎯 Demo Commands for K8s Agent

## 📋 **VIEWING RESOURCES**
- `show me all pods`
- `list all deployments`
- `show me all services`
- `get pod logs for web-server`
- `describe the web-server pod`

## ➕ **CREATING RESOURCES**

### Create Simple Pods
- `create an nginx pod called web-server`
- `create a busybox pod named debug-pod`
- `create an nginx pod called frontend`

### Create Deployments (Multiple Pods)
- `create a deployment called my-app with nginx`
- `create a deployment called backend with nginx and 5 replicas`

### Create Services (Load Balancers)
- `expose the my-app deployment as a service`
- `expose the backend deployment on port 8080`

## ➖ **DELETING RESOURCES**
- `delete the pod named web-server`
- `delete the pod named debug-pod`
- `delete the deployment called my-app`
- `delete the deployment called backend`

## 🎮 **DEMO WORKFLOW**

1. **Start with viewing current state:**
   ```
   show me all pods
   ```

2. **Create some demo resources:**
   ```
   create an nginx pod called web-server
   create a deployment called my-app with nginx
   ```

3. **Check what was created:**
   ```
   show me all pods
   show me all deployments
   ```

4. **Expose deployment as a service:**
   ```
   expose the my-app deployment as a service
   show me all services
   ```

5. **Clean up:**
   ```
   delete the pod named web-server
   delete the deployment called my-app
   ```

6. **Verify cleanup:**
   ```
   show me all pods
   show me all deployments
   ```

## 🚀 **How to Start**

1. **Start MCP Server (Terminal 1):**
   ```powershell
   cd mcp_server
   python -m k8s_mcp_server
   ```

2. **Start Agent (Terminal 2):**
   ```powershell
   cd agent
   .\.venv\Scripts\Activate.ps1
   python agent.py
   ```

3. **Try the demo commands above!**