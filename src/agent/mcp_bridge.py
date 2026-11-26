"""Zero-Dependency Stdio Model Context Protocol (MCP) Bridge for Eigenia TwinScan & OpenClaw.

Run directly via:
    ``TWINSCAN_API_URL=http://localhost:8000 python -m src.agent.mcp_bridge``

Speaks newline-delimited JSON-RPC 2.0 (MCP protocol ``2024-11-05``) over ``stdin``/``stdout``,
forwarding ``tools/list`` and ``tools/call`` to the Eigenia TwinScan backend with 3x retry
and strict ``sys.stderr`` diagnostic logging (never polluting ``stdout``).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, Optional

import httpx

from src.agent.robot_tools import get_mcp_tool_schemas

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "eigenia-twinscan-mcp", "version": "2.0.0"}


async def _http_json_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    json_body: Optional[Dict[str, Any]] = None,
    retries: int = 3,
) -> Dict[str, Any]:
    """Execute an HTTP JSON request with up to 3x retry and ``sys.stderr`` error logging."""
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            resp = await client.request(method, url, json=json_body)
            resp.raise_for_status()
            return dict(resp.json())
        except Exception as exc:
            last_exc = exc
            sys.stderr.write(f"[mcp_bridge] {method} {url} failed (attempt {attempt}/{retries}): {exc}\n")
            if attempt < retries:
                await asyncio.sleep(0.25 * attempt)
    assert last_exc is not None
    raise last_exc


async def handle_mcp_request(
    req: Dict[str, Any],
    client: Optional[httpx.AsyncClient] = None,
    api_url: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Handle a single JSON-RPC 2.0 MCP request dictionary.

    Args:
        req: Parsed JSON-RPC 2.0 request object.
        client: Optional reusable ``httpx.AsyncClient`` (useful for tests & persistent sessions).
        api_url: Base URL of the Eigenia TwinScan backend (defaults to ``TWINSCAN_API_URL``).

    Returns:
        JSON-RPC 2.0 response dictionary, or ``None`` for notifications (no ``id`` / ``notifications/*``).
    """
    method = str(req.get("method") or "").strip()
    req_id = req.get("id")
    params = req.get("params") if isinstance(req.get("params"), dict) else {}
    base_url = (api_url or os.getenv("TWINSCAN_API_URL", "http://localhost:8000")).rstrip("/")

    if method == "notifications/initialized" or (method.startswith("notifications/") and req_id is None):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": dict(SERVER_INFO),
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=20.0)
    try:
        if method == "tools/list":
            try:
                data = await _http_json_with_retry(active_client, "GET", f"{base_url}/api/agent/tools")
                tools = data.get("mcp_tools") or get_mcp_tool_schemas()
            except Exception as exc:
                sys.stderr.write(f"[mcp_bridge] Falling back to local MCP tool schemas: {exc}\n")
                tools = get_mcp_tool_schemas()
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

        if method == "tools/call":
            tool_name = str(params.get("name") or "").strip()
            tool_args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            robot_id = tool_args.pop("robot_id", None) if "robot_id" in tool_args else params.get("robot_id")
            if not tool_name:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Missing required parameter 'name' for tools/call."},
                }
            try:
                res = await _http_json_with_retry(
                    active_client,
                    "POST",
                    f"{base_url}/api/agent/execute",
                    json_body={"tool": tool_name, "arguments": tool_args, "robot_id": robot_id},
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}],
                        "isError": not bool(res.get("ok", False)),
                    },
                }
            except Exception as exc:
                err_payload = {"ok": False, "tool": tool_name, "summary": f"Backend call failed: {exc}", "data": {}}
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(err_payload, ensure_ascii=False)}],
                        "isError": True,
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    finally:
        if owns_client:
            await active_client.aclose()


async def run_stdio_bridge() -> None:
    """Run the persistent newline-delimited JSON-RPC 2.0 MCP stdio bridge loop."""
    api_url = os.getenv("TWINSCAN_API_URL", "http://localhost:8000").rstrip("/")
    sys.stderr.write(f"[mcp_bridge] Eigenia TwinScan MCP stdio server ready -> {api_url}\n")
    async with httpx.AsyncClient(timeout=20.0) as client:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                sys.stderr.write(f"[mcp_bridge] Invalid JSON input: {exc}\n")
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
                continue
            if not isinstance(req, dict):
                continue
            resp = await handle_mcp_request(req, client=client, api_url=api_url)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(run_stdio_bridge())
