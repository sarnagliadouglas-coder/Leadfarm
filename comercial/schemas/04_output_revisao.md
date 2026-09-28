# Schema — Output do Agente 4 (Revisor)

## Descrição

Estrutura do output produzido pelo Agente 4 — Revisor.
Determina se a abordagem é aprovada (PASS) ou rejeitada (FAIL).

## Consumidores

- Pipeline (decisão de fluxo: output final ou retorno ao Agente 3)
- Agente 3 — Copywriter (em caso de FAIL, recebe o output completo para correção direcionada)

## Campos

### Campos comuns (PASS e FAIL)

- `resultado` — PASS ou FAIL
- `checklist` — lista de itens validados, cada um com status (ok / problema)

### Campos adicionais em caso de PASS

- `observacoes` — notas opcionais do revisor (não bloqueantes)

### Campos adicionais em caso de FAIL

- `problemas` — lista estruturada de problemas encontrados (ver estrutura abaixo)
- `instrucao_geral` — resumo do que precisa mudar, em uma frase

### Estrutura de cada problema (FAIL)

Cada item na lista `problemas` deve conter:

| Campo | Descrição |
|---|---|
| `trecho` | O trecho específico da abordagem que contém o problema (citação direta) |
| `categoria` | Tipo do problema: `factualidade`, `coerencia`, `qualidade`, `regra_comercial` |
| `severidade` | `critico` (bloqueia aprovação) ou `relevante` (deve ser corrigido mas não invalida sozinho) |
| `descricao` | O que está errado, de forma objetiva |
| `instrucao` | O que o Agente 3 deve fazer para corrigir este trecho específico |

### Regras do FAIL

- Cada problema deve ser independente e acionável isoladamente
- A `instrucao` deve ser específica o suficiente para o Agente 3 corrigir sem reescrever tudo
- O revisor NÃO reescreve a abordagem — apenas aponta onde e o que corrigir
- Problemas sem `trecho` identificável (ex: problema estrutural geral) usam `trecho: null` e descrevem o problema na `descricao`
- **`categoria: factualidade` + `severidade: critico` é obrigatório quando a copy afirma algo rastreável apenas a `inferencias` (ou a nada) do dossiê do Agente 1, não a `fatos_observados`.** Ver [01_output_investigacao.md](01_output_investigacao.md), "O circuito fechado A1 ↔ A4" — esta é a trava que fecha o circuito do lado do A4.

## Formato

<!-- TODO: Definir formato final (JSON, YAML, etc.) -->

## Exemplo

<!-- TODO: Incluir exemplo de output PASS e FAIL com a estrutura acima -->
