# Contrato QUALIFICADOR → COMERCIAL

**Versão:** 2.3.0
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

## Campanha e aviso de mesmo negócio (2.2.0; cidade em 2.3.0)

| Campo | Onde | Conteúdo |
|---|---|---|
| `campanha_id` | cada lead de `nata` / `candidatos_triagem` e cada item de `descartados` | `{valor, estado}`: id da campanha (uma por nicho, `EQC/config/campanhas/`) usada no import do lead — a escolhida pelo termo da busca ou, em lista sem termo, a ativa do menu (`EQC/config/campanha_ativa.json`). Nunca re-carimbado. Lead importado antes de 2.2.0 → `{valor: null, estado: NAO_VERIFICADO}` |
| `campanha_nicho` | idem | `{valor, estado}`: rótulo humano do nicho da campanha (campo `nicho` da campanha). Mesma regra de `NAO_VERIFICADO` |
| `campanha_cidade` | idem | (2.3.0) `{valor, estado}`: cidade da campanha no import — o município do termo da busca, validado pela lista oficial de municípios do INE e gravado na grafia oficial da forma digitada (ex.: `Alacant` ou `Alicante`), ou a `cidade_padrao` da campanha em lista sem termo. Nunca re-carimbado. Lead importado antes de 2.3.0 → `{valor: null, estado: NAO_VERIFICADO}` |
| `possivel_mesmo_negocio` | cada lead de `nata` / `candidatos_triagem` | `{valor, estado}`. O filtro de redes do QUALIFICADOR agrupa fichas por telefone normalizado e por domínio do site próprio (domínio de portal, construtor, rede social ou página do Google não agrupa), sobre todo o pool. Grupo com 3+ fichas é descartado (`rede_ou_multiunidade`); grupo de 2 não é descartado e marca as duas: `valor` = lista `[{place_id, por: telefone\|dominio, chave}]` da(s) outra(s) ficha(s), `estado: CONFIRMADO_PRESENTE`. Checado sem par → `{valor: null, estado: CONFIRMADO_AUSENTE}`. Lead anterior ao filtro → `NAO_VERIFICADO`. É **aviso**, não julgamento: o COMERCIAL decide o que fazer |

Motivos de descarte acrescentados em 2.2.0 (`descartados[*].motivo` é texto livre no
schema): `rede_ou_multiunidade` e `linha_deslocada_irrecuperavel`. Os cortes de categoria da
campanha usam os motivos já existentes `icp_categoria_fora_do_perfil` /
`icp_categoria_excluida`. Quando o import gravou o detalhe do corte, ele vem em
`campos_do_corte.detalhe_do_corte` (`{valor, estado: CONFIRMADO_PRESENTE}`).

## CSV humano (fronteira QUALIFICADOR → COMERCIAL)

Além do JSON, o QUALIFICADOR grava a cada `saida` um CSV com as pistas **Direta** e
**Espera** — os leads que **não** atravessam o JSON (sem site próprio, ou site próprio sem
problema vendável que não virou candidato à triagem). É a fonte da aba Geral da planilha do
COMERCIAL. **Não** é validado por schema: este quadro é a referência legível.

- Arquivo: `qualificador_<AAAAMMDD>-<HHMMSS>.csv` (sem número de versão), em
  `EQC/pipeline/saidas-humanas/` (env `QUALIFICADOR_SAIDA_HUMANA_OUTPUT_DIR` vence).
- Formato: UTF-8 com BOM, delimitador `;`, uma linha de cabeçalho.
- **Colunas novas entram sempre no fim**; a ordem das existentes não muda.

| # | Coluna | Conteúdo |
|---|---|---|
| 1 | `pista` | `direta` \| `espera` |
| 2 | `motivo` | Por que está na pista (`sem site`, `site é portal`, `site é rede social`, `site é página do Google`, `site em construtor gratuito`, `sem problema encontrado`) |
| 3 | `nome` | Nome da ficha do Google |
| 4 | `nicho` | 1ª categoria do Google (corrigida nas linhas deslocadas) |
| 5 | `cidade` | Cidade depois do CEP; vazia quando não confiável |
| 6 | `telefone` | Telefone resolvido |
| 7 | `email` | 1º e-mail |
| 8 | `instagram` | Instagram |
| 9 | `site` | Valor do campo Website da ficha |
| 10 | `classe_site` | `sem_site` \| `portal` \| `rede_social` \| `superficie_google` \| `construtor` \| `proprio` |
| 11 | `avaliacoes` | Número de avaliações; vazio se desconhecido |
| 12 | `nota` | Nota do Google; vazia se desconhecida |
| 13 | `google_maps_url` | Link da ficha |
| 14 | `place_id` | Identificador da ficha |
| 15 | `campanha_id` | (2.2.0) id da campanha ativa no import; `NAO_VERIFICADO` em lead anterior ao carimbo |
| 16 | `campanha_nicho` | (2.2.0) nicho da campanha ativa no import; `NAO_VERIFICADO` idem |
| 17 | `possivel_mesmo_negocio` | (2.2.0) place_id(s) da(s) outra(s) ficha(s) do par, separados por vírgula; vazio = checado sem par; `NAO_VERIFICADO` = lead anterior ao filtro |
| 18 | `prioridade_rotulo` | (2.2.0) Prioridade da Onda 1 (`alta` \| `media` \| `baixa`, `qualificacao.priority`); vazio nas linhas que vêm da Onda 2. **Não autoritativa**, como `priorizacao` |
| 19 | `prioridade_score` | (2.2.0) Score da Onda 1 (0–100, `qualificacao.score`); vazio nas linhas da Onda 2. **Não autoritativo** |
| 20 | `campanha_cidade` | (2.3.0) cidade da campanha no import (mesma regra do campo do JSON); `NAO_VERIFICADO` em lead anterior ao carimbo. Não confundir com a coluna 5 (`cidade`), que é a cidade do endereço da ficha |

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

### 2.3.0 — MINOR, aditiva
Acrescenta, por lead (`nata`, `candidatos_triagem`) e por descartado, o campo
**obrigatório** `campanha_cidade` (`{valor, estado}`, `NAO_VERIFICADO` para lead importado
antes de 2.3.0), e a coluna 20 `campanha_cidade` no fim do CSV humano. Motivo: as campanhas
passam a ser uma por nicho, sem cidade fixa; a cidade vem do termo da busca (validada pela
lista oficial de municípios do INE) ou, em lista sem termo, da `cidade_padrao` da campanha.
Conjunto de chaves obrigatórias mudou; MINOR segue o precedente de 1.1.0 e 2.2.0.
**Não é compatível em nenhum dos dois sentidos:** o schema 2.3.0 recusa arquivos 2.2.0
(falta `campanha_cidade` e o `const` de `contract_version` é outro), e um consumidor 2.2.0
recusa arquivos 2.3.0 (`contract_version` diferente e `additionalProperties: false` nos
blocos `lead` e `descartado`). Produtor e consumidor precisam passar para 2.3.0 juntos.
No CSV humano a coluna nova entra no fim; um leitor que só conhece as 19 primeiras colunas
continua lendo-as nas mesmas posições.
Autorizado pelo diretor, 06/10/2026.

### 2.2.0 — MINOR, aditiva
Acrescenta, por lead (`nata`, `candidatos_triagem`), os campos **obrigatórios**
`campanha_id`, `campanha_nicho` e `possivel_mesmo_negocio`, e por descartado
`campanha_id` e `campanha_nicho` — todos `{valor, estado}`, com `NAO_VERIFICADO` para lead
importado antes de 2.2.0. Documenta os motivos de descarte `rede_ou_multiunidade` e
`linha_deslocada_irrecuperavel` e o `campos_do_corte.detalhe_do_corte`. Documenta, como
fronteira, as colunas do CSV humano, com cinco colunas novas no fim (`campanha_id`,
`campanha_nicho`, `possivel_mesmo_negocio`, `prioridade_rotulo`, `prioridade_score`).
Conjunto de chaves obrigatórias mudou; MINOR segue o precedente de 1.1.0 (`linkedin`).
**Não é compatível em nenhum dos dois sentidos:** como os campos novos são obrigatórios, o
schema 2.2.0 recusa arquivos 2.1.0 (faltam as chaves e o `const` de `contract_version` é
outro), e um consumidor 2.1.0 recusa arquivos 2.2.0 (`contract_version` diferente e
`additionalProperties: false` nos blocos `lead` e `descartado`). Produtor e consumidor
precisam passar para 2.2.0 juntos.
Autorizado pelo diretor, 04/10/2026.

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
