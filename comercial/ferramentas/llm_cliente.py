"""llm_cliente.py — uma chamada à API da Anthropic (Etapa E1,
`RUMO-COMERCIAL-2026-09.md` §5). Infraestrutura só: nenhum prompt comercial,
nenhuma mensagem, nenhuma estratégia vive aqui — isso é a etapa seguinte.

`chamar_llm` sempre resolve a chave antes de qualquer outra coisa
(`llm_config.resolver_api_key`, que levanta `ChaveApiAusenteError` com
instrução clara se ela não estiver configurada) — mesmo quando um cliente é
injetado (`cliente=`), para que o mesmo caminho de falha valha em produção e
em teste. Nunca segue em frente sem chave.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

try:
    import llm_config
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
    import llm_config

try:
    from custo_llm import Uso, uso_de_resposta
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from custo_llm import Uso, uso_de_resposta

MAX_TOKENS_PADRAO = 16000


@dataclass(frozen=True)
class RespostaLLM:
    """Resultado de uma chamada: texto já extraído dos blocos `text` da
    resposta, uso medido, e o modelo efetivamente usado. `resposta_bruta`
    fica disponível para quem precisar de outros blocos (ex.: `thinking`)."""

    texto: str
    uso: Uso
    modelo: str
    resposta_bruta: Any


def _extrair_texto(blocos: Iterable) -> str:
    return "".join(
        bloco.text for bloco in blocos if getattr(bloco, "type", None) == "text"
    )


def chamar_llm(
    mensagens: list,
    *,
    system: Optional[str] = None,
    max_tokens: int = MAX_TOKENS_PADRAO,
    modelo: Optional[str] = None,
    cliente: Optional[Any] = None,
) -> RespostaLLM:
    """Faz uma chamada a `POST /v1/messages` e devolve texto + uso medido.

    - `modelo` omitido ⇒ resolvido por `llm_config.resolver_modelo()`
      (env `COMERCIAL_LLM_MODEL` ou `modelo_default` da tabela de preços).
    - `cliente` omitido ⇒ instancia `anthropic.Anthropic(api_key=...)` com a
      chave resolvida. Testes injetam aqui um cliente simulado — nenhum
      teste deste módulo faz chamada real.
    - Sem `ANTHROPIC_API_KEY` configurada, levanta `llm_config.ChaveApiAusenteError`
      antes de tocar em `cliente` ou na rede, mesmo com `cliente` injetado.
    """
    chave = llm_config.resolver_api_key()
    modelo_resolvido = modelo or llm_config.resolver_modelo()

    if cliente is None:
        import anthropic

        cliente = anthropic.Anthropic(api_key=chave)

    kwargs: dict = {
        "model": modelo_resolvido,
        "max_tokens": max_tokens,
        "messages": mensagens,
    }
    if system is not None:
        kwargs["system"] = system

    resposta = cliente.messages.create(**kwargs)

    return RespostaLLM(
        texto=_extrair_texto(resposta.content),
        uso=uso_de_resposta(resposta),
        modelo=modelo_resolvido,
        resposta_bruta=resposta,
    )
