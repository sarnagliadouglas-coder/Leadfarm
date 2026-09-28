"""
Testes de contorno dos três wrappers CLI (Etapa 5.1) — nível de processo, não
de função. Verificam o que a função testada por chamada direta não pode
provar: os bytes que realmente saem em `stdout` quando o processo é invocado
como um hook `PostToolUse` invocaria, via `subprocess`.

Por que subprocess e não chamada direta: um teste que chama `main()` na
mesma interpretação Python que o executa usa a mesma suposição de
codificação do código testado — os dois erram igual e concordam. Só o
processo filho real, com `stdout` capturado como bytes crus, expõe a
codificação que o interpretador realmente usa para escrever no pipe.

Contrato de exit code fixado por estes testes:
    0   artefato válido            {"valido": true}
    1   artefato inválido          {"valido": false, "erro": ...}
    2   não foi possível validar   {"valido": null, "erro_operacional": ...}
"""

from __future__ import annotations

import copy
import json
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


def _rodar(script: str, *args: str) -> subprocess.CompletedProcess:
    """Roda um wrapper como subprocess, stdout/stderr como bytes crus —
    exatamente como um hook PostToolUse chamaria."""
    return subprocess.run(
        [sys.executable, str(FERRAMENTAS_DIR / script), *args],
        capture_output=True,
    )


@pytest.fixture
def dossie_com_referencia_quebrada(tmp_path: Path) -> Path:
    """Cópia de um dossiê real com um fontes_ref inválido — dispara a
    mensagem de causa+correção, que tem acentuação ('não')."""
    if not EQC_DOSSIE_REAL.is_file():
        pytest.skip(f"dossiê real de referência não encontrado: {EQC_DOSSIE_REAL}")
    dossie = json.loads(EQC_DOSSIE_REAL.read_text(encoding="utf-8"))
    dossie = copy.deepcopy(dossie)
    dossie["fatos_observados"][0]["fontes_ref"] = ["fonte_inexistente_999"]
    caminho = tmp_path / "dossie_referencia_quebrada.json"
    caminho.write_text(json.dumps(dossie, ensure_ascii=False), encoding="utf-8")
    return caminho


def test_json_invalido_decodifica_como_utf8(dossie_com_referencia_quebrada):
    """Defeito 1: a saída --json de um artefato inválido tem acentuação
    (a mensagem de fontes_ref cita 'não'). Os bytes crus de stdout devem
    decodificar como UTF-8 — não como a codificação local do console."""
    r = _rodar("validador_dossie.py", str(dossie_com_referencia_quebrada), "--json")
    assert r.returncode == 1, f"esperava exit 1 (artefato inválido); veio {r.returncode}"
    try:
        texto = r.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        pytest.fail(
            f"stdout não decodifica como UTF-8 (bytes: {r.stdout[:120]!r}): {exc}"
        )
    corpo = json.loads(texto)
    assert corpo["valido"] is False
    assert "não" in corpo["erro"]


@pytest.mark.parametrize("script,args_extra", [
    ("validador_dossie.py", []),
    ("validador_diagnostico.py", ["__dossie_origem_qualquer__.json"]),
])
def test_json_malformado_retorna_exit_2(tmp_path: Path, script, args_extra):
    """Defeito 2: JSON malformado no arquivo de entrada não é um artefato
    'inválido' (nível de conteúdo) — é uma falha operacional (não foi
    possível nem chegar a validar). exit 2, JSON parseável em stdout."""
    caminho_malformado = tmp_path / "malformado.json"
    caminho_malformado.write_text("{isto nao e json", encoding="utf-8")

    args = [str(caminho_malformado)] + args_extra
    r = _rodar(script, *args, "--json")

    assert r.returncode == 2, (
        f"{script}: esperava exit 2 (falha operacional) para JSON malformado; "
        f"veio {r.returncode}. stdout={r.stdout!r} stderr={r.stderr[:300]!r}"
    )
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["valido"] is None
    assert "erro_operacional" in corpo


@pytest.mark.parametrize("script,args_extra", [
    ("validador_dossie.py", []),
    ("validador_diagnostico.py", ["__dossie_origem_qualquer__.json"]),
])
def test_arquivo_ausente_retorna_exit_2(tmp_path: Path, script, args_extra):
    """Arquivo que não existe é a mesma classe de falha operacional que
    JSON malformado — nunca chegou a existir um artefato para julgar."""
    caminho_ausente = tmp_path / "nao_existe.json"
    args = [str(caminho_ausente)] + args_extra
    r = _rodar(script, *args, "--json")

    assert r.returncode == 2, (
        f"{script}: esperava exit 2 para arquivo ausente; veio {r.returncode}. "
        f"stdout={r.stdout!r} stderr={r.stderr[:300]!r}"
    )
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["valido"] is None


def test_contrato_loader_arquivo_ausente_retorna_exit_2(tmp_path: Path):
    """Defeito 2, caso nomeado explicitamente: contrato_loader hoje devolve
    exit 1 (mesmo código de ContratoInvalidoError) para ArquivoDeEntradaError,
    que é falha operacional, não artefato reprovado."""
    caminho_ausente = tmp_path / "nao_existe.json"
    r = _rodar("contrato_loader.py", str(caminho_ausente), "--json")

    assert r.returncode == 2, (
        f"esperava exit 2 (ArquivoDeEntradaError é falha operacional); "
        f"veio {r.returncode}. stdout={r.stdout!r}"
    )
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["valido"] is None
    assert "erro_operacional" in corpo


def test_contrato_loader_json_malformado_retorna_exit_1(tmp_path: Path):
    """contrato_loader é a exceção da regra: `carregar_lote` já converte
    JSONDecodeError em ContratoInvalidoError internamente — o wrapper NÃO
    deve reinterpretar isso como falha operacional. exit 1, não 2."""
    caminho_malformado = tmp_path / "malformado.json"
    caminho_malformado.write_text("{isto nao e json", encoding="utf-8")
    r = _rodar("contrato_loader.py", str(caminho_malformado), "--json")

    assert r.returncode == 1, (
        f"esperava exit 1 (ContratoInvalidoError, já classificado pela "
        f"biblioteca); veio {r.returncode}. stdout={r.stdout!r}"
    )
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["valido"] is False
