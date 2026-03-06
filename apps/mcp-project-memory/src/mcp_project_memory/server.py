from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import FunctionResource
import mcp.types as types
from mcp.shared.message import SessionMessage

from .config import load_config
from .store import ProjectMemoryStore


class ProjectMemoryServer:
    def __init__(self, config_path: str | None = None) -> None:
        self.store = ProjectMemoryStore(load_config(config_path))
        self.mcp = FastMCP("mcp-project-memory")
        self._registered_resources: set[str] = set()
        self._register_tools()
        self.refresh_resources()

    def refresh_resources(self) -> None:
        descriptors = {
            descriptor["uri"]: descriptor
            for descriptor in self.store.list_resource_descriptors()
        }
        stale_uris = self._registered_resources - set(descriptors)
        for uri in stale_uris:
            self.mcp._resource_manager._resources.pop(uri, None)
            self._registered_resources.remove(uri)

        for descriptor in descriptors.values():
            uri = descriptor["uri"]
            if uri in self._registered_resources:
                continue
            self.mcp.add_resource(
                FunctionResource(
                    uri=uri,
                    name=descriptor["name"],
                    mime_type=descriptor["mime_type"],
                    fn=self._make_resource_reader(uri),
                )
            )
            self._registered_resources.add(uri)

    def _make_resource_reader(self, uri: str):
        def reader() -> str:
            return self.store.read_resource_text(uri)

        return reader

    def _register_tools(self) -> None:
        @self.mcp.tool(description="Persist the canonical episode state snapshot")
        def update_episode_state(
            project_id: str,
            episode_id: str,
            state: dict[str, Any],
        ) -> dict[str, Any]:
            payload = self.store.update_episode_state(project_id, episode_id, state)
            self.refresh_resources()
            return payload

        @self.mcp.tool(description="Append an auditable decision entry to the episode log")
        def record_decision(
            project_id: str,
            episode_id: str,
            type: str,
            reason: str,
            author: str,
            evidence_refs: list[str] | None = None,
        ) -> dict[str, Any]:
            payload = self.store.record_decision(
                project_id=project_id,
                episode_id=episode_id,
                decision_type=type,
                reason=reason,
                author=author,
                evidence_refs=evidence_refs,
            )
            self.refresh_resources()
            return payload

        @self.mcp.tool(description="Persist the confirmed structured plan for an episode")
        def confirm_plan(
            project_id: str,
            episode_id: str,
            plan: dict[str, Any],
        ) -> dict[str, Any]:
            payload = self.store.confirm_plan(project_id, episode_id, plan)
            self.refresh_resources()
            return payload

        @self.mcp.tool(description="Persist canonical structure annotations for an episode")
        def save_structure_annotations(
            project_id: str,
            episode_id: str,
            annotations: dict[str, Any],
        ) -> dict[str, Any]:
            payload = self.store.save_structure_annotations(project_id, episode_id, annotations)
            self.refresh_resources()
            return payload

        @self.mcp.tool(description="Import experiment results and link them to candidates or runs")
        def import_experiment_results(
            project_id: str,
            episode_id: str,
            result: dict[str, Any],
            experiment_id: str | None = None,
            candidate_ids: list[str] | None = None,
            run_ids: list[str] | None = None,
        ) -> dict[str, Any]:
            payload = self.store.import_experiment_results(
                project_id=project_id,
                episode_id=episode_id,
                result=result,
                experiment_id=experiment_id,
                candidate_ids=candidate_ids,
                run_ids=run_ids,
            )
            self.refresh_resources()
            return payload

        @self.mcp.tool(description="Archive an episode and generate a reproducibility manifest")
        def archive_episode(project_id: str, episode_id: str) -> dict[str, Any]:
            payload = self.store.archive_episode(project_id, episode_id)
            self.refresh_resources()
            return payload

    def run_stdio(self) -> None:
        anyio.run(self.run_stdio_async)

    async def run_stdio_async(self) -> None:
        read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

        async def stdin_reader() -> None:
            loop = asyncio.get_running_loop()
            chunks: asyncio.Queue[bytes | None] = asyncio.Queue()

            def on_readable() -> None:
                chunk = os.read(sys.stdin.fileno(), 65536)
                if chunk:
                    chunks.put_nowait(chunk)
                    return
                loop.remove_reader(sys.stdin.fileno())
                chunks.put_nowait(None)

            loop.add_reader(sys.stdin.fileno(), on_readable)
            try:
                async with read_stream_writer:
                    buffer = bytearray()
                    while True:
                        chunk = await chunks.get()
                        if chunk is None:
                            break
                        buffer.extend(chunk)
                        while True:
                            newline_index = buffer.find(b"\n")
                            if newline_index < 0:
                                break
                            line = bytes(buffer[: newline_index + 1])
                            del buffer[: newline_index + 1]
                            try:
                                message = types.JSONRPCMessage.model_validate_json(line.decode("utf-8"))
                            except Exception as exc:
                                await read_stream_writer.send(exc)
                                continue
                            await read_stream_writer.send(SessionMessage(message))
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()
            finally:
                loop.remove_reader(sys.stdin.fileno())

        async def stdout_writer() -> None:
            try:
                async with write_stream_reader:
                    async for session_message in write_stream_reader:
                        payload = session_message.message.model_dump_json(
                            by_alias=True,
                            exclude_none=True,
                        )
                        os.write(sys.stdout.fileno(), (payload + "\n").encode("utf-8"))
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()

        async with anyio.create_task_group() as tg:
            tg.start_soon(stdin_reader)
            tg.start_soon(stdout_writer)
            await self.mcp._mcp_server.run(
                read_stream,
                write_stream,
                self.mcp._mcp_server.create_initialization_options(),
            )
def create_server(config_path: str | None = None) -> ProjectMemoryServer:
    return ProjectMemoryServer(config_path)


def run_stdio(config_path: str | None = None) -> None:
    create_server(config_path).run_stdio()
