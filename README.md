<div align="center">
  <h1>MatrUSP MCP</h1>
  <p>Servidor MCP read-only para ofertas, horários e currículos públicos da USP.</p>

  <p>
    <a href="docs/getting-started.md">Instalação</a> •
    <a href="docs/mcp-reference.md">MCP</a> •
    <a href="docs/architecture.md">Arquitetura</a> •
    <a href="docs/development-and-releases.md">Desenvolvimento</a>
  </p>

  <p>
    <a href="https://github.com/koobzaar/matrusp-mcp/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/koobzaar/matrusp-mcp/ci.yml?branch=tcc2016&amp;label=CI" alt="CI"/></a>
    <a href="https://github.com/koobzaar/matrusp-mcp/actions/workflows/contract.yml"><img src="https://img.shields.io/github/actions/workflow/status/koobzaar/matrusp-mcp/contract.yml?label=live%20contract" alt="Live contract"/></a>
    <img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&amp;logoColor=white" alt="Python 3.12"/>
    <img src="https://img.shields.io/badge/MCP-v2-5A45FF" alt="MCP v2"/>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0--only-663399" alt="AGPL-3.0-only"/></a>
  </p>
</div>

## Tecnologias

`Python 3.12` · `MCP v2` · `Pydantic v2` · `Starlette` · `Uvicorn` · `SQLite FTS5` ·
`Beautiful Soup` · `httpx` · `uv` · `Docker` · `Playwright` · `pytest` · `Ruff` · `Pyright`

## Documentação técnica

| Área | Referência |
|---|---|
| Instalação, stdio, Streamable HTTP, Docker | [Instalação e execução](docs/getting-started.md) |
| Camadas, módulos, domínio, IDs, invariantes | [Arquitetura](docs/architecture.md) |
| Tools, inputs, respostas, erros, manifesto | [Referência MCP](docs/mcp-reference.md) |
| Intervalos, conflitos, bundles, top-K, score | [Semântica temporal e ranking](docs/temporal-and-ranking.md) |
| JupiterWeb, parsers, SQLite v1, artefatos | [Snapshots e crawler](docs/snapshots-and-crawler.md) |
| ASGI, Host, Origin, body limit, rate limit | [Segurança HTTP](docs/http-security.md) |
| uv, testes, CI, live contract, releases, GHCR | [Desenvolvimento e releases](docs/development-and-releases.md) |

## MCP tools

`search_offerings` · `get_discipline` · `find_gap_fillers` · `check_schedule_conflicts` ·
`generate_schedules` · `compare_schedules` · `search_curricula` · `get_curriculum`

## Licença

[AGPL-3.0-only](LICENSE) · [Contribuidores](CONTRIBUTORS.md) · Fonte: `JupiterWeb USP`
