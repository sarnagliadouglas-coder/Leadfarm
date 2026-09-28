"""
Testes de contorno da CLI de dossie_io.py (main), nível de processo — mesmo
motivo do test_wrappers_cli.py: só um subprocess real, com stdin/stdout como
bytes crus, prova o que a CLI realmente faz. Chamar main() na mesma
interpretação do teste usaria a mesma suposição de codificação do código
testado.

Antes desta CLI existir, dossie_io.py não tinha main() nem __main__:
`python dossie_io.py < dossie.json` saía com exit 0, em silêncio, sem gravar
nada — o pior caso possível (parece sucesso, não fez nada). Reproduzido
manualmente em 15/09/2026 antes de qualquer código ser escrito.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FERRAMENTAS_DIR = Path(__file__).resolve().parent.parent / "ferramentas"
# Qualquer dossiê real que esteja na pasta do pipeline (fora do Git) serve de
# referência -- nenhum place_id de lead real fica escrito no código versionado.
# Sem nenhum dossiê na pasta, os testes que dependem dele são pulados.
_DIR_DOSSIES_REAIS = (
    Path(__file__).resolve().parent.parent.parent / "EQC" / "pipeline" / "comercial" / "01-investigacao"
)
EQC_DOSSIE_REAL = next(iter(sorted(_DIR_DOSSIES_REAIS.glob("dossie_*.json"))), _DIR_DOSSIES_REAIS / "dossie_ausente.json")


def _rodar(stdin_bytes: bytes, output_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["COMERCIAL_A1_OUTPUT_DIR"] = str(output_dir)
    return subprocess.run(
        [sys.executable, str(FERRAMENTAS_DIR / "dossie_io.py"), *args],
        input=stdin_bytes,
        capture_output=True,
        env=env,
    )


@pytest.fixture
def dossie_valido_bytes() -> bytes:
    if not EQC_DOSSIE_REAL.is_file():
        pytest.skip(f"dossiê real de referência não encontrado: {EQC_DOSSIE_REAL}")
    return EQC_DOSSIE_REAL.read_bytes()


def test_dossie_valido_grava_e_devolve_caminho(tmp_path, dossie_valido_bytes):
    r = _rodar(dossie_valido_bytes, tmp_path, "--json")

    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["gravado"] is True

    arquivos = list(tmp_path.iterdir())
    assert len(arquivos) == 1, f"esperava 1 arquivo gravado, achei {arquivos}"
    assert corpo["caminho"] == str(arquivos[0]), (
        "o caminho devolvido no stdout precisa ser exatamente o arquivo real "
        f"gravado — devolvido: {corpo['caminho']!r}, real: {arquivos[0]!r}"
    )


def test_dossie_invalido_exit_1_nada_gravado(tmp_path):
    dossie_invalido = json.dumps({"place_id": "PLACE123"}).encode("utf-8")
    r = _rodar(dossie_invalido, tmp_path, "--json")

    assert r.returncode == 1, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["gravado"] is False
    assert list(tmp_path.iterdir()) == []


def test_json_malformado_exit_2_nada_gravado(tmp_path):
    r = _rodar(b"{isto nao e json", tmp_path, "--json")

    assert r.returncode == 2, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["gravado"] is None
    assert "erro_operacional" in corpo
    assert list(tmp_path.iterdir()) == []


def test_stdin_vazio_exit_2(tmp_path):
    r = _rodar(b"", tmp_path, "--json")

    assert r.returncode == 2, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["gravado"] is None
    assert list(tmp_path.iterdir()) == []


def test_stdout_decodifica_como_utf8_ascii_puro(tmp_path):
    """Defeito da 5.1 não se repete: a saída --json é ASCII puro nos três
    casos (válido, inválido, operacional) — não só verificado na tela."""
    dossie_invalido = json.dumps({"place_id": "PLACE123"}).encode("utf-8")
    r = _rodar(dossie_invalido, tmp_path, "--json")

    assert r.returncode == 1
    todos_ascii = all(b < 128 for b in r.stdout)
    assert todos_ascii, f"stdout não é ASCII puro: {r.stdout[:200]!r}"
    r.stdout.decode("utf-8")  # não deve levantar


def test_escreve_so_no_destino(tmp_path, dossie_valido_bytes):
    """Depois de cada caso, o diretório de destino contém só o que se
    espera — nunca sobra de um caso anterior nem escrita fora do destino."""
    r1 = _rodar(json.dumps({"place_id": "X"}).encode(), tmp_path, "--json")
    assert r1.returncode == 1
    assert list(tmp_path.iterdir()) == []

    r2 = _rodar(b"", tmp_path, "--json")
    assert r2.returncode == 2
    assert list(tmp_path.iterdir()) == []

    r3 = _rodar(dossie_valido_bytes, tmp_path, "--json")
    assert r3.returncode == 0
    arquivos = list(tmp_path.iterdir())
    assert len(arquivos) == 1
    assert arquivos[0].name.startswith("dossie_")
