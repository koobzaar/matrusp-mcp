# Segurança

O MatrUSP MCP é um servidor público, somente-leitura e baseado em snapshots. Ainda assim, falhas em
parsing, transporte HTTP, dependências ou validação de entrada podem afetar usuários e deployments.

## Reportar uma vulnerabilidade

Não abra uma issue pública para uma vulnerabilidade. Use a opção **Report a vulnerability** na aba
**Security** do GitHub para enviar um relatório privado. Se essa opção não estiver disponível, entre
em contato privado com o mantenedor por um canal indicado no perfil de `@koobzaar`.

Inclua, quando possível:

- descrição e impacto;
- passos mínimos para reprodução;
- versão, commit ou ambiente afetado;
- evidência sem credenciais, tokens ou dados pessoais;
- uma sugestão de mitigação, se houver.

Não faça testes destrutivos contra deployments públicos. Para testes locais, use snapshots de
desenvolvimento e valores fictícios.
