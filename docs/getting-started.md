# Instalação e execução

## Requisitos

| Componente | Versão ou função |
|---|---|
| Python | `3.12` ou superior |
| uv | `0.12.5`, fixado em `pyproject.toml` |
| SQLite | snapshot local com schema MatrUSP v1 |
| MCP | SDK Python `mcp>=2,<3` |

O `uv` é o único gerenciador de ambiente e dependências do projeto. Todos os comandos de
desenvolvimento usam o lockfile e não alteram suas resoluções.

```bash
git clone https://github.com/koobzaar/matrusp-mcp.git
cd matrusp-mcp
uv sync --locked
uv run --locked matrusp-mcp validate data/matrusp.sqlite
```

O arquivo `data/matrusp.sqlite` é um snapshot de desenvolvimento. O runtime não consulta o
JupiterWeb e abre esse arquivo com SQLite em `mode=ro&immutable=1`.

## Transporte stdio

```bash
uv run --locked matrusp-mcp serve \
  --transport stdio \
  --snapshot data/matrusp.sqlite
```

Exemplo de configuração de um cliente MCP após `uv sync --locked`:

```json
{
  "mcpServers": {
    "matrusp": {
      "command": "/caminho/absoluto/matrusp/.venv/bin/matrusp-mcp",
      "args": [
        "serve",
        "--transport",
        "stdio",
        "--snapshot",
        "/caminho/absoluto/matrusp/data/matrusp.sqlite"
      ]
    }
  }
}
```

Use caminhos absolutos porque clientes desktop normalmente não herdam o diretório de trabalho
do terminal. O protocolo usa JSON-RPC delimitado por linha em `stdin` e `stdout`; mensagens de
diagnóstico não são escritas no canal MCP.

## Streamable HTTP

```bash
uv run --locked matrusp-mcp serve \
  --transport streamable-http \
  --snapshot data/matrusp.sqlite \
  --host 127.0.0.1 \
  --port 8000
```

Endpoints:

| Rota | Função |
|---|---|
| `/mcp` | transporte MCP Streamable HTTP |
| `/healthz` | processo ativo |
| `/readyz` | snapshot carregado e serviço pronto |

Para uma implantação pública, configure um proxy reverso com TLS e autenticação. O servidor
embutido não implementa esses dois controles. Os limites, cabeçalhos confiáveis e variáveis de
ambiente são descritos em [Segurança e transporte HTTP](http-security.md).

## Configuração

| Variável | Uso | Padrão |
|---|---|---|
| `MATRUSP_SNAPSHOT` | caminho do snapshot SQLite | `data/matrusp.sqlite` |
| `MATRUSP_ALLOWED_HOSTS` | lista CSV de valores `Host` permitidos | somente hosts locais |
| `MATRUSP_ALLOWED_ORIGINS` | lista CSV de origens permitidas | nenhuma origem de navegador |
| `MATRUSP_TRUSTED_PROXY_CIDRS` | CIDRs autorizados a fornecer `X-Forwarded-For` | nenhum |

Argumentos de linha de comando prevalecem sobre os padrões. `--snapshot` também prevalece sobre
`MATRUSP_SNAPSHOT`.

## Imagem Docker

```bash
docker build --tag matrusp-mcp:test .
docker run --rm \
  --publish 127.0.0.1:8000:8000 \
  matrusp-mcp:test
```

A imagem:

- usa `python:3.12-slim`;
- valida o snapshot durante o build;
- executa como usuário sem privilégios, UID/GID `10001`;
- expõe a porta `8000` e inclui `HEALTHCHECK`;
- inicia o transporte Streamable HTTP em `0.0.0.0:8000`.

Para usar outro snapshot, monte-o somente para leitura e defina `MATRUSP_SNAPSHOT`:

```bash
docker run --rm \
  --publish 127.0.0.1:8000:8000 \
  --volume /caminho/snapshot.sqlite:/data/matrusp.sqlite:ro \
  --env MATRUSP_SNAPSHOT=/data/matrusp.sqlite \
  matrusp-mcp:test
```

## Próximos passos

- [Referência MCP](mcp-reference.md)
- [Arquitetura](architecture.md)
- [Semântica temporal e geração de horários](temporal-and-ranking.md)
- [Snapshots e crawler](snapshots-and-crawler.md)
- [Desenvolvimento e releases](development-and-releases.md)
