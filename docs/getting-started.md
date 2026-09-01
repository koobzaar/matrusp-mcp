# Instalação e execução

## Requisitos

| Componente | Versão ou função |
|---|---|
| Python | `3.12` ou superior |
| uv | `>=0.10.11,<0.13`; desenvolvimento e CI usam `0.12.5` |
| SQLite | snapshot local com schema MatrUSP v1 |
| MCP | SDK Python `mcp>=2,<3` |

O `uv` é o único gerenciador de ambiente e dependências do projeto. Todos os comandos de
desenvolvimento usam o lockfile e não alteram suas resoluções. A faixa compatível inclui o runtime
Python da Vercel (`0.10.11`) sem mudar a versão de referência do projeto (`0.12.5`).

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

## Vercel

O runtime Python da Vercel carrega `asgi:app`, configurado em `pyproject.toml`. O arquivo
`vercel.json` inclui explicitamente `data/matrusp.sqlite` no bundle da função; o runtime continua
somente-leitura e offline. O workflow semanal de snapshot atualiza esse arquivo em `main` somente após
um crawl e uma validação bem-sucedidos, fazendo a integração Git da Vercel construir o snapshot novo.

A instância pública atual do transporte MCP está disponível em
`https://matrusp-mcp.vercel.app/mcp`.

Ao importar o repositório na Vercel, use o preset `Other`, mantenha a raiz do repositório e deixe
Build Command, Output Directory e Install Command sem override. A plataforma detecta
`pyproject.toml` e `uv.lock`.

Habilite a exposição automática das variáveis de sistema da Vercel. O entrypoint aceita os hosts
presentes em `VERCEL_URL`, `VERCEL_BRANCH_URL` e `VERCEL_PROJECT_PRODUCTION_URL`, cobrindo os
deployments de Preview e Production sem liberar hosts arbitrários.

`MATRUSP_SNAPSHOT=data/matrusp.sqlite` é opcional. Use `MATRUSP_ALLOWED_HOSTS` apenas para acrescentar
domínios que não estejam nas variáveis da plataforma, como um domínio personalizado adicional.
`MATRUSP_ALLOWED_ORIGINS` permanece opt-in.

Depois do deployment, verifique:

```bash
curl https://matrusp-mcp.vercel.app/healthz
curl https://matrusp-mcp.vercel.app/readyz
```

## Próximos passos

- [Usar o MatrUSP no ChatGPT](chatgpt.md)
- [Referência MCP](mcp-reference.md)
- [Arquitetura](architecture.md)
- [Semântica temporal e geração de horários](temporal-and-ranking.md)
- [Snapshots e crawler](snapshots-and-crawler.md)
- [Desenvolvimento e releases](development-and-releases.md)
