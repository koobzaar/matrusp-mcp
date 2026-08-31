# Contribuindo

Obrigado por contribuir com o MatrUSP MCP.

## Antes de começar

Leia o [README](README.md), o [guia de desenvolvimento e releases](docs/development-and-releases.md)
e o [AGENTS.md](AGENTS.md). O runtime deve continuar somente-leitura e offline; mudanças no crawler,
no schema, nos snapshots ou na superfície MCP precisam explicar impacto e proveniência.

## Ambiente e verificações

Use Python 3.12 e uv. Não use `pip`, Python global ou edite `.venv` manualmente:

```bash
uv sync --locked
uv run --locked pytest --cov=matrusp_mcp --cov-branch
uv run --locked ruff check .
uv run --locked pyright
uv run --locked matrusp-mcp validate data/matrusp.sqlite
uv build
```

Testes que acessam o JupiterWeb são opt-in e devem ser executados somente quando necessário, com
`MATRUSP_RUN_LIVE_CONTRACT=1`. Não inclua HTML baixado nem snapshots de produção em um pull request
comum.

## Commits e pull requests

Use [Conventional Commits](https://www.conventionalcommits.org/), por exemplo
`fix: handle empty schedule window`. Mantenha cada commit focado, descreva a motivação e registre as
verificações executadas.

O pull request deve explicar:

- o comportamento alterado e por quê;
- mudanças de API, schema, crawler ou snapshot;
- testes, coverage, lint, type-check e build relevantes;
- qualquer limitação que ainda dependa de um serviço externo.

## Segurança

Não publique credenciais, dados pessoais ou detalhes de vulnerabilidades em issues. Consulte
[SECURITY.md](SECURITY.md) para reportar problemas de segurança.
