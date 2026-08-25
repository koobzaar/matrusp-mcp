# Referência MCP

## Contrato comum

O servidor expõe oito ferramentas MCP v2 e um recurso. Todas as ferramentas são declaradas como:

- `readOnlyHint: true`;
- `destructiveHint: false`;
- `idempotentHint: true`;
- `openWorldHint: false`;
- saída estruturada validada por Pydantic.

Toda resposta bem-sucedida usa o mesmo envelope:

```json
{
  "snapshot_id": "identificador-imutavel",
  "observed_at": "2026-01-01T12:00:00+00:00",
  "warnings": [],
  "data": {}
}
```

`warnings` agrega condições de qualidade encontradas recursivamente, como horário parcial ou
desconhecido, flags da fonte e disciplinas `stub`. Os modelos de entrada rejeitam campos não
declarados com `extra="forbid"`.

Erros públicos são serializados com código e mensagem:

| Código | Significado |
|---|---|
| `invalid_input` | horário, data, bloco, filtro ou restrição inválida |
| `not_found` | disciplina, turma, bundle ou currículo inexistente |
| `stale_cursor` | cursor criado para outro snapshot |
| `search_too_broad` | consulta textual ampla demais para o limite seguro do FTS |

## `search_offerings`

Pesquisa ofertas correntes por texto, organização, professor e horário.

| Campo | Tipo | Regra |
|---|---|---|
| `query` | `string \| null` | código ou texto normalizado |
| `professor` | `string \| null` | busca insensível a acentos e caixa |
| `campus` | `string \| null` | campus normalizado |
| `unit_code` | `string \| null` | código exato de unidade |
| `department` | `string \| null` | departamento normalizado |
| `days` | `string[]` | dias aceitos pela normalização |
| `start_time` | `HH:MM \| null` | exige `end_time` |
| `end_time` | `HH:MM \| null` | deve ser posterior a `start_time` |
| `window_mode` | `overlaps \| contained` | padrão `overlaps` |
| `include_unknown` | `boolean` | padrão `false` |
| `limit` | `integer` | `1..50`, padrão `20` |
| `cursor` | `string \| null` | paginação opaca e vinculada ao snapshot |

Em `overlaps`, o encontro precisa satisfazer simultaneamente o filtro de dia e a interseção de
horário. Em `contained`, a semântica existente de contenção é preservada. Intervalos são
semiabertos: um encontro que termina exatamente no início da janela não intersecta a janela.

Saída principal: `data.items` e `data.next_cursor`.

## `get_discipline`

Obtém uma disciplina por `code`, incluindo versões, unidades, detalhes acadêmicos, seções e
bundles relacionados. Uma disciplina originada apenas de currículo pode retornar `is_stub: true` e
um aviso correspondente.

```json
{"code": "MAC0110"}
```

## `find_gap_fillers`

Encontra bundles que intersectam ou cabem integralmente em uma janela e que são compatíveis com a
seleção atual.

| Campo | Tipo | Regra |
|---|---|---|
| `day` | `string` | obrigatório |
| `start_time` | `HH:MM` | obrigatório |
| `end_time` | `HH:MM` | obrigatório e posterior ao início |
| `window_mode` | `overlaps \| contained` | padrão `overlaps` |
| `bundle_ids` | `string[]` | seleção existente por bundle |
| `section_ids` | `string[]` | seleção existente por turma |
| `include_unknown` | `boolean` | permite considerar itens não completos |

No modo `contained`, todos os encontros do bundle precisam estar no dia solicitado e contidos na
janela. No modo `overlaps`, pelo menos um encontro do mesmo dia precisa cruzar a janela. Bundles em
conflito ou com compatibilidade desconhecida com a seleção atual não são retornados.

## `check_schedule_conflicts`

Verifica conflitos entre bundles, turmas e bloqueios manuais.

```json
{
  "bundle_ids": ["bundle:MAC0110:1"],
  "section_ids": [],
  "blocks": [
    {
      "id": "trabalho",
      "day": "segunda",
      "start_time": "14:00",
      "end_time": "16:00",
      "start_date": "2026-02-23",
      "end_date": "2026-06-30"
    }
  ]
}
```

Também é possível usar `items`, com objetos discriminados por `bundle_id`, `section_id` ou
`block`. A saída contém:

- `state`: `conflict`, `no_conflict` ou `unknown`;
- `conflicts`: pares conflitantes e encontros responsáveis;
- `unknown_pairs`: pares que não podem ser decididos com os dados disponíveis.

Datas de blocos usam ISO `YYYY-MM-DD`, são opcionais e inclusivas. O identificador do bloco é
opcional; na ausência, o serviço gera `block:{index}`.

## `generate_schedules`

Gera combinações top-K determinísticas de bundles completos e selecionáveis.

| Campo | Tipo | Regra |
|---|---|---|
| `required_disciplines` | `string[]` | `1..15`, códigos únicos |
| `allowed_bundle_ids` | `string[]` | restringe o universo quando informado |
| `existing_bundle_ids` | `string[]` | seleção fixa incorporada às alternativas |
| `blocks` | `object[]` | bloqueios manuais |
| `max_results` | `integer` | `1..50`, padrão `10` |
| `node_budget` | `integer` | `1..1.000.000`, padrão `1.000.000` |
| `preferences` | `object` | pesos, professores e janelas preferidas |
| `hard_constraints` | `object` | restrições finais e filtros de dia |

Preferências:

| Campo | Intervalo | Efeito no score |
|---|---:|---|
| `days_weight` | `0..100` | penaliza dias ativos |
| `gaps_weight` | `0..100` | penaliza horas de intervalo |
| `outside_preferred_windows_weight` | `0..100` | penaliza horas fora das janelas |
| `avoided_professors_weight` | `0..100` | penaliza professores evitados |
| `preferred_professors_weight` | `0..100` | bonifica professores preferidos |

As listas `avoided_professors`, `preferred_professors` e `preferred_windows` completam esses pesos.
Quando uma lista é informada com peso explícito zero, o serviço usa peso efetivo `1` para que a
preferência tenha efeito.

Restrições reconhecidas em `hard_constraints`:

| Chave | Tipo | Regra |
|---|---|---|
| `forbidden_days` | `string[]` | elimina candidatos com encontro nesses dias |
| `required_days` | `string[]` | exige que todos esses dias estejam ativos |
| `max_active_days` | `integer` | limita dias ativos |
| `max_total_gap_hours` | `number` | limita horas totais de intervalo |

A resposta informa `schedules`, `truncated`, `explored_nodes` e `discard_reasons`. Consulte
[Semântica temporal e geração de horários](temporal-and-ranking.md) para o algoritmo e o score.

## `compare_schedules`

Compara de `1` a `50` alternativas, cada uma formada por uma lista de IDs de bundle. Aceita os
mesmos `blocks` e `preferences` do gerador. Para cada alternativa retorna `state`, `score` e
`metrics`, sem alterar a ordem de entrada.

## `search_curricula`

Pesquisa currículos atuais.

| Campo | Tipo | Regra |
|---|---|---|
| `query` | `string \| null` | curso, habilitação ou texto relacionado |
| `unit_code` | `string \| null` | filtro de unidade |
| `campus` | `string \| null` | filtro de campus |
| `limit` | `integer` | `1..50`, padrão `20` |

## `get_curriculum`

Obtém a estrutura completa pelo identificador
`curriculum:{course_code}:{habilitation_code}`. Itens incluem natureza, período ideal, créditos e
relações de requisito forte, requisito fraco e indicação de conjunto.

```json
{"curriculum_id": "curriculum:45052:4"}
```

## Recurso `matrusp://snapshot/manifest`

Retorna JSON com identidade, versão de schema, licença, horário de observação, origem, checksums,
commit do crawler e contagens do snapshot. O recurso permite verificar a proveniência sem consultar
uma ferramenta de domínio.
