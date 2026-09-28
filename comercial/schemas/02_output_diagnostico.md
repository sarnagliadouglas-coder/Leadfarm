# Schema — Output do Agente 2 (Diagnóstico Comercial)

## Descrição

Estrutura do output produzido pelo Agente 2 — Diagnóstico Comercial (o "diagnóstico").
Este output alimenta o Agente 3 (Copywriter) **ou** encerra o pipeline para este lead, quando não há ângulo comercial viável.

O Agente 2 responde **"existe oportunidade comercial, e qual é o melhor ângulo dentro do que vendemos?"**. Ele não responde "este lead é válido o suficiente para entrar no processo?" — essa pergunta já foi respondida pelo QUALIFICADOR antes deste lead chegar aqui (ver "A fronteira com o QUALIFICADOR" abaixo).

## Consumidores

- **Agente 3 — Copywriter** (input principal, apenas quando `decisao = prosseguir`)
- **Pipeline** (decisão de fluxo: prosseguir para o Agente 3 ou encerrar para este lead)

---

## A fronteira com o QUALIFICADOR — não recriar filtro que já existe

O QUALIFICADOR já respondeu "este lead é válido/ativo o suficiente para entrar no processo?" — os leads que não passaram nisso já foram descartados antes de chegar ao COMERCIAL (`rejection_reason`: `no_contact_no_signal` \| `large_organization` \| `icp_*` \| `sem_canal_de_contato` \| `qualification_declined`, ver `EQC\contracts\CONTRACT.md`). **Todo lead que o Agente 2 recebe já passou por isso.**

O Agente 2 **não desqualifica lead por**: ser negócio pequeno, ter poucas avaliações, ficha modesta, ou aparente falta de capacidade de investimento. Não há dados suficientes para avaliar isso, e negócio pequeno sem site é precisamente parte do público-alvo — filtrar por porte cortaria o núcleo do alvo, não o ruído.

> ## ⚠️ Regra dura — presunção de oportunidade na trilha `COMPLETO_SEM_SITE`
>
> Um lead que passou pelo QUALIFICADOR e não tem site é **presunção forte de oportunidade**. Para o Agente 2 concluir `sem_angulo` nessa trilha, é preciso existir um **fato concreto e específico**, encontrado no dossiê do Agente 1, que **invalide** essa presunção — não apenas um fato qualquer, um fato **relevante para a conclusão**.
>
> Exemplos de fato que invalida a presunção: o A1 descobriu que o negócio na verdade possui site (a ficha do Google estava desatualizada); o negócio encerrou as atividades; trata-se de filial de uma rede que centraliza a presença digital.
>
> Exemplo de fato que **não** invalida a presunção, mesmo sendo concreto, observável e rastreável: "possui poucas avaliações". Isso não diz nada sobre se o negócio se beneficiaria de ter um site — não serve como justificativa de `sem_angulo`.
>
> **Ausência de evidência não é evidência de ausência.** O Agente 2 não conclui que não há oportunidade só porque o dossiê não traz sinais *adicionais* de sucesso comercial — a ausência de site já é o sinal.
>
> Estruturalmente: `sem_angulo.fatos_ref` é **obrigatório e não pode ser vazio** quando `estagio_analise = COMPLETO_SEM_SITE` (Regra de validação 6). O validador não julga se o fato citado *de fato* invalida a presunção — isso é julgamento, não estrutura — mas exige que exista pelo menos uma referência rastreável a `fatos_observados` do dossiê. `sem_angulo` nessa trilha sem isso é **erro estrutural**, não uma conclusão só questionável.

Na trilha `COMPLETO_COM_SITE`, o julgamento é outro: existe um site, e a pergunta é se ele tem deficiência comercial relevante que a nossa oferta resolve. **Uma taxa alta de `sem_angulo` nessa trilha é esperada, não sinal de agente quebrado** — ver [agent.md](../agents/02_diagnostico_comercial/agent.md), seção "Sobre a taxa de `sem_angulo` por trilha".

---

## Princípios de construção

1. **O Agente 2 pode identificar múltiplos problemas e oportunidades num lead** — nunca reduz a análise a um único achado prematuramente.
2. **Todo achado preservado, nenhum apagado.** Ângulos não escolhidos como principal não são depreciados nem descartados — são ativos comerciais preservados para contatos futuros.
3. **Um único ângulo principal por diagnóstico**, com justificativa explícita da escolha.
4. **Inferência e incerteza do A1 orientam, nunca viram fato.** Toda `achado` que o A2 registra como evidência de peso comercial precisa ser rastreável a `fatos_observados` do dossiê — não a `inferencias` nem a `incertezas`. Esta é a regra mais fácil de violar sem perceber, e é a que o Agente 4 vai cobrar depois.
5. **`sem_angulo` é resultado legítimo e desejável** quando não existe oferta concreta a fazer — nunca um "não sei", e nunca inventar oportunidade só para manter o lead no funil.

---

## Estrutura

### Raiz

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `schema_version` | string | sim | `"1.0"` |
| `place_id` | string | sim | Identificador do lead, idêntico ao `place_id` do dossiê de origem |
| `dossie_origem` | string | sim | Nome do arquivo do dossiê do Agente 1 usado como base (`dossie_<place_id>_<timestamp>.json`) — rastreia qual dossiê gerou qual diagnóstico |
| `lote_origem` | string | sim | Eco do `lote_origem` do dossiê — rastreia a cadeia completa até o contrato do QUALIFICADOR |
| `estagio_analise` | enum | sim | `COMPLETO_SEM_SITE` \| `COMPLETO_COM_SITE` — eco de `qualificador.sinais_recebidos.estagio_analise` do dossiê. Determina qual regra de `sem_angulo` se aplica (ver acima) |
| `diagnosticado_em` | string (ISO 8601) | sim | Data/hora do diagnóstico |
| `modelo` | string | sim | Modelo LLM que produziu este diagnóstico. A política de escalonamento (equivalente à D2 do Agente 1) não foi decidida para o Agente 2 nesta rodada — este campo existe para rastreabilidade desde já; ver "Fora de escopo desta rodada" ao final |
| `decisao` | enum | sim | `prosseguir` \| `sem_angulo` |
| `achados` | array | sim | Todo problema/oportunidade identificado (ver definição abaixo). `[]` quando `decisao = sem_angulo` |
| `angulo_principal` | object \| null | sim | O achado escolhido para a primeira abordagem, com justificativa. `null` quando `decisao = sem_angulo` |
| `sem_angulo` | object \| null | sim | Motivo estruturado da conclusão. `null` quando `decisao = prosseguir` |

---

### 1. `achados` — todo problema e oportunidade identificado

O Agente 2 lista **tudo** que encontrou de relevante nos `fatos_observados` do dossiê — não só o que vai virar o ângulo principal. Cada achado é classificado por `papel`, que decide o que acontece com ele:

| `papel` | Significado |
|---|---|
| `principal` | O ângulo escolhido para a primeira abordagem. Exatamente um achado tem este papel quando `decisao = prosseguir` |
| `secundario` | Sustenta uma abordagem própria em outro momento — serve sozinho num segundo contato |
| `evidencia` | Apenas reforça o ângulo principal (ou outro achado que referencia) — não sustenta contato independente |

```json
{
  "id": "achado_001",
  "natureza": "problema",
  "descricao": "O formulário da página de contato retorna erro após o envio.",
  "relevancia_comercial": "alta",
  "papel": "principal",
  "fatos_ref": ["fato_004"],
  "inferencias_ref": [],
  "incertezas_ref": [],
  "reforca_achado_ref": null
}
```

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | string | sim | `achado_001`, `achado_002`… |
| `natureza` | enum | sim | `problema` \| `oportunidade` |
| `descricao` | string | sim | O achado, em termos comerciais (aqui, diferente do dossiê do A1, interpretação é o papel do agente) |
| `relevancia_comercial` | enum | sim | `alta` \| `media` \| `baixa` |
| `papel` | enum | sim | `principal` \| `secundario` \| `evidencia` |
| `fatos_ref` | array de string | sim | **≥ 1** id de `fatos_observados` do dossiê do A1 (Regra de validação 2). Todo achado é rastreável a fato, nunca só a inferência/incerteza |
| `inferencias_ref` | array de string | não | ids de `inferencias` do dossiê que **orientaram** este achado — nunca substituem `fatos_ref` |
| `incertezas_ref` | array de string | não | ids de `incertezas` do dossiê que **orientaram** este achado — nunca substituem `fatos_ref` |
| `reforca_achado_ref` | string \| null | condicional | **Obrigatório** (não `null`) quando `papel = evidencia` — aponta para o `achado` que este reforça. Ausente/`null` nos demais papéis |

**Sobre `inferencias_ref`/`incertezas_ref`:** citar uma inferência ou incerteza aqui documenta que ela orientou o raciocínio do Agente 2 (ex.: "o A1 suspeitava que o negócio reinvestiu em redes sociais — isso me fez procurar e confirmar X, que é o fato_007 citado em `fatos_ref`"). Uma inferência sozinha, sem fato de apoio, **nunca** justifica um achado — o achado sempre precisa do `fatos_ref`.

---

### 2. `angulo_principal` — a escolha e sua justificativa

```json
"angulo_principal": {
  "achado_ref": "achado_001",
  "justificativa_escolha": "É o problema com consequência mais direta e mensurável na jornada de conversão (perda de contatos via formulário), e o único achado com fato_observado de natureza 'problema' e confiança alta que a nossa oferta resolve diretamente."
}
```

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `achado_ref` | string | sim | Aponta para o `id` do achado com `papel: "principal"` em `achados` |
| `justificativa_escolha` | string | sim | Por que este achado, e não outro dos identificados, foi escolhido para a primeira abordagem |

Os achados não escolhidos como principal **não são removidos nem depreciados** na justificativa — a justificativa explica a escolha, não desqualifica os demais.

---

### 3. `sem_angulo` — motivo estruturado

```json
"sem_angulo": {
  "motivo_categoria": "site_adequado_sem_deficiencia_relevante",
  "motivo_descricao": "O site carrega rápido em mobile e desktop (fato_002, fato_003), expõe telefone/WhatsApp/formulário funcionais (fato_004, fato_005) e não apresenta nenhum problema de conversão ou acessibilidade identificado pela checklist base. Não há deficiência dentro do que vendemos (sites/performance/conversão) que justifique abordagem.",
  "motivo_crm": "Site já funciona bem — sem abertura clara para nossa oferta no momento.",
  "evidencias_consideradas": ["fato_002", "fato_003", "fato_004", "fato_005", "inf_001"],
  "fatos_ref": []
}
```

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `motivo_categoria` | string | sim | Classificação livre (mesma filosofia de `rejection_reason` do QUALIFICADOR — não é enum fechado, a lista pode crescer). Vocabulário recomendado: `presuncao_de_oportunidade_invalidada` (trilha `COMPLETO_SEM_SITE`), `site_adequado_sem_deficiencia_relevante` (trilha `COMPLETO_COM_SITE`), `negocio_inativo_ou_invalido`, `outro` |
| `motivo_descricao` | string | sim | Explicação objetiva, baseada em fato, não em suposição |
| `motivo_crm` | string | sim | Versão resumida e legível por alguém que não participou da análise |
| `evidencias_consideradas` | array de string | sim | Ids (`fato_`/`inf_`/`inc_`) analisados antes da conclusão — pode incluir inferências/incertezas, é o panorama completo considerado, não só a base factual estrita |
| `fatos_ref` | array de string | sim | Ids de `fatos_observados` (só `fato_`) que sustentam especificamente a conclusão de `sem_angulo`. **Obrigatório não-vazio quando `estagio_analise = COMPLETO_SEM_SITE`** (Regra de validação 6) — é aqui que mora o fato concreto que invalida a presunção de oportunidade. Pode ser `[]` na trilha `COMPLETO_COM_SITE`, onde a ausência de problema (não um fato específico de invalidação) já é o motivo |

---

## Formato

**JSON** como formato canônico. Persistido em disco conforme [agents/02_diagnostico_comercial/prompt.md](../agents/02_diagnostico_comercial/prompt.md), seção "Saída em disco".

---

## Regras de validação

1. Exatamente um `achado` tem `papel: "principal"` quando `decisao = prosseguir`, e `angulo_principal.achado_ref` aponta para esse mesmo id.
2. Todo `achado` tem `fatos_ref` com pelo menos um id, e todo id referenciado (`fatos_ref`, `inferencias_ref`, `incertezas_ref`) existe no dossiê de origem, no bloco correto (`fato_` só em `fatos_observados`, `inf_` só em `inferencias`, `inc_` só em `incertezas`).
3. Todo `achado` com `papel: "evidencia"` tem `reforca_achado_ref` apontando para um `id` de achado existente no mesmo diagnóstico. Achados com outros papéis têm este campo `null`.
4. `place_id` do diagnóstico é idêntico ao `place_id` do dossiê de origem.
5. `estagio_analise` do diagnóstico é idêntico a `qualificador.sinais_recebidos.estagio_analise` do dossiê de origem — é eco, não reclassificação.
6. Quando `decisao = sem_angulo` **e** `estagio_analise = COMPLETO_SEM_SITE`, `sem_angulo.fatos_ref` tem pelo menos um id, e esse id existe em `fatos_observados` do dossiê de origem. Ausência disso é **erro estrutural**, não uma conclusão questionável (ver "A fronteira com o QUALIFICADOR" acima).
7. `sem_angulo.evidencias_consideradas` — todo id referenciado existe no dossiê de origem, em algum dos três blocos (`fatos_observados`, `inferencias`, `incertezas`).
8. `achados = []` quando `decisao = sem_angulo`; `achados` não-vazio quando `decisao = prosseguir`.
9. `angulo_principal = null` quando `decisao = sem_angulo`; não-nulo quando `decisao = prosseguir`. Simetricamente para `sem_angulo` (null quando `prosseguir`, preenchido quando `sem_angulo`).

---

## Fora de escopo — o que este output NÃO contém

| Campo proibido | Agente responsável |
|---|---|
| Copy redigida / argumento pronto | Agente 3 |
| Re-julgamento de validade do lead (porte, poucas avaliações, etc. como motivo de desqualificação) | QUALIFICADOR — já decidido antes deste lead chegar aqui |
| Recalculo de `psi` ou de qualquer campo verificado do dossiê do A1 | Agente 1 |

---

## Fora de escopo desta rodada — decisões pendentes

- **Política de escalonamento de modelo (equivalente à D2 do Agente 1)** não foi definida para o Agente 2. O campo `modelo` existe para rastreabilidade, mas não há regra de "quando escalar para Opus 5" documentada aqui — a direção não tratou disso nesta rodada.
- **Um terceiro valor de `decisao`** (ex.: `inconclusivo`, para quando o dossiê do A1 está `bloqueada`/`parcial` a ponto de não permitir julgar a adequação do site na trilha `COMPLETO_COM_SITE`) não foi criado. Hoje, um dossiê insuficiente nessa trilha força uma escolha entre `prosseguir` com pouca base ou `sem_angulo` sob a categoria `outro` — nenhuma das duas é ideal. Sinalizado para decisão futura, não resolvido unilateralmente aqui.

---

## Exemplo

### `decisao = prosseguir`

```json
{
  "schema_version": "1.0",
  "place_id": "ChIJexemplo00000000000000000",
  "dossie_origem": "dossie_ChIJexemplo00000000000000000_20260908-142200.json",
  "lote_origem": "leads_qualificados_20260908-074342_v1.1.0.json",
  "estagio_analise": "COMPLETO_COM_SITE",
  "diagnosticado_em": "2026-09-08T15:00:00Z",
  "modelo": "claude-sonnet-5",
  "decisao": "prosseguir",
  "achados": [
    {
      "id": "achado_001",
      "natureza": "problema",
      "descricao": "O formulário de contato retorna erro após o envio — o único caminho de conversão dedicado do site está quebrado.",
      "relevancia_comercial": "alta",
      "papel": "principal",
      "fatos_ref": ["fato_004"],
      "inferencias_ref": [],
      "incertezas_ref": [],
      "reforca_achado_ref": null
    },
    {
      "id": "achado_002",
      "natureza": "problema",
      "descricao": "O botão de WhatsApp não aparece na versão mobile — perde-se o canal de contato mais rápido justamente em quem navega pelo celular.",
      "relevancia_comercial": "media",
      "papel": "secundario",
      "fatos_ref": ["fato_003"],
      "inferencias_ref": [],
      "incertezas_ref": [],
      "reforca_achado_ref": null
    },
    {
      "id": "achado_003",
      "natureza": "problema",
      "descricao": "O carregamento inicial no mobile é lento (~6s), o que agrava o problema do formulário: quem espera e ainda assim tenta contato pelo formulário encontra um erro no fim.",
      "relevancia_comercial": "media",
      "papel": "evidencia",
      "fatos_ref": ["fato_006"],
      "inferencias_ref": [],
      "incertezas_ref": [],
      "reforca_achado_ref": "achado_001"
    }
  ],
  "angulo_principal": {
    "achado_ref": "achado_001",
    "justificativa_escolha": "É o achado com maior relevância comercial e consequência mais direta e mensurável (perda de contatos via formulário), diretamente resolvido pela nossa oferta. O achado_002 (WhatsApp ausente no mobile) é preservado como ângulo secundário para um segundo contato, e o achado_003 (carregamento lento) reforça a urgência do problema do formulário sem sustentar sozinho uma abordagem."
  },
  "sem_angulo": null
}
```

### `decisao = sem_angulo`, trilha `COMPLETO_SEM_SITE`

```json
{
  "schema_version": "1.0",
  "place_id": "ChIJexemplo11111111111111111",
  "dossie_origem": "dossie_ChIJexemplo11111111111111111_20260908-142500.json",
  "lote_origem": "leads_qualificados_20260908-074342_v1.1.0.json",
  "estagio_analise": "COMPLETO_SEM_SITE",
  "diagnosticado_em": "2026-09-08T15:05:00Z",
  "modelo": "claude-sonnet-5",
  "decisao": "sem_angulo",
  "achados": [],
  "angulo_principal": null,
  "sem_angulo": {
    "motivo_categoria": "presuncao_de_oportunidade_invalidada",
    "motivo_descricao": "O A1 confirmou que o negócio é filial de uma rede nacional que centraliza toda a presença digital em um único site institucional (fato_006) — a ausência de site próprio desta unidade não é uma lacuna a preencher, é a política de presença digital do grupo. A presunção de oportunidade da trilha COMPLETO_SEM_SITE foi invalidada por este fato específico, não pela reputação ou porte do negócio.",
    "motivo_crm": "Filial de rede que já tem site institucional próprio — não há lacuna de presença digital a resolver aqui.",
    "evidencias_consideradas": ["fato_001", "fato_003", "fato_006", "inf_001"],
    "fatos_ref": ["fato_006"]
  }
}
```

### `decisao = sem_angulo`, trilha `COMPLETO_COM_SITE`

```json
{
  "schema_version": "1.0",
  "place_id": "ChIJexemplo22222222222222222",
  "dossie_origem": "dossie_ChIJexemplo22222222222222222_20260908-142800.json",
  "lote_origem": "leads_qualificados_20260908-074342_v1.1.0.json",
  "estagio_analise": "COMPLETO_COM_SITE",
  "diagnosticado_em": "2026-09-08T15:08:00Z",
  "modelo": "claude-sonnet-5",
  "decisao": "sem_angulo",
  "achados": [],
  "angulo_principal": null,
  "sem_angulo": {
    "motivo_categoria": "site_adequado_sem_deficiencia_relevante",
    "motivo_descricao": "O site carrega rápido em mobile e desktop (fato_002, fato_003), expõe telefone/WhatsApp/formulário funcionais e testados (fato_004, fato_005) e não apresenta nenhum problema de conversão, acessibilidade ou performance identificado pela checklist base. Não há deficiência dentro do que vendemos que justifique abordagem no momento.",
    "motivo_crm": "Site já funciona bem — sem abertura clara para nossa oferta no momento.",
    "evidencias_consideradas": ["fato_002", "fato_003", "fato_004", "fato_005"],
    "fatos_ref": []
  }
}
```
