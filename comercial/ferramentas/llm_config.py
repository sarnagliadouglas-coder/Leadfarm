"""llm_config.py — resolução de configuração da chamada à API da Anthropic
(Etapa E1, `RUMO-COMERCIAL-2026-09.md` §5): chave, modelo e tabela de preços.

Nada aqui faz chamada de rede nem grava nada. Só resolve e valida.

- **Chave**: `ANTHROPIC_API_KEY`, lida de `os.environ` depois de
  `env_loader.carregar_env()` aplicar `comercial/.env` (se existir, sem
  sobrescrever env real). Ausente ⇒ `ChaveApiAusenteError` com o que fazer —
  nunca segue em frente, nunca é erro cru de rede.
- **Modelo**: env `COMERCIAL_LLM_MODEL` vence; senão `modelo_default` de
  `config/precos_llm.json`. Nunca fixo em código (regra da tarefa).
- **Tabela de preços**: `config/precos_llm.json` — arquivo de configuração,
  carimbado com a data em que foi anotado; ver a chave `_nota` nele sobre
  medido × derivado.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

try:
    import env_loader
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import env_loader

ENV_API_KEY = "ANTHROPIC_API_KEY"
ENV_MODEL = "COMERCIAL_LLM_MODEL"

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CAMINHO_PRECOS_PADRAO = _CONFIG_DIR / "precos_llm.json"


class ChaveApiAusenteError(Exception):
    """`ANTHROPIC_API_KEY` não está configurada — nunca prosseguir sem ela."""


class TabelaPrecosInvalidaError(Exception):
    """`config/precos_llm.json` ausente, ilegível ou sem as chaves exigidas."""


def resolver_api_key() -> str:
    """Devolve a chave da API. Levanta `ChaveApiAusenteError` com instrução
    clara se `ANTHROPIC_API_KEY` não estiver definida (env real ou
    `comercial/.env`). Nunca imprime nem registra o valor da chave."""
    env_loader.carregar_env()
    chave = (os.environ.get(ENV_API_KEY) or "").strip()
    if not chave:
        raise ChaveApiAusenteError(
            f"{ENV_API_KEY} não está configurada. Defina-a antes de chamar a "
            f"API da Anthropic:\n"
            f"  1. Copie comercial/.env.example para comercial/.env (se ainda "
            f"não existe);\n"
            f"  2. Adicione a linha {ENV_API_KEY}=<sua chave> em comercial/.env "
            f"(nunca versionado — coberto por .gitignore);\n"
            f"  3. Ou exporte {ENV_API_KEY} no ambiente antes de rodar.\n"
            f"Nenhuma chamada foi feita."
        )
    return chave


def carregar_tabela_precos(caminho: Path = CAMINHO_PRECOS_PADRAO) -> dict:
    """Lê e valida a tabela de preços (`config/precos_llm.json` por padrão).
    Levanta `TabelaPrecosInvalidaError` com o caminho tentado se o arquivo
    não existir, não for JSON válido, ou faltar `modelo_default` /
    `precos_por_modelo`."""
    caminho = Path(caminho)
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as e:
        raise TabelaPrecosInvalidaError(
            f"Tabela de preços não encontrada em {caminho}: {e}"
        ) from e

    try:
        tabela = json.loads(texto)
    except json.JSONDecodeError as e:
        raise TabelaPrecosInvalidaError(
            f"Tabela de preços em {caminho} não é JSON válido: {e}"
        ) from e

    if "modelo_default" not in tabela or "precos_por_modelo" not in tabela:
        raise TabelaPrecosInvalidaError(
            f"Tabela de preços em {caminho} não tem 'modelo_default' e/ou "
            f"'precos_por_modelo'."
        )
    return tabela


def resolver_modelo(tabela: Optional[dict] = None) -> str:
    """Modelo a usar na chamada. `COMERCIAL_LLM_MODEL` (env) vence; senão
    `modelo_default` da tabela de preços (`tabela`, ou carregada do arquivo
    padrão se omitida)."""
    env_loader.carregar_env()
    override = (os.environ.get(ENV_MODEL) or "").strip()
    if override:
        return override
    if tabela is None:
        tabela = carregar_tabela_precos()
    return tabela["modelo_default"]
