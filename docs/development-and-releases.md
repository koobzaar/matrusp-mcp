# Desenvolvimento, testes e releases

## Ambiente

O projeto usa Python `3.12` e uv `0.12.5` como versão de referência. `pyproject.toml` aceita
`uv>=0.10.11,<0.13` para compatibilidade com o runtime da Vercel. Não use `pip`, Python global ou
edição manual de `.venv`.

```bash
uv sync --locked
```

Para alterar dependências:

```bash
uv add nome-do-pacote
uv add --dev nome-do-pacote
uv remove nome-do-pacote
```

`pyproject.toml` e `uv.lock` devem entrar juntos no commit. `uv lock --upgrade` é reservado para
upgrades intencionais.

## Qualidade local

Execute antes de enviar uma mudança:

```bash
uv run --locked pytest --cov=matrusp_mcp --cov-branch
uv run --locked ruff check .
uv run --locked pyright
uv run --locked matrusp-mcp validate data/matrusp.sqlite
uv build
docker build --tag matrusp-mcp:test .
git diff --check
```

Configuração:

| Ferramenta | Política |
|---|---|
| pytest | testes em `tests/`, configuração e markers estritos |
| pytest-asyncio | `asyncio_mode = "auto"` |
| pytest-cov | branch coverage mínima de `90%` |
| Hypothesis | propriedades e casos combinatórios |
| Ruff | Python 3.12, linha de `100` caracteres |
| Pyright | `typeCheckingMode = "strict"` |
| Hatchling | wheel e sdist via `uv build` |

Testes espelham os módulos em `src/matrusp_mcp/` e usam o padrão `test_<behavior>`. Regressões devem
cobrir limites, estados desconhecidos e ordenação determinística.

## Contrato JupiterWeb ao vivo

Testes normais não acessam a rede. O contrato ao vivo é explícito:

```bash
uv run --locked playwright install chromium
MATRUSP_RUN_LIVE_CONTRACT=1 \
  uv run --locked pytest -m live_contract
```

O contrato abre páginas representativas, envia o HTML aos parsers reais e verifica:

- classificação válida de oferta ou ausência;
- IDs de turma únicos;
- encontros com dia e horários plausíveis;
- currículos com itens plausíveis.

Fixtures determinísticas em `tests/fixtures/` reproduzem somente a forma relevante do DOM. HTML
completo baixado do JupiterWeb não deve ser commitado.

## Estrutura de testes

| Área | Cobertura principal |
|---|---|
| crawler/parsers | DOM aninhado, horários, vagas, currículos e detalhes |
| temporal | intervalos semiabertos, datas e incerteza |
| repository/service | FTS, cursores, filtros, envelopes e erros |
| engine | top-K, empates, orçamento, restrições e força bruta |
| HTTP | Host/Origin, corpos, rate limit, proxy e requisições normais |
| snapshot | integridade, foreign keys, manifesto, delta e artefatos |
| MCP | ferramentas, recurso, anotações e transportes |

## CI

`.github/workflows/ci.yml` executa em todo push e pull request:

1. checkout;
2. instalação do uv `0.12.5`;
3. `uv sync --locked`;
4. Ruff;
5. Pyright;
6. pytest com cobertura de branches;
7. build de wheel e sdist;
8. build da imagem Docker.

O workflow tem somente permissão de leitura de conteúdo.

## Live contract agendado

`.github/workflows/contract.yml` roda manualmente e às segundas-feiras, `11:30 UTC`. Ele instala o
Chromium com dependências e define `MATRUSP_RUN_LIVE_CONTRACT=1`. Sua função é detectar alterações
no DOM antes que elas contaminem um snapshot.

## Snapshot semanal

`.github/workflows/snapshot.yml` roda manualmente e às segundas-feiras, `11:00 UTC`, com grupo de
concorrência `snapshot-release` sem cancelamento de execução anterior.

Fluxo:

1. baixa o snapshot da última release, quando existente;
2. coleta para `/tmp/matrusp.sqlite` e gera artefatos;
3. aplica proteção de delta em relação ao snapshot anterior;
4. valida o novo SQLite;
5. copia o snapshot validado para o contexto temporário do build;
6. exige build Docker válido;
7. cria uma GitHub Release imutável;
8. publica a imagem GHCR somente depois da release.

Tags da imagem:

```text
ghcr.io/{owner}/{repository}:{git_sha}
ghcr.io/{owner}/{repository}:{snapshot_id}
ghcr.io/{owner}/{repository}:latest
```

Tag da release:

```text
snapshot-v1-{UTC_TIMESTAMP}
```

O workflow publica `matrusp-snapshot-{snapshot_id}.sqlite.gz`,
`manifest-{snapshot_id}.json` e `SHA256SUMS`. O snapshot de produção não é atualizado por commits
comuns; ele pertence a esse fluxo separado de release.

## Imagem de produção

O `Dockerfile` instala o pacote em `python:3.12-slim`, valida o banco durante o build, muda para
UID/GID `10001` e executa o servidor HTTP na porta `8000`. A imagem só é enviada ao GHCR depois que
o release do snapshot foi criado com sucesso.

## Commits e pull requests

Use Conventional Commits:

```text
feat: descrição imperativa
fix: descrição imperativa
docs: descrição imperativa
test: descrição imperativa
refactor: descrição imperativa
build: descrição imperativa
ci: descrição imperativa
chore: descrição imperativa
```

O corpo do commit deve registrar motivação, mudanças técnicas e verificações. Alterações de schema,
API, crawler ou snapshot devem ser destacadas no pull request. Não misture snapshot gerado com
mudança de código.

## Segurança e integridade

- não commitar credenciais ou configuração de produção;
- preservar SQLite imutável no runtime;
- preservar validações de Host e Origin;
- não reduzir validações de snapshot para contornar uma fonte quebrada;
- não converter dados desconhecidos em valores afirmativos;
- validar artefatos antes de release e imagem;
- manter pins de uv no projeto e nos workflows sincronizados.
