# Schema — Output do Agente 1 (Investigação)

## Descrição

Estrutura do output produzido pelo Agente 1 — Investigação (o "dossiê").
Este output alimenta o Agente 2 (Diagnóstico Comercial) e é o **ground truth** do Agente 4 (Revisor).

O Agente 1 responde **"o que existe?"**. Ele entrega realidade verificada e organizada.
Ele nunca responde "o que disso importa comercialmente?" — isso é do Agente 2.

**Reconciliação (v2.0):** esta versão incorpora a estrutura de evidência de cinco categorias adotada pela direção — não é uma camada colada sobre o schema v1.0, é uma reestruturação. Ver "O que mudou da v1.0" ao final deste documento para o mapa completo de blocos fundidos/renomeados.

## Consumidores

- **Agente 2 — Diagnóstico Comercial** (input principal)
- **Agente 4 — Revisor** (ground truth para validação factual da copy)

## Princípios de construção

1. **Toda afirmação carrega sua evidência.** Não existe campo com conclusão solta.
2. **Ausência de evidência não vira evidência negativa.** O que não foi encontrado vai para `dados_nao_encontrados`, nunca para `fatos_observados`.
3. **O que está bom é reportado com o mesmo peso do que está ruim.** Sem isso o pipeline procura defeito até encontrar.
4. **Consequência observável, não consequência comercial.** "O caminho de contacto retorna erro" — sim. "O negócio está perdendo clientes" — não.
5. **Evidência limpa e rica em vez de classificação.** O schema não pré-digere a decisão; entrega material para o Agente 2 raciocinar.
6. **Fato e inferência nunca se misturam.** Ver a seção seguinte — é a regra mais importante deste documento.

---

## O circuito fechado A1 ↔ A4 — por que fato e inferência são blocos separados

O Agente 1 e o Agente 4 formam um circuito fechado: o A4 usa este dossiê como **ground truth** para decidir se a copy do A3 é factualmente correta. Ele não reinveste a investigação — ele confia no que está aqui.

Se uma **inferência** (uma conclusão do A1, não algo que ele viu diretamente) entrar misturada com **fatos**, o A4 valida uma copy errada com total confiança — porque, do ponto de vista do A4, tudo neste dossiê é "o que foi confirmado". A separação estrutural entre `fatos_observados` e `inferencias` é a única trava contra isso. Não é estilo de escrita, é arquitetura: os dois vivem em blocos diferentes do schema, com regras de validação diferentes, e nenhum mecanismo permite que um `id` de `inferencias` seja citado onde o schema espera um `id` de `fatos_observados` (ver Regras de validação, item 9).

> ## ⚠️ Regra dura — a única que este documento marca como inegociável
>
> **O Agente 4 só aceita, como afirmação factual da copy, o que for rastreável a `fatos_observados`.** Uma inferência do A1 (ou pior, uma suposição do A3) que aparece na copy como se fosse fato confirmado é **FAIL de severidade `critico`** na revisão do A4 ([schemas/04_output_revisao.md](04_output_revisao.md), categoria `factualidade`) — não é um detalhe a ajustar, é motivo de reprovação.

---

## Estrutura

### Raiz

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `schema_version` | string | sim | `"2.0"` |
| `place_id` | string | sim | Identificador do lead, herdado do contrato do QUALIFICADOR (`place_id`) — não "`lead_id`": este dossiê fala o vocabulário do contrato de ponta a ponta |
| `lote_origem` | string | sim | Nome do arquivo de lote do QUALIFICADOR que originou este lead (`leads_qualificados_<timestamp>_v<versão>.json`) — rastreia qual contrato gerou qual dossiê |
| `investigado_em` | string (ISO 8601) | sim | Data/hora UTC em que o dossiê foi gravado pelo `dossie_io.py`, ao fim da investigação. Preenchido pela ferramenta, nunca pelo agente. A hora da coleta do site fica em `gerado_em` dos fatos técnicos citados |
| `modelo` | string | sim | Modelo LLM que produziu este dossiê (`"claude-sonnet-5"` \| `"claude-opus-5"`) — ver [agents/01_investigacao/prompt.md](../agents/01_investigacao/prompt.md), regra de escalonamento (D2) |
| `escalonamento` | object | sim | `{ "ocorreu": bool, "motivo": string \| null }`. `motivo` só é preenchido quando `ocorreu: true`, e só descreve **evidência conflitante que o Sonnet não resolveu** — nunca "faltava informação" (isso vira `dados_nao_encontrados`, não motivo de escalonamento) |
| `status_investigacao` | enum | sim | `completa` \| `parcial` \| `bloqueada` |
| `negocio` | object | sim | Identidade e ficha do negócio |
| `presenca_digital` | object | sim | Resumo de estado, sustentado por `fatos_observados` |
| `fatos_observados` | array | sim | **Bloco central.** O A1 viu isto diretamente — ver definição abaixo |
| `fontes_dos_fatos` | array | sim | De onde veio cada fato — rastreabilidade por fato, não global |
| `inferencias` | array | sim | Conclusões do A1 a partir dos fatos (pode ser `[]`) — nunca fato |
| `incertezas` | array | sim | Sinal ambíguo ou conflitante encontrado (pode ser `[]`) |
| `dados_nao_encontrados` | array | sim | Procurou e não achou — distinto de não ter procurado (pode ser `[]`) |
| `por_dispositivo` | object | sim | Comportamento mobile vs desktop |
| `jornada_principal` | object | sim | Caminho do visitante até o contato |
| `qualificador` | object | sim | Insumos recebidos do QUALIFICADOR e procedência de uso |

`status_investigacao`:
- `completa` — checklist base coberta integralmente
- `parcial` — alguns itens não puderam ser verificados (detalhados em `dados_nao_encontrados`)
- `bloqueada` — site inacessível ou impedimento que inviabiliza a investigação; o Agente 2 recebe o pacote quase vazio, mas sabe o motivo

---

### 1. `negocio` — contexto

Quem está sendo analisado. Vem em grande parte do QUALIFICADOR, mas o Agente 1 **confirma contra o que encontrou** no site e no GBP. É ficha de identidade — dado direto, não passa pelo aparato fato/fonte de `fatos_observados` (identidade não é um "achado", é um cadastro). Quando um campo de identidade é objeto de um achado real (ex.: uma divergência), a divergência em si é registrada tipada abaixo, e pode referenciar um fato/fonte quando fizer sentido.

```json
"negocio": {
  "nome": "Clínica Dental Ficticia",
  "nicho": "Odontologia",
  "localizacao": "Alicante, Espanha",
  "servicos_principais": ["Implantologia", "Ortodontia", "Branqueamento"],
  "website": "https://clinicadentalficticia.es",
  "google_maps_url": "https://maps.google.com/...",
  "rating_coletado": { "valor": 4.9, "estado": "CONFIRMADO_PRESENTE" },
  "total_avaliacoes_coletado": { "valor": 41, "estado": "CONFIRMADO_PRESENTE" },
  "rating_verificado": 4.7,
  "total_avaliacoes_verificado": 412,
  "redes_sociais": {
    "instagram": "https://instagram.com/clinicadentalficticia",
    "facebook": "https://facebook.com/clinicadentalficticia",
    "linkedin": null
  },
  "canais_de_contato": [
    { "tipo": "telefone", "valor": "+34 965 00 00 00", "onde": "header e rodapé" },
    { "tipo": "whatsapp", "valor": "+34 611 00 00 00", "onde": "botão flutuante, apenas desktop" },
    { "tipo": "email", "valor": "geral@clinicadentalficticia.es", "onde": "rodapé" }
  ],
  "divergencias_com_qualificador": [
    {
      "campo": "rating",
      "valor_coletado": { "valor": 4.9, "estado": "CONFIRMADO_PRESENTE" },
      "valor_verificado": 4.7,
      "observacao": "Rating no GBP caiu de 4.9 (coleta do QUALIFICADOR) para 4.7 (verificação ao vivo do A1) — pode indicar avaliações negativas recentes; investigar antes de usar o rating como argumento comercial."
    },
    {
      "campo": "nicho",
      "valor_coletado": "Centro médico",
      "valor_verificado": "Odontologia (clínica exclusivamente dentária)",
      "observacao": "QUALIFICADOR classificou como 'Centro médico'; o site apresenta-se exclusivamente como clínica dentária."
    }
  ]
}
```

**`rating_verificado` / `total_avaliacoes_verificado`** — produzidos pelo Agente 1 na Fase 5 (GBP), ao vivo. É a autoridade sobre o fato. Nullable: quando o GBP está inacessível ou o dado não foi alcançado, ficam `null` e o item correspondente vai para `dados_nao_encontrados` — nunca ficam vazios silenciosamente.

**`rating_coletado` / `total_avaliacoes_coletado`** — eco fiel de `reputacao.nota_google` e `reputacao.review_count` do contrato do QUALIFICADOR ([CONTRACT.md](../../EQC/contracts/CONTRACT.md)), no mesmo formato `{valor, estado}` e com o mesmo vocabulário de estado (`CONFIRMADO_PRESENTE` \| `CONFIRMADO_AUSENTE` \| `NAO_VERIFICADO`). O Agente 1 não reinterpreta nem resume esse par em um booleano ou em `null` — repassa como recebeu. `NAO_VERIFICADO` significa "o QUALIFICADOR não checou"; `CONFIRMADO_AUSENTE` significa "o QUALIFICADOR checou e não há rating".

**Regra de autoridade:** em caso de conflito entre coletado e verificado, **o verificado tem precedência**. O coletado existe para **detectar divergência** — **isso não é erro, é sinal comercial** (uma ficha cujo rating caiu desde a coleta é informação de abordagem) — nunca para ser usado como evidência por si só; um `rating_coletado` nunca entra sozinho em `fatos_observados` ou na copy.

**`divergencias_com_qualificador`** é `[]` quando não há divergência. Cada item é um objeto tipado — `campo`, `valor_coletado`, `valor_verificado`, `observacao` — nunca uma string livre. `valor_coletado` preserva o formato de origem do campo (o par `{valor, estado}` para campos que vêm assim do contrato, texto simples para os que não vêm, como `nicho`). **Regra de validação 11** exige esta entrada sempre que coletado e verificado divergirem e ambos estiverem presentes — ver abaixo.

---

### 2. `presenca_digital` — retrato objetivo

Permite ao Agente 2 entender **maturidade digital**, não apenas encontrar bugs. É uma síntese — cada valor é derivado de um ou mais `fatos_observados` (às vezes cruzando vários, o que é uma forma leve de inferência estrutural, mas confinada a este resumo de estado fixo, não uma inferência livre).

```json
"presenca_digital": {
  "website": "parcialmente_funcional",
  "mobile": "problematico",
  "desktop": "adequado",
  "https": true,
  "gbp": "ativo_incompleto",
  "caminho_para_contato": "quebrado",
  "carregamento_percebido": "lento"
}
```

| Campo | Valores |
|---|---|
| `website` | `funcional` \| `parcialmente_funcional` \| `inacessivel` |
| `mobile` / `desktop` | `adequado` \| `problematico` \| `nao_testado` |
| `https` | `true` \| `false` \| `null` (não verificado) |
| `gbp` | `ativo_completo` \| `ativo_incompleto` \| `inexistente` \| `nao_verificado` |
| `caminho_para_contato` | `claro` \| `confuso` \| `quebrado` \| `inexistente` |
| `carregamento_percebido` | `rapido` \| `medio` \| `lento` \| `nao_avaliado` — deriva de `lead["psi"]` quando `CONFIRMADO_PRESENTE` (ver [referencias/insumos_sistema_qualificacao.md](../referencias/insumos_sistema_qualificacao.md), seção "`psi`"); `nao_avaliado` quando `psi` é `NAO_VERIFICADO` — nunca inferir "rápido" ou "lento" na ausência de medição |

Cada valor precisa ser sustentado por pelo menos um `fato_observado` — não pode existir isoladamente (Regra de validação 5).

---

### 3. `fatos_observados` — o A1 viu isto diretamente

**O bloco central.** Único material que o Agente 3 pode afirmar na copy e que o Agente 4 aceita como base (ver "O circuito fechado A1 ↔ A4" acima). Fusão dos antigos blocos `observacoes` (fatos/problemas/pontos fortes) e `sinais_maturidade_digital` da v1.0 — ver "O que mudou da v1.0".

```json
{
  "id": "fato_004",
  "categoria": "conversao",
  "natureza": "problema",
  "afirmacao": "O formulário da página /contacto retorna erro após o envio.",
  "dispositivo": "ambos",
  "confianca": "alta",
  "fontes_ref": ["fonte_004"],
  "consequencia_observavel": "Não existe confirmação de que a mensagem chegue ao negócio; quem usa este caminho fica sem retorno."
}
```

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | string | sim | `fato_001`, `fato_002`… Referenciável pelos outros blocos |
| `categoria` | enum | sim | ver lista abaixo |
| `natureza` | enum | sim | `problema` \| `ponto_forte` \| `neutro` |
| `afirmacao` | string | sim | O fato, em uma frase. Descritivo, sem adjetivo comercial |
| `dispositivo` | enum | sim | `mobile` \| `desktop` \| `ambos` \| `nao_aplicavel` |
| `confianca` | enum | sim | `alta` \| `media` — grau de certeza sobre a leitura do que foi observado, nunca sobre se o fato é real. Nunca `baixa` (regra 3) |
| `fontes_ref` | array de string | sim | **≥ 1** id de `fontes_dos_fatos` (Regra de validação 1). Um fato sem fonte rastreável não entra aqui |
| `consequencia_observavel` | string | condicional | **Apenas** quando `natureza = problema` |

**Categorias:** `acessibilidade`, `identidade_negocio`, `conversao`, `contato`, `mobile`, `performance`, `gbp`, `conteudo`, `seo_local`, `maturidade_digital` (nova — absorve os antigos "sinais crus" de redes sociais/atualidade de conteúdo).

**Sobre `consequencia_observavel`:** descreve o que acontece com quem navega, verificável por observação. Não descreve efeito comercial, volume perdido ou intenção.

- ✅ "O botão de WhatsApp não aparece em telas abaixo de 768px."
- ❌ "O negócio perde clientes por causa disto."

**Sobre pontos fortes:** têm o mesmo rigor de evidência dos problemas. Um dossiê sem nenhum `ponto_forte` num site que carrega e funciona é um dossiê incompleto.

**Sobre `maturidade_digital`:** um sinal cru continua sendo um **fato** — "Instagram com publicação há 7 dias" é algo que o A1 viu, não uma conclusão. O cruzamento entre sinais ("negócio consolidado, redes ativas, site desatualizado, logo provavelmente...") é que vira `inferencia`, nunca fica misturado aqui.

---

### 4. `fontes_dos_fatos` — de onde veio cada fato

Rastreabilidade **por fato**, não um `fonte: "..."` genérico solto no topo do dossiê. Uma fonte pode sustentar mais de um fato (ex.: um único screenshot evidenciando três achados); um fato pode ter mais de uma fonte (verificado em dois lugares). A ligação é sempre via `id`, nunca duplicando texto.

```json
{
  "id": "fonte_004",
  "tipo": "url",
  "local": "https://clinicadentalficticia.es/contacto",
  "como_verificado": "Inspeção estrutural do formulário (campos, action) e verificação HTTP do endpoint de destino, sem submissão de dados. Endpoint retornou 404."
}
```

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | string | sim | `fonte_001`, `fonte_002`… |
| `tipo` | enum | sim | `url` \| `elemento_dom` \| `campo_contrato` \| `screenshot` \| `gbp` \| `ferramenta_fetch_tecnico` |
| `local` | string | sim | URL exata, seletor/elemento, nome do campo do contrato (ex.: `reputacao.nota_google`), caminho do screenshot, ou `"Google Business Profile"` |
| `como_verificado` | string | sim | A ação executada para verificar, incluindo o que foi concretamente observado (texto livre — substitui os antigos `evidencia` + `como_verificado` separados da v1.0, fundidos aqui) |

`tipo: ferramenta_fetch_tecnico` é usado quando o fato vem do retorno estruturado de `ferramentas/fetch_tecnico.py` (ver [agents/01_investigacao/prompt.md](../agents/01_investigacao/prompt.md)) — `local` aponta para o campo do JSON de retorno (ex.: `por_dispositivo.mobile.has_whatsapp_link`).

---

### 5. `inferencias` — conclusões do A1, nunca fato

Toda entrada aqui é uma leitura que o A1 fez **a partir de** fatos — não algo que ele observou diretamente. Orienta o diagnóstico do A2. **Nunca pode virar afirmação factual na copy** — ver a Regra dura no topo deste documento.

```json
{
  "id": "inf_001",
  "afirmacao": "O negócio parece ter recomeçado a investir em presença digital recentemente, sem ainda atualizar o site.",
  "baseada_em": ["fato_007", "fato_009"],
  "confianca": "media"
}
```

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | string | sim | `inf_001`, `inf_002`… |
| `afirmacao` | string | sim | A conclusão, em uma frase |
| `baseada_em` | array de string | sim | **≥ 1** id de `fatos_observados` (Regra de validação 10) — uma inferência sem fato de apoio é opinião, não pertence ao dossiê |
| `confianca` | enum | sim | `alta` \| `media`. Nunca `baixa` — se a confiança na inferência é baixa, ela pertence a `incertezas`, não aqui |

Pode ser `[]`. Nem todo dossiê tem uma leitura cruzada que valha a pena registrar — inventar uma inferência para preencher o bloco é exatamente o que a Regra dura existe para prevenir.

---

### 6. `incertezas` — sinal ambíguo ou conflitante

Distinto de `inferencias` (que é uma conclusão, ainda que com confiança média) e de `dados_nao_encontrados` (que é ausência). Aqui o A1 encontrou **algo**, mas esse algo não fecha — duas fontes discordam, ou o comportamento observado não é claramente interpretável.

```json
{
  "id": "inc_001",
  "descricao": "O telefone exibido no rodapé do site (965 00 00 01) difere do telefone no Google Business Profile (965 00 00 00).",
  "sinais_conflitantes": ["fato_005", "fato_008"],
  "impacto_na_analise": "Não é possível afirmar qual número está correto sem contato direto; ambos podem estar ativos (linhas diferentes) ou um estar desatualizado."
}
```

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | string | sim | `inc_001`, `inc_002`… |
| `descricao` | string | sim | O que está ambíguo ou conflitante |
| `sinais_conflitantes` | array de string | condicional | ids de `fatos_observados` envolvidos, quando o conflito é entre fatos já registrados |
| `impacto_na_analise` | string | sim | O que essa ambiguidade impede de concluir |

Pode ser `[]`.

---

### 7. `dados_nao_encontrados` — procurou e não achou

Distinto de `fatos_observados` por design, e distinto de simplesmente "não procurou" — todo item aqui reflete uma tentativa real. Impede que ausência de evidência vire evidência negativa. (Era `nao_confirmado` na v1.0 — mesma função, nome alinhado à taxonomia nova.)

```json
[
  {
    "item": "Se o formulário efetivamente entrega a mensagem quando enviado por um visitante real",
    "motivo": "Política do A1 é não submeter formulários reais (evita gerar contato falso no negócio); o endpoint quebrado já é evidência suficiente de falha, mas o comportamento em uso real não é testado.",
    "tentativas": "Verificação do endpoint em duas ocasiões, mesmo resultado.",
    "impacto_na_analise": "Confirmado que o envio falha; não é possível afirmar se alguma mensagem chega."
  },
  {
    "item": "Horários de atendimento no site",
    "motivo": "Não localizados em nenhuma página navegada.",
    "tentativas": "Homepage, /contacto, rodapé e menu principal.",
    "impacto_na_analise": "Ausência não confirmada — pode existir em página não alcançada pela navegação."
  }
]
```

Todos os quatro campos (`item`, `motivo`, `tentativas`, `impacto_na_analise`) são obrigatórios. `impacto_na_analise` é o que impede o Agente 2 de tratar a lacuna como problema.

**Não confundir com `NAO_VERIFICADO` do contrato:** quando o QUALIFICADOR já declara um campo como `NAO_VERIFICADO` (ex.: `contato.linkedin`, `psi`), isso é um **fato sobre o que o QUALIFICADOR entregou** — vai para `negocio`/`qualificador` como está, ecoado com seu `{valor, estado}` ou tratado conforme [referencias/insumos_sistema_qualificacao.md](../referencias/insumos_sistema_qualificacao.md). `dados_nao_encontrados` é especificamente sobre a **própria investigação ao vivo do A1** não ter alcançado algo — as duas lacunas nunca se misturam.

---

### 8. `por_dispositivo` — comportamento separado

Não fica diluído no relatório geral, porque a diferença entre dispositivos costuma ser o achado mais relevante.

```json
"por_dispositivo": {
  "mobile": {
    "funcionamento": "Navegação e leitura funcionam, mas o principal caminho de contacto não está disponível.",
    "fatos_ref": ["fato_003", "fato_004", "fato_006"]
  },
  "desktop": {
    "funcionamento": "Navegação, conteúdo e canais de contacto funcionam conforme esperado, exceto o envio do formulário.",
    "fatos_ref": ["fato_004", "fato_005"]
  }
}
```

`fatos_ref` aponta para ids de `fatos_observados` — sem duplicar texto, e **nunca** para um id de `inferencias` (Regra de validação 9). `funcionamento` é a síntese descritiva do comportamento naquele dispositivo.

---

### 9. `jornada_principal` — o site como sistema comercial

O caminho real do visitante até o contato, testado ponta a ponta.

```json
"jornada_principal": {
  "entrada": "https://clinicadentalficticia.es",
  "etapas": [
    { "etapa": "Homepage apresenta a proposta da clínica", "resultado": "ok", "fato_ref": "fato_001" },
    { "etapa": "Serviço 'Implantologia' localizado no menu", "resultado": "ok", "fato_ref": "fato_002" },
    { "etapa": "CTA 'Marcar consulta' leva a /contacto", "resultado": "ok", "fato_ref": null },
    { "etapa": "Envio do formulário de marcação", "resultado": "falha", "fato_ref": "fato_004" }
  ],
  "resultado": "interrompida",
  "onde_interrompeu": "Envio do formulário — última etapa do único caminho de marcação no mobile.",
  "caminhos_alternativos": [
    { "canal": "telefone", "disponivel": true, "fato_ref": "fato_005" },
    { "canal": "whatsapp", "disponivel": false, "fato_ref": "fato_003" }
  ]
}
```

- `resultado`: `completa` \| `interrompida` \| `nao_testavel`
- `caminhos_alternativos` importa: uma jornada interrompida com telefone visível e funcional é uma realidade diferente de uma sem nenhuma saída.

---

### 10. `qualificador` — insumos e procedência

Conforme [referencias/insumos_sistema_qualificacao.md](../referencias/insumos_sistema_qualificacao.md) e [CONTRACT.md](../../EQC/contracts/CONTRACT.md).

```json
"qualificador": {
  "sinais_recebidos": {
    "estagio_analise": "COMPLETO_COM_SITE",
    "evidencias_qualificador": {
      "fatos": ["meta description ausente no HTML", "atributo lang no HTML: es"]
    },
    "priorizacao_nao_autoritativa": {
      "commercial_fit_score": 62,
      "priority_label": "media",
      "reasons": ["reputação: 4.9 estrelas com 41 avaliações", "meta description ausente — vale investigar SEO"]
    }
  },
  "procedencia": [
    {
      "origem": "qualificador",
      "insumo_usado": "priorizacao.priority_label = media",
      "o_que_foi_investigado": "Performance mobile e desktop, estrutura das páginas principais",
      "o_que_foi_encontrado": "Carregamento lento confirmado no mobile; desktop dentro do normal",
      "relevancia_comercial": "sim",
      "fatos_ref": ["fato_006"]
    },
    {
      "origem": "investigacao_base",
      "insumo_usado": null,
      "o_que_foi_investigado": "Checklist base — funcionamento do CTA principal",
      "o_que_foi_encontrado": "Formulário de contacto retorna erro no envio — não sinalizado pelo QUALIFICADOR",
      "relevancia_comercial": "sim",
      "fatos_ref": ["fato_004"]
    }
  ]
}
```

**`sinais_recebidos.priorizacao_nao_autoritativa`** carrega o mesmo aviso do bloco `priorizacao` do contrato de entrada — o nome viaja junto com o dado atravessando a fronteira entre o COMERCIAL e o Agente 2. Chega aqui **só para rastreamento** (medir se o sinal do QUALIFICADOR se confirmou na investigação), nunca como insumo de julgamento.

**Duas formas, uma por trilha (correção pós-piloto):** o contrato v1.1.0 tem duas trilhas com vocabulários de `priorizacao` distintos (ver [referencias/insumos_sistema_qualificacao.md](../referencias/insumos_sistema_qualificacao.md)), e este bloco precisa refletir a trilha real do lead — não só a de `COMPLETO_COM_SITE`, que era a única representada até esta correção.

| `estagio_analise` | Forma de `priorizacao_nao_autoritativa` |
|---|---|
| `COMPLETO_SEM_SITE` (Onda 1) | `{ commercial_fit_score, reasons, priority, contactability, risks }` |
| `COMPLETO_COM_SITE` (Onda 2) | `{ commercial_fit_score, reasons, priority_label }` |

O schema formal (`priorizacao_onda1` / `priorizacao_onda2` em [01_output_investigacao.schema.json](01_output_investigacao.schema.json)) amarra a forma ao `estagio_analise` do próprio dossiê — um dossiê `COMPLETO_SEM_SITE` com a forma de Onda 2 (ou vice-versa) é output inválido. Antes desta correção, um lead `COMPLETO_SEM_SITE` perdia `priority`/`contactability`/`risks` silenciosamente (não havia campo para eles); isso forçava o A1 a improvisar, citando o dado em texto livre dentro de `qualificador.procedencia[].insumo_usado` — deixou de ser necessário.

Exemplo para uma trilha `COMPLETO_SEM_SITE`:

```json
"priorizacao_nao_autoritativa": {
  "commercial_fit_score": 58,
  "reasons": ["sem site — oportunidade de presença digital do zero", "ficha do Google ativa e com avaliações"],
  "priority": "alta",
  "contactability": "media",
  "risks": ["nicho muito competitivo na região"]
}
```

- `origem`: `qualificador` \| `investigacao_base`
- `relevancia_comercial`: `sim` \| `nao` \| `n/a`
- Achados da investigação base que o QUALIFICADOR não sinalizou **devem** ser registrados com `origem: investigacao_base`.
- `fatos_ref` (renomeado de `observacoes_ref` na v1.0) — mesma regra: nunca aponta para `inferencias`.

---

## Formato

**JSON** como formato canônico. É o que o Agente 2 consome. Persistido em disco conforme [agents/01_investigacao/prompt.md](../agents/01_investigacao/prompt.md), seção "Saída em disco".

---

## Regras de validação

1. Toda entrada em `fatos_observados` tem `fontes_ref` com pelo menos um id, e todo id referenciado existe em `fontes_dos_fatos`.
2. `consequencia_observavel` existe **se e somente se** `natureza = problema` (em `fatos_observados`).
3. `confianca` nunca é `baixa` — nem em `fatos_observados`, nem em `inferencias`. Item de baixa confiança pertence a `dados_nao_encontrados` (fato) ou `incertezas` (inferência/leitura).
4. **Todo item da checklist base** ([referencias/insumos_sistema_qualificacao.md](../referencias/insumos_sistema_qualificacao.md)) aparece em `fatos_observados` **ou** em `dados_nao_encontrados`. Um item da base ausente dos dois é output inválido.
5. Todo valor em `presenca_digital` é sustentado por ao menos um `fato_observado`.
6. Todo campo `*_ref` (`fontes_ref`, `fatos_ref`, `fato_ref`, `baseada_em`, `sinais_conflitantes`) aponta para um `id` existente **no bloco correto**.
7. `procedencia` contém uma entrada para cada sinal do QUALIFICADOR recebido, mesmo quando o sinal não gerou investigação específica (`relevancia_comercial: "n/a"`).
8. Nenhum campo contém linguagem comercial, projeção ou recomendação de abordagem.
9. **Nenhum campo `*_ref` fora de `inferencias.baseada_em` e `incertezas.sinais_conflitantes` pode apontar para um id de `inferencias`.** `por_dispositivo.fatos_ref`, `jornada_principal[].fato_ref` e `qualificador.procedencia[].fatos_ref` só apontam para `fatos_observados`. Esta é a trava estrutural da Regra dura (ver "O circuito fechado A1 ↔ A4").
10. Toda `inferencia` tem `baseada_em` com pelo menos um id de `fatos_observados`.
11. Quando `negocio.rating_coletado.valor` e `negocio.rating_verificado` estão ambos presentes (não `null`) e divergem — ou o mesmo para `total_avaliacoes_*` —, deve existir uma entrada correspondente em `negocio.divergencias_com_qualificador` com o `campo` respectivo.
12. `place_id` do dossiê é idêntico ao `place_id` do lead de origem no `lote_origem`.
13. A forma de `qualificador.sinais_recebidos.priorizacao_nao_autoritativa` corresponde à trilha de `estagio_analise` (ver tabela na seção 10) — checado estruturalmente pelo schema formal (`oneOf` + `allOf`/`if`/`then`), não precisa de checagem adicional em código.

---

## Fora de escopo — o que este output NÃO contém

Campos que **não existem** neste schema, por pertencerem a outros agentes:

| Campo proibido | Agente responsável |
|---|---|
| `angulo_comercial` | Agente 2 |
| `lead_deve_ser_abordado` | Agente 2 |
| `oportunidade` / `potencial` | Agente 2 |
| `argumento` / `pitch` | Agente 3 |
| `score` / `nota` do lead | Agente 2 |
| Qualquer projeção ("perde X clientes", "poderia aumentar Y") | nenhum — não é verificável |

Se o Agente 1 sente necessidade de preencher algo assim, o campo certo é `consequencia_observavel` — descrevendo o que acontece, não o que significa. Se é uma leitura cruzada legítima, o campo certo é `inferencias` — nunca `fatos_observados`.

---

## Exemplo

Dossiê completo e internamente consistente — todos os `*_ref` deste exemplo resolvem para um `id` real dentro dele.

```json
{
  "schema_version": "2.0",
  "place_id": "ChIJexemplo00000000000000000",
  "lote_origem": "leads_qualificados_20260908-074342_v1.1.0.json",
  "investigado_em": "2026-09-08T14:22:00Z",
  "modelo": "claude-sonnet-5",
  "escalonamento": { "ocorreu": false, "motivo": null },
  "status_investigacao": "parcial",

  "negocio": {
    "nome": "Clínica Dental Ficticia",
    "nicho": "Odontologia",
    "localizacao": "Alicante, Espanha",
    "servicos_principais": ["Implantologia", "Ortodontia", "Branqueamento"],
    "website": "https://clinicadentalficticia.es",
    "google_maps_url": "https://maps.google.com/?cid=123456789",
    "rating_coletado": { "valor": 4.9, "estado": "CONFIRMADO_PRESENTE" },
    "total_avaliacoes_coletado": { "valor": 41, "estado": "CONFIRMADO_PRESENTE" },
    "rating_verificado": 4.7,
    "total_avaliacoes_verificado": 412,
    "redes_sociais": {
      "instagram": "https://instagram.com/clinicadentalficticia",
      "facebook": "https://facebook.com/clinicadentalficticia",
      "linkedin": null
    },
    "canais_de_contato": [
      { "tipo": "telefone", "valor": "+34 965 00 00 00", "onde": "header e rodapé" },
      { "tipo": "email", "valor": "geral@clinicadentalficticia.es", "onde": "rodapé" }
    ],
    "divergencias_com_qualificador": [
      {
        "campo": "rating",
        "valor_coletado": { "valor": 4.9, "estado": "CONFIRMADO_PRESENTE" },
        "valor_verificado": 4.7,
        "observacao": "Rating no GBP caiu de 4.9 (coleta do QUALIFICADOR) para 4.7 (verificação ao vivo do A1) — pode indicar avaliações negativas recentes; investigar antes de usar o rating como argumento comercial."
      },
      {
        "campo": "nicho",
        "valor_coletado": "Centro médico",
        "valor_verificado": "Odontologia (clínica exclusivamente dentária)",
        "observacao": "QUALIFICADOR classificou como 'Centro médico'; o site apresenta-se exclusivamente como clínica dentária."
      }
    ]
  },

  "presenca_digital": {
    "website": "parcialmente_funcional",
    "mobile": "problematico",
    "desktop": "adequado",
    "https": true,
    "gbp": "ativo_incompleto",
    "caminho_para_contato": "quebrado",
    "carregamento_percebido": "lento"
  },

  "fatos_observados": [
    {
      "id": "fato_001", "categoria": "identidade_negocio", "natureza": "ponto_forte",
      "afirmacao": "A homepage apresenta com clareza que se trata de uma clínica dentária e lista os serviços oferecidos.",
      "dispositivo": "ambos", "confianca": "alta", "fontes_ref": ["fonte_001"]
    },
    {
      "id": "fato_002", "categoria": "conteudo", "natureza": "neutro",
      "afirmacao": "Cada serviço principal tem uma página dedicada acessível pelo menu.",
      "dispositivo": "ambos", "confianca": "alta", "fontes_ref": ["fonte_002"]
    },
    {
      "id": "fato_003", "categoria": "mobile", "natureza": "problema",
      "afirmacao": "O botão de WhatsApp não é exibido na versão mobile do site.",
      "dispositivo": "mobile", "confianca": "alta", "fontes_ref": ["fonte_003"],
      "consequencia_observavel": "No mobile, o WhatsApp não está disponível como caminho de contacto; resta o telefone e o formulário."
    },
    {
      "id": "fato_004", "categoria": "conversao", "natureza": "problema",
      "afirmacao": "O formulário da página /contacto retorna erro após o envio.",
      "dispositivo": "ambos", "confianca": "alta", "fontes_ref": ["fonte_004"],
      "consequencia_observavel": "Não existe confirmação de que a mensagem chegue ao negócio; quem usa este caminho fica sem retorno."
    },
    {
      "id": "fato_005", "categoria": "contato", "natureza": "ponto_forte",
      "afirmacao": "O telefone está visível no header e no rodapé do site, e é clicável no mobile.",
      "dispositivo": "ambos", "confianca": "alta", "fontes_ref": ["fonte_005"]
    },
    {
      "id": "fato_006", "categoria": "performance", "natureza": "problema",
      "afirmacao": "No mobile, a página principal permanece visualmente incompleta por cerca de 6 segundos.",
      "dispositivo": "mobile", "confianca": "alta", "fontes_ref": ["fonte_006"],
      "consequencia_observavel": "Nos primeiros segundos no mobile a página não mostra o que a clínica oferece."
    },
    {
      "id": "fato_007", "categoria": "gbp", "natureza": "problema",
      "afirmacao": "O Google Business Profile tem 3 fotos, a mais recente de 2021, e nenhuma publicação.",
      "dispositivo": "nao_aplicavel", "confianca": "alta", "fontes_ref": ["fonte_007"],
      "consequencia_observavel": "O perfil não apresenta conteúdo visual recente da clínica."
    },
    {
      "id": "fato_008", "categoria": "contato", "natureza": "neutro",
      "afirmacao": "O Google Business Profile lista um telefone (+34 965 00 00 01) diferente do telefone do site (+34 965 00 00 00).",
      "dispositivo": "nao_aplicavel", "confianca": "alta", "fontes_ref": ["fonte_008"]
    },
    {
      "id": "fato_009", "categoria": "maturidade_digital", "natureza": "neutro",
      "afirmacao": "O Instagram do negócio tem publicação nos últimos 7 dias.",
      "dispositivo": "nao_aplicavel", "confianca": "alta", "fontes_ref": ["fonte_009"]
    }
  ],

  "fontes_dos_fatos": [
    { "id": "fonte_001", "tipo": "url", "local": "https://clinicadentalficticia.es", "como_verificado": "Leitura da homepage. Título 'Clínica Dental Ficticia — Implantologia e Ortodontia' visível sem rolagem, seguido de secção com os três serviços." },
    { "id": "fonte_002", "tipo": "url", "local": "https://clinicadentalficticia.es", "como_verificado": "Navegação pelo menu e abertura de cada página de serviço; cada uma tem descrição própria." },
    { "id": "fonte_003", "tipo": "elemento_dom", "local": "botão flutuante de WhatsApp (presente no desktop)", "como_verificado": "Navegação em viewport mobile (390px) nas páginas home, serviços e contacto — botão ausente; nenhum outro link de WhatsApp encontrado." },
    { "id": "fonte_004", "tipo": "ferramenta_fetch_tecnico", "local": "por_dispositivo.desktop.form_action", "como_verificado": "fetch_tecnico.py: endpoint de destino do formulário (action=/enviar-contacto) retorna 404 em requisição HEAD/GET de verificação, sem submissão de dados. Estrutura do formulário íntegra." },
    { "id": "fonte_005", "tipo": "elemento_dom", "local": "link tel: no header e rodapé", "como_verificado": "Inspeção visual e toque no link em viewport mobile — abre o discador." },
    { "id": "fonte_006", "tipo": "screenshot", "local": "screenshots/ChIJexemplo_mobile.png", "como_verificado": "Observação do carregamento da homepage em viewport mobile, três repetições — imagem de destaque e bloco de serviços aparecem em etapas, estabilizando por volta de 6s." },
    { "id": "fonte_007", "tipo": "gbp", "local": "Google Business Profile", "como_verificado": "Consulta ao perfil pelo google_maps_url recebido — secção de fotos com três imagens de 2021 ou anterior; aba de publicações vazia." },
    { "id": "fonte_008", "tipo": "gbp", "local": "Google Business Profile", "como_verificado": "Telefone listado no card do perfil, comparado ao telefone lido no rodapé do site." },
    { "id": "fonte_009", "tipo": "url", "local": "https://instagram.com/clinicadentalficticia", "como_verificado": "Leitura do perfil público — data da publicação mais recente." }
  ],

  "inferencias": [
    {
      "id": "inf_001",
      "afirmacao": "O negócio parece manter alguma atividade em redes sociais, mas não replica isso no Google Business Profile.",
      "baseada_em": ["fato_007", "fato_009"],
      "confianca": "media"
    }
  ],

  "incertezas": [
    {
      "id": "inc_001",
      "descricao": "O telefone exibido no rodapé do site (965 00 00 00) difere do telefone no Google Business Profile (965 00 00 01).",
      "sinais_conflitantes": ["fato_005", "fato_008"],
      "impacto_na_analise": "Não é possível afirmar qual número está correto sem contato direto; ambos podem estar ativos (linhas diferentes) ou um estar desatualizado."
    }
  ],

  "dados_nao_encontrados": [
    {
      "item": "Se o formulário efetivamente entrega a mensagem ao destinatário quando enviado por um visitante real",
      "motivo": "Política do A1 é não submeter formulários reais (evita gerar contato falso no negócio); o endpoint quebrado já é evidência suficiente de falha, mas o comportamento em uso real não é testado.",
      "tentativas": "Verificação do endpoint em duas ocasiões, mesmo resultado.",
      "impacto_na_analise": "Confirmado que o envio falha; não é possível afirmar se alguma mensagem chega."
    },
    {
      "item": "Horários de atendimento no site",
      "motivo": "Não localizados em nenhuma página navegada.",
      "tentativas": "Homepage, /contacto, páginas de serviço, rodapé e menu.",
      "impacto_na_analise": "Ausência não confirmada — podem existir em página não alcançada. No GBP os horários estão presentes e corretos."
    }
  ],

  "por_dispositivo": {
    "mobile": {
      "funcionamento": "Navegação e leitura funcionam. O carregamento inicial é lento e o WhatsApp não está disponível, restando telefone e formulário como caminhos de contacto.",
      "fatos_ref": ["fato_003", "fato_004", "fato_006"]
    },
    "desktop": {
      "funcionamento": "Navegação, conteúdo e telefone funcionam conforme esperado. O envio do formulário falha.",
      "fatos_ref": ["fato_004", "fato_005"]
    }
  },

  "jornada_principal": {
    "entrada": "https://clinicadentalficticia.es",
    "etapas": [
      { "etapa": "Homepage apresenta a proposta da clínica", "resultado": "ok", "fato_ref": "fato_001" },
      { "etapa": "Serviço localizado pelo menu", "resultado": "ok", "fato_ref": "fato_002" },
      { "etapa": "CTA 'Marcar consulta' leva a /contacto", "resultado": "ok", "fato_ref": null },
      { "etapa": "Envio do formulário de marcação", "resultado": "falha", "fato_ref": "fato_004" }
    ],
    "resultado": "interrompida",
    "onde_interrompeu": "Envio do formulário — última etapa do caminho iniciado pelo CTA principal.",
    "caminhos_alternativos": [
      { "canal": "telefone", "disponivel": true, "fato_ref": "fato_005" },
      { "canal": "whatsapp", "disponivel": false, "fato_ref": "fato_003" }
    ]
  },

  "qualificador": {
    "sinais_recebidos": {
      "estagio_analise": "COMPLETO_COM_SITE",
      "evidencias_qualificador": {
        "fatos": ["meta description ausente no HTML", "atributo lang no HTML: es"]
      },
      "priorizacao_nao_autoritativa": {
        "commercial_fit_score": 62,
        "priority_label": "media",
        "reasons": ["reputação: 4.9 estrelas com 41 avaliações", "meta description ausente — vale investigar SEO"]
      }
    },
    "procedencia": [
      {
        "origem": "qualificador",
        "insumo_usado": "priorizacao.priority_label = media",
        "o_que_foi_investigado": "Performance e estrutura no mobile e desktop",
        "o_que_foi_encontrado": "Carregamento lento confirmado no mobile; desktop dentro do normal",
        "relevancia_comercial": "sim",
        "fatos_ref": ["fato_006"]
      },
      {
        "origem": "qualificador",
        "insumo_usado": "priorizacao.commercial_fit_score = 62",
        "o_que_foi_investigado": "Contexto geral do negócio",
        "o_que_foi_encontrado": "n/a — usado apenas como contexto",
        "relevancia_comercial": "n/a",
        "fatos_ref": []
      },
      {
        "origem": "qualificador",
        "insumo_usado": "evidencias_qualificador.fatos: meta description ausente no HTML",
        "o_que_foi_investigado": "Confirmação da categoria e SEO on-page no site e no GBP",
        "o_que_foi_encontrado": "Divergência de nicho — clínica exclusivamente dentária; meta description de fato ausente",
        "relevancia_comercial": "sim",
        "fatos_ref": ["fato_001"]
      },
      {
        "origem": "investigacao_base",
        "insumo_usado": null,
        "o_que_foi_investigado": "Checklist base — funcionamento do CTA principal",
        "o_que_foi_encontrado": "Formulário de contacto retorna erro no envio — não sinalizado pelo QUALIFICADOR",
        "relevancia_comercial": "sim",
        "fatos_ref": ["fato_004"]
      },
      {
        "origem": "investigacao_base",
        "insumo_usado": null,
        "o_que_foi_investigado": "Checklist base — canais de contacto visíveis no mobile",
        "o_que_foi_encontrado": "WhatsApp ausente no mobile — não sinalizado pelo QUALIFICADOR",
        "relevancia_comercial": "sim",
        "fatos_ref": ["fato_003"]
      }
    ]
  }
}
```

---

## O que mudou da v1.0 — mapa de reconciliação

| Bloco/campo v1.0 | Destino na v2.0 | Motivo |
|---|---|---|
| `observacoes` (fatos/problemas/pontos fortes, com `evidencia`+`como_verificado`+`fonte` embutidos) | **Fundido** em `fatos_observados` (o quê) + `fontes_dos_fatos` (de onde) | Rastreabilidade por fato deixa de ser um campo de texto solto (`fonte`) e vira uma entidade própria, reutilizável entre fatos e com tipo estruturado |
| `sinais_maturidade_digital` | **Fundido** em `fatos_observados` (categoria `maturidade_digital`) | Um sinal cru é um fato como outro qualquer; a diferença nunca esteve no dado, estava em não deixar alguém interpretá-lo — isso agora é reforçado pela separação `fatos_observados` vs. `inferencias`, não por um bloco à parte |
| `nao_confirmado` | **Renomeado** para `dados_nao_encontrados` | Mesma função exata; nome alinhado à taxonomia de cinco categorias |
| `sistema_1` (nome) | já renomeado para `qualificador` em round anterior (D7) — mantido | — |
| *(nada na v1.0)* | `inferencias` — **novo** | A v1.0 proibia o A1 de interpretar ("isso é leitura do Agente 2"). A direção decidiu que o A1 pode registrar conclusões próprias, desde que isoladas e nunca citáveis como fato — mudança de mandato, não só de schema. Ver nota abaixo |
| *(nada na v1.0)* | `incertezas` — **novo** | Categoria sem equivalente anterior: sinal ambíguo/conflitante que não é nem fato fechado nem lacuna |
| `negocio`, `presenca_digital`, `por_dispositivo`, `jornada_principal`, `qualificador` | **Mantidos**, campos `*_ref` repontados para `fatos_observados` (renomeados `fatos_ref`/`fato_ref` onde antes eram `observacoes_ref`/`observacao_ref`) | Estruturas de resumo/visão que já eram distintas da evidência bruta — permanecem distintas na v2.0 |

**Nota sobre `inferencias` e o mandato do A1:** a v1.0 do [agents/01_investigacao/agent.md](../agents/01_investigacao/agent.md) afirma em mais de um lugar que o A1 não interpreta ("O cruzamento... é leitura do Agente 2"). A introdução de `inferencias` **relaxa** essa proibição — o A1 agora pode registrar uma leitura cruzada própria, desde que isolada em bloco próprio, apoiada em fatos (`baseada_em`) e nunca citável como fato por outro bloco. Isso é uma mudança de mandato do agente, não só de formato de saída — registrado aqui para quem for revisar `agent.md` em seguida; não editei o "porquê" arquitetural em `agent.md` nesta rodada porque o escopo desta tarefa foi o schema, mas a contradição textual existe até esse arquivo ser revisitado.
