"""email_utils.py — link `mailto:` para a coluna "Abrir e-mail" da planilha
de envio (Etapa E2b, decisão do diretor, 24/09/2026, quarta rodada). Nenhum
envio de e-mail — só monta o link, igual a `whatsapp_utils.link_whatsapp*`.

`config/assunto_email.json` carrega o assunto por pista ("direta"/"nata") —
o diretor edita à mão, o código só lê.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from urllib.parse import quote

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CAMINHO_ASSUNTOS_PADRAO = _CONFIG_DIR / "assunto_email.json"

_CHAVES_ASSUNTOS_OBRIGATORIAS = ("direta", "nata")


class ConfigAssuntoEmailInvalidaError(Exception):
    """`config/assunto_email.json` ausente, ilegível ou incompleto."""


def carregar_assuntos_email(caminho: Path = CAMINHO_ASSUNTOS_PADRAO) -> dict:
    caminho = Path(caminho)
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as e:
        raise ConfigAssuntoEmailInvalidaError(
            f"Config de assunto de e-mail não encontrada em {caminho}: {e}"
        ) from e
    try:
        config = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ConfigAssuntoEmailInvalidaError(
            f"Config de assunto de e-mail em {caminho} não é JSON válido: {e}"
        ) from e

    faltando = [c for c in _CHAVES_ASSUNTOS_OBRIGATORIAS if c not in config]
    if faltando:
        raise ConfigAssuntoEmailInvalidaError(
            f"Config de assunto de e-mail em {caminho} sem as chaves: {faltando}"
        )
    return config


def link_mailto(email: Optional[str], assunto: str, mensagem: str) -> str:
    """`mailto:<email>?subject=<assunto>&body=<mensagem>`, `assunto` e
    `mensagem` percent-encoded (`quote`, `safe=""` — cobre acento, "¿" e
    quebra de linha, que vira `%0A`). `email` vazio/`None` devolve string
    vazia — nunca um link sem destinatário."""
    if not email:
        return ""
    return f"mailto:{email}?subject={quote(assunto, safe='')}&body={quote(mensagem or '', safe='')}"
