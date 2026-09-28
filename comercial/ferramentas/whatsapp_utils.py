"""whatsapp_utils.py — normalização de telefone espanhol e montagem de link
`wa.me` (Etapa E2b, planilha de envio). Nenhum envio, nenhuma abertura de
WhatsApp — só monta o texto do link. Funções puras, sem I/O.

Regra do celular espanhol (mesma da coluna `whatsapp_apto` do QUALIFICADOR,
`telefone_utils.py`, reimplementada aqui de propósito — COMERCIAL não
importa código do QUALIFICADOR, só consome o CSV/contrato que ele produz):
9 dígitos, começando por 6 ou 7, depois de normalizar `+34`/`0034`/`34`
opcional e remover espaços/pontos/traços/parênteses. Fixo (começa 8/9) ou
qualquer formato que não bata: `None`, nunca um link fixo mascarado.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote

import re

_LIMPEZA_RE = re.compile(r"[\s.\-()]")
_PREFIXO_ES_RE = re.compile(r"^(?:\+34|0034|34)")
_MOVEL_ES_RE = re.compile(r"^[67]\d{8}$")


def normalizar_movel_espanhol(telefone) -> Optional[str]:
    """9 dígitos do número, só quando for celular espanhol válido. `None`
    para fixo, vazio, `None` de entrada, ou qualquer formato que não bata —
    nunca um "quase-válido" arredondado para servir."""
    if not telefone:
        return None
    limpo = _LIMPEZA_RE.sub("", str(telefone))
    limpo = _PREFIXO_ES_RE.sub("", limpo)
    return limpo if _MOVEL_ES_RE.fullmatch(limpo) else None


def link_whatsapp(numero_normalizado: str) -> str:
    """`https://wa.me/34<9 dígitos>` — `numero_normalizado` já validado por
    `normalizar_movel_espanhol` (não revalida aqui — quem chama decide se
    tem número ou não)."""
    return f"https://wa.me/34{numero_normalizado}"


def link_whatsapp_com_mensagem(numero_normalizado: str, mensagem: str) -> str:
    """Como `link_whatsapp`, mais `?text=<mensagem codificada>`. Usa
    `urllib.parse.quote` (percent-encoding — %20 para espaço, cobre acento,
    "¿" e vírgula) com `safe=""` — nenhum caractere escapa sem codificar."""
    return f"{link_whatsapp(numero_normalizado)}?text={quote(mensagem, safe='')}"
