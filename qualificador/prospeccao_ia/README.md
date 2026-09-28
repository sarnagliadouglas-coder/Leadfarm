# prospeccao_ia — porta de entrada

> **Auditoria (2026-09-05).** Este README e a pasta [`docs/`](docs/) são uma **documentação-base
> reconstruída a partir do código**, não a especificação original. Onde a conclusão não é
> sustentada diretamente por evidência, está marcada `INFERÊNCIA — CONFIRMAR` ou
> `NÃO DETERMINADO`. Nenhum código, config, schema ou comportamento foi alterado nesta etapa.

## O que este projeto é (em uma frase)

Um **pré-processador determinístico de leads**, custo ≈ $0, que lê um CSV de negócios
extraído do Google Maps, limpa / deduplica / filtra / classifica / pontua cada lead **sem
nenhum julgamento de LLM**, e emite um único arquivo `leads_qualificados_<data>-<hora>_v<contract_version>.json`
(+ sidecar `.meta.json`) para consumo por máquina, em `QUALIFICADOR_OUTPUT_DIR`.

## ⚠️ Conflito de nomenclatura (ler antes de tudo)

| Fonte | Como chama este projeto |
|---|---|
| Tarefa / pasta do usuário (histórico) | **"Sistema 2"** |
| [`SISTEMA.md`](SISTEMA.md) e todos os comentários no código | antes **"Sistema 1"**, agora **"QUALIFICADOR"** |

Nome funcional deste projeto: **QUALIFICADOR**. No código, **"Sistema 2" é um sistema multiagente SEPARADO** (Investigação → Diagnóstico
Comercial → Copywriter → Revisor) que **consome** o `leads_saida.json` produzido aqui e faz
todo o julgamento comercial e toda a geração de copy. Este repositório **não contém** esse
sistema multiagente.

Ou seja: relativo ao código, **este projeto é o estágio determinístico que ANTECEDE a
qualificação/decisão comercial** — não é o estágio que qualifica.

## Fluxo real (verificado no código)

```
CSV do extractor do Google Maps  (data/import/*.csv)
        │
        ▼   agent_coletor.py      normaliza, deduplica, filtro comercial, separa por "tem site?"
        ▼   gbp_diagnostic.py     diagnóstico de completude da ficha do Google (todos os leads)
        │
   ┌────┴─────────────────────────────┐
   ▼ Onda 1 (sem site)                ▼ Onda 2 (com site)
   lead_qualification.py              website_analyzer.py + wave2_scoring.py
   ICP → contatabilidade →            HTTP real do site → sinais do HTML → score
   commercial_fit_score → ranking     psi_client.py (PageSpeed, OPCIONAL)
   │                                  │
   ▼ data/leads_qualificados.json     ▼ data/leads_com_site.json
   └────────────┬─────────────────────┘
                ▼   output_json.py
   QUALIFICADOR_OUTPUT_DIR/leads_qualificados_*.json   ──►  COMERCIAL (multiagente, fora deste repo)
```

Não há sistema a montante que alimente este projeto com JSON — a entrada é o CSV cru.

## Comandos

```
python main.py --csv data/import/arquivo.csv    # só importa
python main.py gbp                               # diagnóstico de ficha (todos os leads)
python main.py qualify                           # Onda 1
python main.py wave2                             # Onda 2 (análise de site)
python main.py psi                               # PageSpeed (precisa PSI_ENABLED=1 + PSI_API_KEY)
python main.py saida                             # (re)monta o contrato de saída
python main.py all --csv data/import/arquivo.csv # importa + roda tudo, 1 lote por esteira
```

Requisitos: Python 3 (testado em 3.14). `pip install -r requirements.txt`
(`jsonschema` — validação do contrato de saída; `pytest` — suíte). `jsonschema` é a
primeira dependência de runtime fora da stdlib (decisão da direção, por validação do contrato).

## Documentação

A pasta `docs/` foi removida (continha nomenclatura antiga contaminada). A documentação
formal será recriada numa fase posterior do projeto.

Por enquanto: [`SISTEMA.md`](SISTEMA.md) descreve etapa a etapa o que roda e onde o dado
mora entre rodadas.
