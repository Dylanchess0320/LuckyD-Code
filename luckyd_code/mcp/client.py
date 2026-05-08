"""Basic MCP (Model Context Protocol) client.

Connects to MCP servers via stdio JSON-RPC and registers their tools.
MCP spec: https://modelcontextprotocol.io
"""

import json
import logging
import subprocess
import time
from typing import Any, Optional, cast

logger = logging.getLogger("luckyd_code.mcp")


class MCPServer:
    """A connected MCP server with health checks and reconnection."""

    def __init__(self, name: str, command: str, args: list[str] | None = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.process: Optional[subprocess.Popen] = None
        self.tools: list[dict] = []
        self._request_id = 0
        self._max_retries = 2

    def connect(self):
        """Start the MCP server process."""
        try:
            import sys
            # On Windows, use shell=True for .cmd/.bat files (like npx, which is npx.cmd)
            use_shell = sys.platform == "win32"
            self.process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=use_shell,
            )
            # Poll stderr in a non-blocking way — log any startup errors
            import threading
            def _log_stderr(proc):
                for line in iter(proc.stderr.readline, ""):
                    if line:
                        logger.debug("[mcp:%s] %s", self.name, line.rstrip())
            t = threading.Thread(target=_log_stderr, args=(self.process,), daemon=True)
            t.start()
        except Exception as e:
            return f"Failed to start MCP server '{self.name}': {e}"
        return None

    def _ensure_running(self) -> bool:
        """Check if the server is running and attempt reconnect if not."""
        if self.process and self.process.poll() is None:
            return True
        # Attempt reconnection
        for attempt in range(self._max_retries):
            logger.info("Reconnecting MCP server '%s' (attempt %d/%d)",
                        self.name, attempt + 1, self._max_retries)
            self.process = None
            error = self.connect()
            if error is None:
                # Rediscover tools
                self.tools = self.list_tools()
                return True
            time.sleep(1)
        return False

    def _send_request(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        """Send a JSON-RPC request and get response."""
        if not self._ensure_running():
            return {"error": "Server not running"}

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {},
        }

        try:
            if self.process is None or self.process.stdin is None or self.process.stdout is None:
                return {"error": "Server process not available"}
            self.process.stdin.write(json.dumps(request) + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
            if not line:
                return {"error": "Empty response from server"}
            result: dict[str, object] = json.loads(line)
            return result
        except Exception as e:
            logger.warning("MCP request error for '%s': %s", self.name, e)
            return {"error": str(e)}

    def list_tools(self) -> list[dict[str, object]]:
        """List available tools from this server."""
        response = self._send_request("tools/list")
        if "error" in response:
            return []
        result: dict[str, object] = cast(dict[str, object], response.get("result", {}))
        tools: list[dict[str, object]] = cast(list[dict[str, object]], result.get("tools", []))
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on this server."""
        response = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if "error" in response:
            return f"MCP error: {response['error']}"
        result: dict[str, object] = cast(dict[str, object], response.get("result", {}))
        content: list[dict[str, object]] = cast(list[dict[str, object]], result.get("content", []))
        return "\n".join(
            c.get("text", "") for c in content if c.get("type") == "text"
        ) or json.dumps(content)

    def close(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None


class MCPManager:
    """Manages MCP server connections."""

    def __init__(self):
        self.servers: list[MCPServer] = []

    def load_from_config(self, config: dict):
        """Load MCP servers from settings config."""
        servers_config = config.get("mcpServers", {})
        if not servers_config:
            servers_config = config.get("mcp_servers", {})

        for name, cfg in servers_config.items():
            server = MCPServer(
                name=name,
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
            )
            error = server.connect()
            if error:
                logger.warning("Failed to start MCP server '%s': %s", name, error)
                continue
            server.tools = server.list_tools()
            if server.tools:
                self.servers.append(server)
                logger.info("MCP server '%s' loaded with %d tools", name, len(server.tools))

    def get_all_tools(self) -> list[dict]:
        """Get all tools from all servers as OpenAI tool definitions."""
        tools = []
        for server in self.servers:
            for tool in server.tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": f"mcp_{tool['name']}",
                        "description": tool.get("description", f"MCP tool: {tool['name']}"),
                        "parameters": tool.get("inputSchema", {}),
                    },
                })
        return tools

    def execute(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool by its full name (mcp_<name>)."""
        name = tool_name[len("mcp_"):] if tool_name.startswith("mcp_") else tool_name
        for server in self.servers:
            for tool in server.tools:
                if tool["name"] == name:
                    return server.call_tool(name, arguments)
        return f"MCP tool '{name}' not found"

    def close_all(self):
        for server in self.servers:
            server.close()
