"""
Testes de contorno do `--place-id` na CLI de contrato_loader.py — nível de
processo, subprocess real, mesmo motivo dos outros arquivos `test_*_cli*.py`
desta suíte: só o processo filho real prova o que a CLI grava em stdout.

Reaproveita `_documento_valido`/`_lead_minimo`/`_campo` de
test_contrato_loader.py — são fixtures schema-completas já mantidas lá; não
duplicar aqui é o que a Etapa 6 já registrou como regra de lugar canônico.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FERRAMENTAS_DIR = Path(__file__).resolve().parent.parent / "ferramentas"
TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
SCHEMA_FIXTURE_PATH = FIXTURES_DIR / "leads_qualificados.schema.json"

sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(FERRAMENTAS_DIR))

from test_contrato_loader import _documento_valido, _lead_minimo  # noqa: E402


def _rodar(caminho_lote: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(FERRAMENTAS_DIR / "contrato_loader.py"), str(caminho_lote), *args],
        capture_output=True,
        cwd=str(cwd),
        env=dict(os.environ),
    )


def _sem_priorizacao_em_lugar_nenhum(obj) -> bool:
    """Varre recursivamente — dict, list, em qualquer profundidade."""
    if isinstance(obj, dict):
        if "priorizacao" in obj:
            return False
        return all(_sem_priorizacao_em_lugar_nenhum(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_sem_priorizacao_em_lugar_nenhum(v) for v in obj)
    return True


@pytest.fixture
def repo_root() -> Path:
    raiz = Path(__file__).resolve().parent.parent.parent
    assert (raiz / "comercial" / "ferramentas" / "contrato_loader.py").is_file()
    return raiz


@pytest.fixture
def lote_com_dois_leads(tmp_path: Path) -> Path:
    lead_a = _lead_minimo()
    lead_b = copy.deepcopy(lead_a)
    lead_b["place_id"] = "OUTRO_PLACE_ID_456"
    doc = _documento_valido(nata=[lead_a, lead_b])
    caminho = tmp_path / "lote.json"
    caminho.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return caminho


def test_place_id_encontrado_nunca_tem_priorizacao_em_nenhum_nivel(lote_com_dois_leads, repo_root):
    r = _rodar(lote_com_dois_leads, "--place-id", "ChIJFicticioLead00000000001", "--json", cwd=repo_root)

    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert _sem_priorizacao_em_lugar_nenhum(corpo), (
        f"'priorizacao' apareceu em algum nível da saída: {corpo!r}"
    )
    # a versão protegida continua acessível
    assert "priorizacao_nao_autoritativa" in corpo.get("lead", corpo)


def test_place_id_inexistente_exit_2(lote_com_dois_leads, repo_root):
    r = _rodar(lote_com_dois_leads, "--place-id", "NAO_EXISTE_NO_LOTE", "--json", cwd=repo_root)

    assert r.returncode == 2, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["valido"] is None
    assert "erro_operacional" in corpo


def test_stdout_ascii_puro(lote_com_dois_leads, repo_root):
    r = _rodar(lote_com_dois_leads, "--place-id", "ChIJFicticioLead00000000001", "--json", cwd=repo_root)

    assert r.returncode == 0
    assert all(b < 128 for b in r.stdout), f"stdout não é ASCII puro: {r.stdout[:200]!r}"
    r.stdout.decode("utf-8")  # não deve levantar


def test_roda_a_partir_da_raiz_do_leadfarm(lote_com_dois_leads, repo_root):
    """O comando real do roteiro é `python comercial/ferramentas/contrato_loader.py
    ... --place-id ... --json`, rodado com cwd na raiz do LeadFarm — não em
    comercial/ferramentas/."""
    r = subprocess.run(
        [
            sys.executable,
            "comercial/ferramentas/contrato_loader.py",
            str(lote_com_dois_leads),
            "--place-id", "ChIJFicticioLead00000000001",
            "--json",
        ],
        capture_output=True,
        cwd=str(repo_root),
        env=dict(os.environ),
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo["valido"] is True


def test_sem_place_id_comportamento_atual_inalterado(lote_com_dois_leads, repo_root):
    r = _rodar(lote_com_dois_leads, "--json", cwd=repo_root)
    assert r.returncode == 0
    corpo = json.loads(r.stdout.decode("utf-8"))
    assert corpo == {"valido": True, "origem": str(lote_com_dois_leads), "leads": 2}
