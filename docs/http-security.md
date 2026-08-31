# Segurança e transporte HTTP

## Superfície ASGI

O transporte Streamable HTTP é stateless e responde em JSON. A aplicação expõe apenas:

| Método e rota | Função |
|---|---|
| `POST /mcp` | chamadas MCP |
| `GET /mcp` | `405` — o endpoint stateless não abre stream SSE |
| `GET /healthz` | liveness e `snapshot_id` |
| `GET /readyz` | validação do snapshot, contagens e erros |

`/readyz` responde `200` quando o snapshot é válido e `503` quando a validação falha.

## Ordem de middleware

```mermaid
flowchart LR
    Q[Request] --> H[Host / Origin]
    H --> T[GET /mcp: 405]
    T --> B[Body 256 KiB]
    B --> M[MCP application]
```

A ordem é uma propriedade de segurança:

1. `HostOriginMiddleware` rejeita o destino antes de consumir o corpo;
2. `BodyLimitMiddleware` limita corpo declarado ou em chunks;
3. a aplicação MCP recebe somente requisições que cruzaram os limites anteriores.

## Host e Origin

Hosts permitidos por padrão:

```text
localhost
localhost:*
127.0.0.1
127.0.0.1:*
testserver
testserver:*
```

`MATRUSP_ALLOWED_HOSTS` substitui a lista padrão por valores CSV. O sufixo `:*` aceita qualquer
porta para o nome exato anterior. Host não confiável retorna `421` sem ler o corpo.

Se o cabeçalho `Origin` estiver presente, ele precisa corresponder a
`MATRUSP_ALLOWED_ORIGINS`. Com a lista vazia, qualquer Origin de navegador é rejeitado com `403`.
Clientes não navegadores que omitem Origin continuam sujeitos ao controle de Host.

```bash
MATRUSP_ALLOWED_HOSTS=mcp.exemplo.br \
MATRUSP_ALLOWED_ORIGINS=https://app.exemplo.br \
uv run --locked matrusp-mcp serve \
  --transport streamable-http \
  --host 127.0.0.1
```

## Limite de corpo

O limite máximo é `256 KiB` (`262144` bytes).

| Caso | Resposta |
|---|---|
| `Content-Length` não inteiro ou negativo | `400` |
| `Content-Length` acima do limite | `413` sem consumir o corpo |
| corpo chunked cruza o limite | `413` imediatamente após o chunk excedente |
| corpo dentro do limite | conteúdo recomposto e repassado uma vez |

O SDK MCP recebe o mesmo limite como defesa adicional.

## Limites da proteção embutida

O servidor não oferece autenticação, autorização por usuário, TLS ou persistência de auditoria. Uma
exposição pública deve usar proxy ou gateway para esses controles, mantendo
`MATRUSP_ALLOWED_HOSTS` e `MATRUSP_ALLOWED_ORIGINS` restritos.

## Checklist de implantação

- terminar TLS no proxy;
- exigir autenticação antes de `/mcp`;
- encaminhar somente `/mcp`, `/healthz` e `/readyz`;
- definir Host e Origin explicitamente;
- montar o snapshot como somente-leitura;
- executar como usuário sem privilégios;
- monitorar `503`, duração e `snapshot_id`.
