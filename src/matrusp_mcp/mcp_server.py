"""Exposição MCP v2: um servidor e oito tools somente-leitura."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TypeVar, cast

import anyio
from anyio.to_thread import run_sync
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.message import SessionMessage
from mcp.types import ToolAnnotations, jsonrpc_message_adapter

from .api_models import (
    CheckConflictsInput,
    CompareSchedulesInput,
    FindGapFillersInput,
    GenerateSchedulesInput,
    GetCurriculumInput,
    GetDisciplineInput,
    PublicResponse,
    SearchCurriculaInput,
    SearchOfferingsInput,
)
from .service import PublicError, Service

TOOL_NAMES = (
    "search_offerings",
    "get_discipline",
    "find_gap_fillers",
    "check_schedule_conflicts",
    "generate_schedules",
    "compare_schedules",
    "search_curricula",
    "get_curriculum",
)
_Request = TypeVar("_Request")


def _call(service: Service, operation: str, request: _Request) -> PublicResponse:
    try:
        return cast(PublicResponse, getattr(service, operation)(request))
    except PublicError as error:
        raise ToolError(
            json.dumps(
                {"code": error.code, "message": error.message}, ensure_ascii=False, sort_keys=True
            )
        ) from error
    except ValueError as error:
        raise ToolError(
            json.dumps(
                {"code": "invalid_input", "message": str(error)}, ensure_ascii=False, sort_keys=True
            )
        ) from error


def create_server(snapshot_path: Path | None = None) -> MCPServer:
    path = snapshot_path or Path(os.environ.get("MATRUSP_SNAPSHOT", "data/matrusp.sqlite"))
    service = Service.from_path(path)
    annotations = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    server = MCPServer(
        "matrusp-mcp",
        title="MatrUSP MCP",
        description="Read-only queries over versioned public USP academic snapshot data.",
        instructions=(
            "Use these read-only tools to query the versioned USP academic snapshot. "
            "Every response includes snapshot provenance and may include data warnings."
        ),
        website_url="https://github.com/koobzaar/matrusp-mcp",
        version="0.1.0",
    )

    @server.tool(
        name="search_offerings",
        title="Search offerings",
        annotations=annotations,
        structured_output=True,
    )
    async def search_offerings(request: SearchOfferingsInput) -> PublicResponse:
        """Busca ofertas correntes (Search current offerings), com filtros temporais e de professor."""
        return _call(service, "search_offerings", request)

    @server.tool(
        name="get_discipline",
        title="Get discipline",
        annotations=annotations,
        structured_output=True,
    )
    async def get_discipline(request: GetDisciplineInput) -> PublicResponse:
        """Obtém uma disciplina versionada (Get a versioned discipline), inclusive stubs sem oferta."""
        return _call(service, "get_discipline", request)

    @server.tool(
        name="find_gap_fillers",
        title="Find gap fillers",
        annotations=annotations,
        structured_output=True,
    )
    async def find_gap_fillers(request: FindGapFillersInput) -> PublicResponse:
        """Encontra ofertas que cabem ou interceptam uma janela (Find gap fillers)."""
        return _call(service, "find_gap_fillers", request)

    @server.tool(
        name="check_schedule_conflicts",
        title="Check schedule conflicts",
        annotations=annotations,
        structured_output=True,
    )
    async def check_schedule_conflicts(request: CheckConflictsInput) -> PublicResponse:
        """Verifica conflitos, incluindo pares desconhecidos (Check schedule conflicts)."""
        return _call(service, "check_schedule_conflicts", request)

    @server.tool(
        name="generate_schedules",
        title="Generate schedules",
        annotations=annotations,
        structured_output=True,
    )
    async def generate_schedules(request: GenerateSchedulesInput) -> PublicResponse:
        """Gera combinações determinísticas top-K (Generate deterministic schedules)."""
        return _call(service, "generate_schedules", request)

    @server.tool(
        name="compare_schedules",
        title="Compare schedules",
        annotations=annotations,
        structured_output=True,
    )
    async def compare_schedules(request: CompareSchedulesInput) -> PublicResponse:
        """Compara alternativas (Compare schedule alternatives) com a mesma semântica temporal."""
        return _call(service, "compare_schedules", request)

    @server.tool(
        name="search_curricula",
        title="Search curricula",
        annotations=annotations,
        structured_output=True,
    )
    async def search_curricula(request: SearchCurriculaInput) -> PublicResponse:
        """Busca currículos atuais (Search current curricula)."""
        return _call(service, "search_curricula", request)

    @server.tool(
        name="get_curriculum",
        title="Get curriculum",
        annotations=annotations,
        structured_output=True,
    )
    async def get_curriculum(request: GetCurriculumInput) -> PublicResponse:
        """Obtém a estrutura de um currículo (Get curriculum structure)."""
        return _call(service, "get_curriculum", request)

    @server.resource("matrusp://snapshot/manifest", mime_type="application/json")
    async def snapshot_manifest() -> str:
        """Manifesto de proveniência, licença, schema e estatísticas do snapshot."""
        return json.dumps(service.repository.manifest, ensure_ascii=False, sort_keys=True)

    return server


async def run_stdio(server: MCPServer) -> None:
    """Run stdio with line framing, avoiding platform-specific fd redirection.

    The SDK's stdio helper claims file descriptors so that accidental writes
    cannot corrupt the wire.  Some embedded runners expose streams that do not
    support that claim reliably; memory streams preserve the same MCP framing
    and keep the public server/tool layer identical.
    """
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    inbound_send, inbound_receive = anyio.create_memory_object_stream[SessionMessage | Exception](256)
    outbound_send, outbound_receive = anyio.create_memory_object_stream[SessionMessage](0)

    loop = asyncio.get_running_loop()
    standard_input = sys.stdin.fileno()
    input_open = True

    def dispatch_line(line: str) -> None:
        try:
            message = jsonrpc_message_adapter.validate_json(line, by_name=False)
        except Exception as error:
            inbound_send.send_nowait(error)
        else:
            inbound_send.send_nowait(SessionMessage(message))

    def read_stdin() -> None:
        nonlocal input_open
        if not input_open:
            return
        line = sys.stdin.readline()
        if not line:
            input_open = False
            loop.remove_reader(standard_input)
            close_task = loop.create_task(inbound_send.aclose())
            close_task.add_done_callback(lambda _: None)
            return
        dispatch_line(line)

    async def read_stdin_thread() -> None:
        nonlocal input_open
        while input_open:
            line = await run_sync(sys.stdin.readline)
            if not line:
                input_open = False
                await inbound_send.aclose()
                return
            dispatch_line(line)

    async def write_stdout() -> None:
        async with outbound_receive:
            async for message in outbound_receive:
                sys.stdout.write(message.message.model_dump_json(by_alias=True, exclude_unset=True))
                sys.stdout.write("\n")
                sys.stdout.flush()

    async with anyio.create_task_group() as task_group:
        reader_registered = False
        try:
            loop.add_reader(standard_input, read_stdin)
        except (NotImplementedError, PermissionError):
            task_group.start_soon(read_stdin_thread)
        else:
            reader_registered = True
        task_group.start_soon(write_stdout)
        try:
            await server._lowlevel_server.run(
                inbound_receive,
                outbound_send,
                server._lowlevel_server.create_initialization_options(),
            )
        finally:
            if reader_registered and input_open:
                loop.remove_reader(standard_input)
            await inbound_send.aclose()
