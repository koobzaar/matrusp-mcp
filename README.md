# MatrUSP MCP

Servidor MCP read-only para consultar ofertas, turmas, horários e currículos públicos do JupiterWeb da USP. O runtime nunca acessa a rede: ele abre um snapshot SQLite verificado em `mode=ro&immutable=1`.

Read-only MCP server for public USP JupiterWeb offerings, sections, schedules and curricula. Runtime never contacts JupiterWeb; it reads an integrity-checked immutable SQLite snapshot.

## Arquitetura / Architecture

`crawler` coleta e normaliza HTML com TLS, retries e concorrência limitada. `snapshot` publica SQLite atomically after integrity, foreign-key, schema and smoke checks. `repository`, `temporal` and `engine` implement search, semi-open intervals, conflict states and deterministic top-K schedules. `mcp_server` exposes the same service over stdio and Streamable HTTP (`/mcp`).

The public tools are `search_offerings`, `get_discipline`, `find_gap_fillers`, `check_schedule_conflicts`, `generate_schedules`, `compare_schedules`, `search_curricula` and `get_curriculum`. The resource `matrusp://snapshot/manifest` provides provenance, schema version, license and counts.

Horários usam intervalos `[início, fim)`, datas inclusivas e retornam `unknown` quando incompletos. Ofertas sem horário não entram em buscas temporais ou combinações por padrão; vagas são observações datadas, nunca garantias.

## Execução / Running

```bash
uv sync
uv run matrusp-mcp serve --transport stdio --snapshot data/matrusp.sqlite
uv run matrusp-mcp serve --transport streamable-http --snapshot data/matrusp.sqlite
uv run matrusp-mcp validate data/matrusp.sqlite
```

O servidor HTTP oferece somente `/mcp`, `/healthz` e `/readyz`, valida Host/Origin, limita corpos a 256 KiB e aplica rate limit em memória (60 tokens/minuto, burst 20, custos ponderados por tool). Configure `MATRUSP_SNAPSHOT`, `MATRUSP_ALLOWED_HOSTS`, `MATRUSP_ALLOWED_ORIGINS` e `MATRUSP_TRUSTED_PROXY_CIDRS` no proxy oficial; nenhum IP ou argumento é persistido.

## Coleta e publicação / Crawler and releases

```bash
uv run matrusp-mcp crawl --output /tmp/matrusp.sqlite \
  --previous /path/to/previous.sqlite --artifacts /tmp/release
```

O índice do Jupiter é apenas uma lista de candidatos. Cada candidato termina como `confirmed` ou `no_current_offer`; qualquer fetch/parse não classificado aborta a promoção atômica. A coleta de currículos usa somente `tipo=N`, inclui habilitações, requisitos fortes/fracos e indicações de conjunto; grades históricas (`tipo=V`) não são percorridas. Disciplinas curriculares sem oferta recebem stubs. Versões são reutilizadas por `(discipline_code, verdis)`, o histórico é mesclado do snapshot anterior e os códigos de período da fonte são preservados.

Releases válidos publicam `matrusp-snapshot-{snapshot_id}.sqlite.gz`, `manifest-{snapshot_id}.json` e `SHA256SUMS`, com tag imutável `snapshot-v1-{UTC_TIMESTAMP}`. A opção `--artifacts` produz esses três arquivos somente após a validação do banco. A imagem Docker é reconstruída somente depois de um release válido; o workflow baixa o snapshot anterior e aplica a proteção de delta superior a 20%.

## Desenvolvimento / Development

```bash
uv run pytest --cov=matrusp_mcp --cov-branch
uv run ruff check .
uv run pyright
```

O projeto requer Python 3.12+, usa o SDK oficial MCP v2 (`mcp>=2,<3`) e não publica no PyPI na v1. O snapshot de bootstrap em `data/matrusp.sqlite` é pequeno e apenas para desenvolvimento/imagem; dados de produção devem ser obtidos pelo workflow de coleta.

## Dados e licença / Data and license

Fontes primárias: páginas públicas `https://uspdigital.usp.br/jupiterweb/`; o manifesto registra URLs, horários de observação, checksums, commit do crawler e contagens. O código é AGPL-3.0-only. Consulte [LICENSE](LICENSE) e [CONTRIBUTORS.md](CONTRIBUTORS.md) para a licença, atribuição e histórico da comunidade MatrUSP.
