# Usar o MatrUSP MCP no ChatGPT

Este tutorial conecta o servidor público do MatrUSP ao ChatGPT pela internet. Ele não instala
Python nem o snapshot local: o ChatGPT usa as ferramentas do endpoint remoto.

## Antes de começar

O recurso depende do plano e das políticas da conta ou do workspace. É necessário que o ChatGPT
mostre o modo de desenvolvedor e permita conexões MCP personalizadas. Se essa opção não aparecer,
um administrador precisa habilitá-la quando a política do workspace permitir; não há um procedimento
local que contorne essa restrição.

Este projeto expõe um servidor remoto read-only. A conexão MCP e a skill
`matrusp-academic-planning` são componentes distintos: conectar o endpoint não instala
automaticamente a skill.

## Conectar o servidor MCP

Faça isso no ChatGPT pela web:

1. Abra **Settings → Security and login** e ative **Developer mode**.
2. Abra **ChatGPT Plugins**, selecione o botão **+** e crie uma nova conexão.
3. Informe um nome, por exemplo `MatrUSP MCP`, e uma descrição como `Consultas acadêmicas públicas da USP`.
4. Em **Connection**, escolha uma conexão por endpoint público e informe exatamente:
   `https://matrusp-mcp.vercel.app/mcp`
5. Crie a conexão e revise as ferramentas e os metadados descobertos.
6. Abra uma nova conversa, abra o menu de ferramentas e selecione **MatrUSP MCP**.

O caminho `/mcp` é necessário; `/healthz` e `/readyz` servem apenas para verificar a implantação.
O endpoint atual não exige autenticação.

## Testar

Na conversa com a conexão habilitada, experimente:

```text
Use o MatrUSP MCP para encontrar ofertas atuais de MAC0101 e liste dias, horários e professores.
```

```text
Use o MatrUSP MCP para montar alternativas de grade para MAC0101 e MAC0102,
priorizando menos dias no campus e sem conflitos.
```

Confira se a resposta informa o `snapshot_id` e se distingue dados desconhecidos de ausência de
conflito. Horários, vagas e currículos são observações do snapshot, não uma confirmação de matrícula.

## Usar também a skill

A skill versionada está em [`skills/matrusp-academic-planning/`](../skills/matrusp-academic-planning/),
com seu `SKILL.md` e as referências de ferramentas e agendamento. Ela ensina sequências de uso,
critérios de filtragem e limites de interpretação; não substitui o servidor MCP.

Este repositório ainda não é um plugin público instalável com um clique no ChatGPT: ele contém a
skill independente e o servidor remoto, mas não um manifesto `.codex-plugin/plugin.json` nem uma
publicação no diretório público de plugins. Para distribuir a skill e o MCP juntos a outros usuários,
é necessário empacotar um plugin, testar sua conexão e submetê-lo/publicá-lo nas superfícies
apropriadas. Consulte a documentação oficial sobre [conectar e testar plugins](https://developers.openai.com/plugins/deploy/connect-chatgpt),
[criar skills](https://developers.openai.com/plugins/build/skills) e
[empacotar plugins](https://developers.openai.com/plugins/build/plugins).

## Se a conexão falhar

- Confirme que o endereço termina em `/mcp` e que o modo de desenvolvedor está habilitado.
- Atualize a conexão para redescobrir ferramentas e metadados depois de uma alteração no servidor.
- Se a opção de conexão não estiver disponível, verifique a política do plano/workspace ou peça
  ajuda ao administrador.
- Não envie dados pessoais ou informações acadêmicas privadas: este é um endpoint público de
  consulta e o servidor MCP é um serviço de terceiros.

O fluxo acima segue a documentação oficial de [conexão de plugins no ChatGPT](https://developers.openai.com/plugins/deploy/connect-chatgpt)
e de [MCP e Connectors](https://developers.openai.com/api/docs/guides/tools-connectors-mcp).
