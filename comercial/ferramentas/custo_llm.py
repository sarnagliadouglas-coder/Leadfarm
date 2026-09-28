"""custo_llm.py — uso de tokens e custo derivado de uma chamada à API da
Anthropic (Etapa E1). Nenhuma função aqui faz chamada de rede.

Dois passos que nunca se confundem:
1. `uso_de_resposta` — extrai os tokens **medidos**, devolvidos pela própria
   API em `response.usage`. Fato.
2. `calcular_custo_usd` — multiplica os tokens medidos pela tabela de preços
   (`config/precos_llm.json`, carregada por `llm_config.carregar_tabela_precos`).
   **Derivado** — depende de uma tabela que pode estar desatualizada.
"""

from __future__ import annotations

from dataclasses import dataclass


class ModeloSemPrecoError(Exception):
    """A tabela de preços não tem entrada para o modelo usado na chamada —
    custo não pode ser derivado, nunca assumido como zero."""


@dataclass(frozen=True)
class Uso:
    """Tokens medidos de uma chamada, no vocabulário de `response.usage` da
    API da Anthropic."""

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


def uso_de_resposta(resposta) -> Uso:
    """Extrai `Uso` de uma resposta da API (ou de um objeto simulado com o
    mesmo formato de `.usage`). Campos de cache ausentes contam como 0 —
    respostas sem cache não trazem essas chaves."""
    usage = resposta.usage
    return Uso(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_creation_input_tokens=int(
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        ),
        cache_read_input_tokens=int(
            getattr(usage, "cache_read_input_tokens", 0) or 0
        ),
    )


def calcular_custo_usd(uso: Uso, modelo: str, tabela: dict) -> float:
    """Custo em USD = tokens medidos × preço da tabela, por categoria de
    token (entrada, saída, cache de escrita, cache de leitura). Levanta
    `ModeloSemPrecoError` se `modelo` não estiver em
    `tabela["precos_por_modelo"]` — nunca deriva custo de preço inexistente."""
    precos_por_modelo = tabela.get("precos_por_modelo", {})
    if modelo not in precos_por_modelo:
        raise ModeloSemPrecoError(
            f"Sem preço cadastrado para o modelo {modelo!r} em "
            f"config/precos_llm.json (precos_por_modelo). Modelos "
            f"cadastrados: {sorted(precos_por_modelo)}."
        )
    precos = precos_por_modelo[modelo]
    um_milhao = 1_000_000
    return (
        uso.input_tokens / um_milhao * precos["entrada"]
        + uso.output_tokens / um_milhao * precos["saida"]
        + uso.cache_creation_input_tokens / um_milhao * precos["cache_escrita"]
        + uso.cache_read_input_tokens / um_milhao * precos["cache_leitura"]
    )
