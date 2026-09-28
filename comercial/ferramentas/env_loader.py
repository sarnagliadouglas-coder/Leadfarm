"""env_loader.py — carregador mínimo de `comercial/.env`, só stdlib (sem
python-dotenv). Mesmo padrão de `qualificador/prospeccao_ia/env_loader.py`.

Motivo: `llm_config.py` lê `ANTHROPIC_API_KEY` direto de `os.environ`. Sem
isto, pôr a chave em `comercial/.env` não teria efeito nenhum — precisaria
ser exportada à mão no shell.

Regras:
- Lê `comercial/.env` (um nível acima de `ferramentas/`) se existir.
- Variáveis de ambiente REAIS têm precedência: nunca sobrescreve o que já
  está em `os.environ`.
- Ausência do `.env` não é erro — segue silencioso.
- Formato: `CHAVE=VALOR` por linha. Linhas vazias e as que começam com `#`
  são ignoradas. Aspas simples ou duplas em volta do valor são removidas.
  Sem interpolação, sem `export`.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _parse(texto: str):
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave = chave.strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ("'", '"'):
            valor = valor[1:-1]
        if chave:
            yield chave, valor


def carregar_env(path=None) -> list[str]:
    """Aplica `comercial/.env` a `os.environ` sem sobrescrever variáveis já
    definidas. Idempotente. Devolve a lista de chaves que passou a definir
    (vazia se não havia `.env` ou nada novo).

    `path` omitido lê o módulo `_ENV_PATH` a cada chamada (não um default
    fixado na definição da função) — um teste que faça
    `monkeypatch.setattr(env_loader, "_ENV_PATH", outro_caminho)` precisa
    que esta função enxergue o valor trocado. Um `path: Path = _ENV_PATH`
    no cabeçalho seria capturado uma vez, na importação do módulo, e
    ignoraria qualquer troca de `_ENV_PATH` feita depois — foi exatamente
    esse o defeito real (achado 24/09/2026, quando um `comercial/.env`
    passou a existir de verdade nesta máquina e os testes que achavam ter
    isolado a chave começaram a carregar a de verdade)."""
    if path is None:
        path = _ENV_PATH
    try:
        texto = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        return []

    definidas = []
    for chave, valor in _parse(texto):
        if chave not in os.environ:
            os.environ[chave] = valor
            definidas.append(chave)
    return definidas
