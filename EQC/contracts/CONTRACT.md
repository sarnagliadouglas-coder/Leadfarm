# Contrato QUALIFICADOR → COMERCIAL

**Versão:** 2.1.0
**Schema formal:** `leads_qualificados.schema.json` (JSON Schema draft 2020-12)
**Arquivo físico:** `leads_qualificados_<AAAAMMDD>-<HHMMSS>_v<contract_version>.json`, gravado em `QUALIFICADOR_OUTPUT_DIR` (hoje `EQC\pipeline\qualificador-output\`)
**Sidecar:** `<mesmo-nome-base>.meta.json`

Este documento é a versão legível do schema. Em caso de divergência, o `.schema.json` é a fonte de verdade — este arquivo existe para orientação rápida, não para arbitrar disputa de formato.

## Princípios do contrato

O arquivo contém três listas: `nata`, `candidatos_triagem` e `descartados`.
Leads sem site próprio, ou sem evidência suficiente para uma das duas listas de
trabalho, ficam fora do JSON e serão tratados em etapa posterior.

`nata` contém site próprio com pelo menos um `problema_vendavel` comprovado.
`candidatos_triagem` contém site próprio sem problema vendável detectado,
`review_count >= 10`, renderização verificada e PSI verificado. Esses leads
também carregam `candidato_triagem_visual`; o veredito visual pertence ao
COMERCIAL e não atravessa este contrato.

1. **Um dono por fato.** Todo campo que atravessa esta fronteira tem um responsável único (QUALIFICADOR ou um agente específico do COMERCIAL). Ver a matriz de autoridade no histórico do projeto para a lista completa.
2. **`priorizacao` não é autoritativo.** O bloco inteiro existe só para ordenar fila de atendimento. Nenhum agente do COMERCIAL deve usar `commercial_fit_score`, `priority`, `priority_label` ou qualquer campo deste bloco para *julgar* um lead — julgamento é função do COMERCIAL sobre evidência verificada, não herança de score do QUALIFICADOR. O campo `priorizacao.autoritativo` é sempre `false` e existe justamente para lembrar isso em runtime.
3. **`evidencias_qualificador` é fato puro.** Sem interpretação. É o material que o A1 (Investigação) deve confirmar ou refutar.
4. **A lista do lead decide o trabalho.** Não existe campo de pista, trilha ou rota.

## O que muda por trilha

| Bloco / campo | `COMPLETO_SEM_SITE` (Onda 1) | `COMPLETO_COM_SITE` (Onda 2) |
|---|---|---|
| `evidencias_qualificador.sinais_site` | `null` | dict cru de sinais do HTML |
| `priorizacao.contactability` | populado | `null` |
| `priorizacao.risks` | populado | `null` |
| `priorizacao.website_opportunity_score` / `priority_score` / `priority_label` / `lacunas_interpretadas` | `null` | populado |
| `priorizacao.priority` | populado (`alta`/`media`/`baixa`) | `null` |
| `priorizacao.reasons` | populado | populado |
| `analise_tecnica_site` (as 3 chaves) | `null` | populado |
| `texto_site` (2.1.0, opcional) | `null` (sem site a medir) | `null` (sem medição ainda) \| `{estado: NAO_VERIFICADO, ...}` \| objeto completo (`texto`, `chars_originais`, `truncado`, `dispositivo`, `coletado_em`) quando medido |

`priority` e `priority_label` nunca são o mesmo campo: `priority_label` tem um estado extra (`needs_review`) que `priority` não representa. Não assuma equivalência.

## O que **não** está no contrato (removido deliberadamente)

- `extractor_opportunity_raw` — julgamento comercial do EXTRATOR (regra "Unclaimed = oportunidade"), nunca deveria atravessar esta fronteira.
- `fit`, `campaign` — campos mortos, sem consumidor.
- `reason_to_contact` — existe só como saída de console operacional do QUALIFICADOR. Nunca aparece neste JSON (há teste travando isso).
- `qualificacao_comercial`, `site_analise` (nomes antigos) — substituídos por `evidencias_qualificador` + `priorizacao` + `analise_tecnica_site`.

## Vocabulário de `estado` (campos `{valor, estado}`)

| Valor | Significa |
|---|---|
| `CONFIRMADO_PRESENTE` | O dado foi checado e está presente. |
| `CONFIRMADO_AUSENTE` | O dado foi checado e confirmadamente não existe. |
| `NAO_VERIFICADO` | A fonte que confirmaria esse dado não foi consultada (ex: deep-scrape não rodou para este lead). |

Importante para o A1: `NAO_VERIFICADO` não é o mesmo que `CONFIRMADO_AUSENTE`. O primeiro é "não sabemos", o segundo é "sabemos que não tem". Tratar os dois como equivalentes descarta informação que pode valer a pena investigar ao vivo.

## Regra regional embutida

`contato.whatsapp_apto` aplica a regra de celular espanhol (prefixo 6/7 após normalização de código de país). É específica do mercado ES — se o projeto expandir para outro país, este campo precisa de revisão, não é genérico.

## Idioma

Chaves e enums em português. Valores de texto livre (nomes, endereços, categorias) preservam o idioma da fonte (espanhol, leads da Espanha). Ver decisão D5 no histórico do projeto.

## Histórico de versões

### 2.1.0 — MINOR, aditiva
Acrescenta o campo opcional `texto_site` por lead: o texto visível do site
(innerText renderizado, espaços colapsados, nunca HTML), até o limite de
`config/texto_site.json` do QUALIFICADOR (hoje 4000 caracteres), preferindo o
dispositivo mobile, com o desktop como alternativa. Mesmo vocabulário de
`psi` (não é `{valor, estado}` — é `null` | `{estado: NAO_VERIFICADO, ...}` |
objeto completo com `estado: CONFIRMADO_PRESENTE`). Nenhum campo existente
mudou, nenhuma chave obrigatória mudou — por isso é MINOR, não MAJOR.
Autorizado pelo diretor, 24/09/2026.

### 2.0.0
- Substitui a lista única `leads` por `nata` e `candidatos_triagem`, mantendo `descartados`.
- Acrescenta `classe_site`, `problema_vendavel`, `candidato_triagem_visual` e
  `analise_tecnica_site.telefone_na_pagina`.
- `sem_contato_visivel` só é emitido quando a renderização está `medido` e os
  dois dispositivos não exibem contato; `lento_no_celular` usa exclusivamente
  PSI com `lcp_ms > 4000`; `fora_do_ar` aceita 404/5xx e erros de rede, mas
  nunca 403. Dado não verificado nunca vira problema.
- O telefone na página distingue `link`, `texto`, ausência confirmada e não verificado.

### 1.1.0
- **Acrescenta `contato.linkedin`** (`{valor, estado}`, no mesmo padrão de `instagram`/`facebook`). Motivo: o EXTRATOR captura a coluna `LinkedIn` (dado real em ~9% dos leads de um CSV recente) e o A1 do COMERCIAL declarou precisar dele; era dado sendo perdido na fronteira. É **só transporte de evidência** — não entra em `whatsapp_apto`, `contactability`, `commercial_fit_score` nem em nenhum outro cálculo do QUALIFICADOR.
- Mudança retrocompatível em leitura (campo novo), mas **incrementa `contract_version`** porque o conjunto de chaves obrigatórias do payload mudou (`contato.linkedin` é `required`).

### 1.0.0
- Primeira versão formalizada após a correção de Fase 3.
