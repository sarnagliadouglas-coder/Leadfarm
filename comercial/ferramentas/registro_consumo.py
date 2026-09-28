"""registro_consumo.py — registro de consumo de chamadas à API da Anthropic
(Etapa E1), gravado fora do Git.

Duas granularidades pedidas pela tarefa, sem duas fontes de verdade:

- **por chamada**: `registrar_chamada` grava uma linha JSON (append-only,
  nunca reescreve linha anterior) com lead, modelo, tokens, custo estimado e
  data/hora.
- **acumulado por rodada**: `resumo_rodada` deriva número de chamadas, tokens
  totais e custo total **lendo** o mesmo arquivo — nunca mantém uma segunda
  gravação de estado que possa dessincronizar do log linha-a-linha.

Onde gravar (qual arquivo/pasta é "a rodada") é decisão de quem chama —
este módulo só sabe ler e escrever o formato.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from custo_llm import Uso
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from custo_llm import Uso


def registrar_chamada(
    caminho: Path,
    *,
    lead_id: str,
    modelo: str,
    uso: Uso,
    custo_usd: float,
    quando: Optional[datetime] = None,
) -> dict:
    """Acrescenta uma linha JSON ao arquivo em `caminho` (cria diretórios e
    arquivo se preciso; nunca sobrescreve linhas já gravadas). Devolve o
    registro gravado."""
    quando = quando or datetime.now(timezone.utc)
    registro = {
        "quando": quando.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lead_id": lead_id,
        "modelo": modelo,
        "tokens": asdict(uso),
        "custo_estimado_usd": custo_usd,
    }
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False))
        f.write("\n")
    return registro


def resumo_rodada(caminho: Path) -> dict:
    """Lê `caminho` (o log de `registrar_chamada`) e devolve o acumulado:
    número de chamadas, tokens totais por categoria e custo total em USD.
    Arquivo ausente ou vazio devolve tudo zerado — não é erro."""
    caminho = Path(caminho)
    resumo = {
        "numero_chamadas": 0,
        "tokens_totais": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        "custo_total_usd": 0.0,
    }
    try:
        linhas = caminho.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        return resumo

    for linha in linhas:
        linha = linha.strip()
        if not linha:
            continue
        registro = json.loads(linha)
        resumo["numero_chamadas"] += 1
        for chave, valor in registro["tokens"].items():
            resumo["tokens_totais"][chave] += valor
        resumo["custo_total_usd"] += registro["custo_estimado_usd"]
    return resumo
