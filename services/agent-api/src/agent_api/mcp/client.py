from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import Protocol
from collections.abc import Callable

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr


REQUIRED_TOOLS = {
    "search_brand_documents",
    "get_product_facts",
    "get_brand_guidelines",
    "get_channel_spec",
    "validate_marketing_claims",
    "validate_channel_content",
    "save_content_version",
    "export_content_package",
    "create_publish_preview",
}

CAPABILITIES = {
    **{name: "read" for name in REQUIRED_TOOLS - {"save_content_version", "export_content_package", "create_publish_preview"}},
    "save_content_version": "write",
    "export_content_package": "high_risk",
    "create_publish_preview": "high_risk",
}


class MCPExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ToolCallRecorder(Protocol):
    async def record_tool_call(self, payload: dict[str, object]) -> None: ...


class RealMCPClient:
    def __init__(
        self,
        url: str,
        recorder: ToolCallRecorder,
        *,
        workspace_id: str,
        task_id: str,
        workflow_node: str,
        actor_id: str = "system",
        service_token: SecretStr | None = None,
        timeout_seconds: float = 15,
        max_attempts: int = 2,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._url = url.strip()
        self._recorder = recorder
        self._workspace_id = workspace_id
        self._task_id = task_id
        self._workflow_node = workflow_node
        self._actor_id = actor_id
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._http_client_factory = http_client_factory

    def for_task(self, *, workspace_id: str, task_id: str, workflow_node: str) -> "RealMCPClient":
        return RealMCPClient(
            self._url,
            self._recorder,
            workspace_id=workspace_id,
            task_id=task_id,
            workflow_node=workflow_node,
            actor_id=self._actor_id,
            service_token=self._service_token,
            timeout_seconds=self._timeout_seconds,
            max_attempts=self._max_attempts,
            http_client_factory=self._http_client_factory,
        )

    def for_actor(self, *, workspace_id: str, task_id: str, workflow_node: str, actor_id: str) -> "RealMCPClient":
        return RealMCPClient(
            self._url,
            self._recorder,
            workspace_id=workspace_id,
            task_id=task_id,
            workflow_node=workflow_node,
            actor_id=actor_id,
            service_token=self._service_token,
            timeout_seconds=self._timeout_seconds,
            max_attempts=self._max_attempts,
            http_client_factory=self._http_client_factory,
        )

    async def _session(self):
        headers = {}
        if self._service_token is not None:
            headers["Authorization"] = f"Bearer {self._service_token.get_secret_value().strip()}"
        headers["X-BrandFlow-Workspace"] = self._workspace_id
        headers["X-BrandFlow-Task"] = self._task_id
        headers["X-BrandFlow-Actor"] = self._actor_id
        http_client = self._http_client_factory() if self._http_client_factory else httpx.AsyncClient(headers=headers, timeout=self._timeout_seconds)
        transport = streamable_http_client(self._url, http_client=http_client)
        return http_client, transport

    async def discover(self) -> set[str]:
        http_client, transport = await self._session()
        try:
            async with transport as (read_stream, write_stream, _session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
        except Exception as error:
            raise MCPExecutionError("MCP_UNAVAILABLE", f"Brand tools MCP discovery failed: {error}", retryable=True) from error
        finally:
            await http_client.aclose()
        missing = REQUIRED_TOOLS - names
        if missing:
            raise MCPExecutionError("MCP_CAPABILITY_MISSING", "Required BrandFlow MCP capabilities are missing.", retryable=False)
        return names

    def _sanitized_input(self, arguments: dict[str, object]) -> dict[str, object]:
        allowed = {"workspace_id", "task_id", "product_id", "brand_id", "channel", "content_type", "decision_id"}
        sanitized = {key: value for key, value in arguments.items() if key in allowed}
        if "query" in arguments:
            sanitized["query_length"] = len(str(arguments["query"]))
        if "content" in arguments:
            sanitized["content_length"] = len(str(arguments["content"]))
        if "claims" in arguments:
            sanitized["claim_count"] = len(arguments["claims"]) if isinstance(arguments["claims"], list) else 0
        return sanitized

    async def call(self, tool_name: str, arguments: dict[str, object]) -> dict:
        if tool_name not in REQUIRED_TOOLS:
            raise MCPExecutionError("MCP_TOOL_NOT_ALLOWED", "Tool is not in the approved capability registry.", retryable=False)
        started = time.perf_counter()
        final_error: MCPExecutionError | None = None
        if CAPABILITIES[tool_name] != "read" and not arguments.get("idempotency_key"):
            raise MCPExecutionError("MCP_IDEMPOTENCY_REQUIRED", "MCP write actions require an idempotency key.", retryable=False)
        max_attempts = self._max_attempts if CAPABILITIES[tool_name] == "read" or arguments.get("idempotency_key") else 1
        for attempt in range(1, max_attempts + 1):
            http_client, transport = await self._session()
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    async with transport as (read_stream, write_stream, _session_id):
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()
                            result = await session.call_tool(
                                tool_name,
                                arguments,
                                read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
                            )
                if result.isError:
                    raise MCPExecutionError("MCP_UNAVAILABLE", "MCP tool execution failed before a structured response was returned.", retryable=True)
                payload = result.structuredContent
                if not isinstance(payload, dict) or payload.get("tool") != tool_name or "status" not in payload:
                    raise MCPExecutionError("MCP_INVALID_RESPONSE", "MCP tool returned an invalid response.", retryable=False)
                if payload.get("status") in {"failed", "rejected"}:
                    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
                    raise MCPExecutionError(
                        str(error.get("code") or "MCP_TOOL_REJECTED"),
                        str(error.get("message") or "MCP tool rejected the request."),
                        retryable=bool(error.get("retryable", False)),
                    )
                await self._record(tool_name, arguments, "succeeded", started, None, "verified" if CAPABILITIES[tool_name] == "high_risk" else "not_required")
                return payload
            except MCPExecutionError as error:
                final_error = error
                if not error.retryable:
                    break
            except TimeoutError:
                final_error = MCPExecutionError("MCP_TIMEOUT", "MCP tool call timed out.", retryable=True)
            except Exception:
                final_error = MCPExecutionError("MCP_UNAVAILABLE", "Brand tools MCP is unavailable.", retryable=True)
            finally:
                await http_client.aclose()
            if attempt < max_attempts:
                await asyncio.sleep(0.1 * attempt)
        assert final_error is not None
        status = "timed_out" if final_error.code == "MCP_TIMEOUT" else "failed"
        approval_result = "invalid" if CAPABILITIES[tool_name] == "high_risk" and arguments.get("decision_id") else "missing" if CAPABILITIES[tool_name] == "high_risk" else "not_required"
        await self._safe_record(tool_name, arguments, status, started, final_error.code, approval_result)
        raise final_error

    async def _safe_record(self, tool_name: str, arguments: dict[str, object], status: str, started: float, error_code: str | None, approval_result: str) -> None:
        try:
            await self._record(tool_name, arguments, status, started, error_code, approval_result)
        except Exception:
            return

    async def _record(self, tool_name: str, arguments: dict[str, object], status: str, started: float, error_code: str | None, approval_result: str) -> None:
        await self._recorder.record_tool_call({
            "workspace_id": self._workspace_id,
            "task_id": self._task_id,
            "workflow_node": self._workflow_node,
            "mcp_server": "brandflow-brand-tools",
            "tool_name": tool_name,
            "capability": CAPABILITIES[tool_name],
            "sanitized_input": self._sanitized_input(arguments),
            "output_status": status,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "error_code": error_code,
            "error_summary": "Tool execution failed" if error_code else None,
            "approval_result": approval_result,
            "approval_decision_id": arguments.get("decision_id"),
            "target_snapshot_hash": arguments.get("target_snapshot_hash"),
            "idempotency_key": arguments.get("idempotency_key"),
            "request_id": f"mcp:{self._task_id}:{tool_name}:{time.time_ns()}",
        })
