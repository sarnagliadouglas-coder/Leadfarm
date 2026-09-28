"""
diagnostico_io.py — escrita em disco do diagnóstico do Agente 2.

Um diagnóstico por lead (o A2 roda por lead, não em lote — mesmo padrão de
`dossie_io.py` do Agente 1). Nunca sobrescreve: o timestamp no nome do
arquivo preserva rastreabilidade entre tentativas.

Uso:
    from diagnostico_io import salvar_diagnostico

    caminho = salvar_diagnostico(diagnostico)                         # diretório padrão
    caminho = salvar_diagnostico(diagnostico, output_dir=Path("..."))  # explícito (testes)

Diretório padrão: sem `COMERCIAL_A2_OUTPUT_DIR`, deriva do EQC resolvido em
runtime por `eqc.py` — `<eqc_root>/pipeline/comercial/02-diagnostico`. Nenhum
caminho absoluto de máquina fica fixo aqui.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

try:
    import eqc
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import eqc

ENV_DIRETORIO_SAIDA = eqc.ENV_A2_OUTPUT_DIR  # "COMERCIAL_A2_OUTPUT_DIR"


class DiagnosticoIOError(Exception):
    """Erro ao gravar o diagnóstico em disco."""


def diretorio_saida() -> Path:
    """Diretório de saída do diagnóstico. `COMERCIAL_A2_OUTPUT_DIR` (caminho
    final) vence; senão `<eqc_root>/pipeline/comercial/02-diagnostico` — ver
    `eqc.py`."""
    return eqc.diretorio_saida_a2()


def salvar_diagnostico(
    diagnostico: Mapping,
    *,
    output_dir: Optional[Path] = None,
    agora: Optional[datetime] = None,
) -> Path:
    """Grava o diagnóstico em `<output_dir>/diagnostico_<place_id>_<AAAAMMDD-HHMMSS>.json`.

    Args:
        diagnostico: o documento do diagnóstico (já validado por
            `validador_diagnostico` antes de chegar aqui — este módulo não
            valida, só grava).
        output_dir: diretório de saída. Default: COMERCIAL_A2_OUTPUT_DIR ou
            DIRETORIO_SAIDA_PADRAO.
        agora: timestamp a usar no nome do arquivo. Default: agora, UTC.
            Parametrizável para tornar os testes determinísticos.

    Raises:
        DiagnosticoIOError: `place_id` ausente/vazio no diagnóstico, ou
            falha ao escrever o arquivo.
    """
    place_id = diagnostico.get("place_id") if isinstance(diagnostico, Mapping) else None
    if not place_id:
        raise DiagnosticoIOError(
            "Diagnóstico sem 'place_id' — não é possível nomear o arquivo de saída. "
            "Valide o diagnóstico (validador_diagnostico.validar_diagnostico) antes de salvar."
        )

    destino_dir = Path(output_dir) if output_dir else diretorio_saida()
    try:
        destino_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DiagnosticoIOError(f"Não foi possível criar o diretório de saída {destino_dir}: {exc}") from exc

    timestamp = (agora or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    nome = f"diagnostico_{place_id}_{timestamp}.json"
    caminho = destino_dir / nome

    if caminho.exists():
        # Colisão de timestamp (mesma execução, mesmo segundo) -- nunca
        # sobrescrever; ver docstring do módulo.
        raise DiagnosticoIOError(
            f"{caminho} já existe -- nunca sobrescrevemos um diagnóstico. "
            f"Se isto for um reprocesso deliberado no mesmo segundo, aguarde "
            f"e tente de novo."
        )

    try:
        caminho.write_text(json.dumps(diagnostico, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise DiagnosticoIOError(f"Não foi possível escrever {caminho}: {exc}") from exc

    return caminho
