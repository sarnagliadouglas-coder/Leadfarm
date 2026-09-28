# COMERCIAL — Análise e Abordagem Comercial

## Visão Geral

O COMERCIAL é um sistema de análise profunda de leads que já possuem website.
O objetivo é investigar o negócio, produzir um diagnóstico comercial, criar uma abordagem personalizada e validá-la antes da entrega final.

## Fluxo Principal

```
Lead (entrada)
  → Agente 1 — Investigação
  → Agente 2 — Diagnóstico Comercial
  → Agente 3 — Copywriter
  → Agente 4 — Revisor
  → Output Final
```

### Fluxo de Revisão (futuro)

Se o Agente 4 (Revisor) retornar FAIL, o fluxo retorna ao Agente 3 (Copywriter) para correção, em vez de gerar um novo output final.

```
Agente 4 → FAIL → Agente 3 (com feedback) → Agente 4 (nova revisão)
```

## Estrutura do Projeto

```
projeto onda 2/
├── README.md                          # Este arquivo
├── config/                            # Configurações gerais do sistema
│   └── config.md                      # Definições e parâmetros globais
├── pipeline/                          # Orquestração do fluxo entre agentes
│   └── pipeline.md                    # Definição do fluxo principal
├── agents/                            # Agentes do sistema
│   ├── 01_investigacao/               # Agente 1 — Investigação
│   ├── 02_diagnostico_comercial/      # Agente 2 — Diagnóstico Comercial
│   ├── 03_copywriter/                 # Agente 3 — Copywriter
│   └── 04_revisor/                    # Agente 4 — Revisor
├── schemas/                           # Schemas dos outputs estruturados
│   │                                   # (entrada do lead: EQC\contracts\CONTRACT.md, contrato do QUALIFICADOR)
│   ├── 01_output_investigacao.md      # Output do Agente 1
│   ├── 02_output_diagnostico.md       # Output do Agente 2
│   ├── 03_output_copy.md             # Output do Agente 3
│   ├── 04_output_revisao.md          # Output do Agente 4
│   └── output_final.md               # Estrutura do output final
└── docs/                              # Documentação do projeto
    └── principios.md                  # Princípios e regras do sistema
```

## Princípios

- Separação clara de responsabilidades entre agentes
- Outputs estruturados e previsíveis
- Evidência separada de interpretação
- Modularidade: substituir ou melhorar um agente sem reconstruir o sistema
- Sem complexidade prematura
- O sistema pode concluir que não existe ângulo comercial viável

## Status

**Fase atual:** Arquitetura criada — aguardando implementação dos agentes.
