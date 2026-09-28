"""Testes de diagnostico_io.py."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

FERRAMENTAS_DIR = Path(__file__).resolve().parent.parent / "ferramentas"
sys.path.insert(0, str(FERRAMENTAS_DIR))

import diagnostico_io as dio  # noqa: E402


def _diagnostico(place_id="PLACE123"):
    return {"place_id": place_id, "schema_version": "1.0"}


def test_salva_com_nome_esperado(tmp_path):
    agora = datetime(2026, 9, 8, 15, 30, 0, tzinfo=timezone.utc)

    caminho = dio.salvar_diagnostico(_diagnostico(), output_dir=tmp_path, agora=agora)

    assert caminho.name == "diagnostico_PLACE123_20260908-153000.json"
    assert caminho.parent == tmp_path
    assert json.loads(caminho.read_text(encoding="utf-8"))["place_id"] == "PLACE123"


def test_cria_diretorio_se_nao_existir(tmp_path):
    destino = tmp_path / "não" / "existe" / "ainda"

    caminho = dio.salvar_diagnostico(_diagnostico(), output_dir=destino)

    assert caminho.is_file()


def test_nunca_sobrescreve(tmp_path):
    agora = datetime(2026, 9, 8, 15, 30, 0, tzinfo=timezone.utc)
    dio.salvar_diagnostico(_diagnostico(), output_dir=tmp_path, agora=agora)

    with pytest.raises(dio.DiagnosticoIOError, match="já existe"):
        dio.salvar_diagnostico(_diagnostico(), output_dir=tmp_path, agora=agora)


def test_timestamps_diferentes_geram_arquivos_diferentes(tmp_path):
    t1 = datetime(2026, 9, 8, 15, 30, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 8, 15, 31, 0, tzinfo=timezone.utc)

    c1 = dio.salvar_diagnostico(_diagnostico(), output_dir=tmp_path, agora=t1)
    c2 = dio.salvar_diagnostico(_diagnostico(), output_dir=tmp_path, agora=t2)

    assert c1 != c2
    assert c1.is_file() and c2.is_file()


def test_place_id_ausente_falha_alto(tmp_path):
    with pytest.raises(dio.DiagnosticoIOError, match="place_id"):
        dio.salvar_diagnostico({"schema_version": "1.0"}, output_dir=tmp_path)


def test_place_id_vazio_falha_alto(tmp_path):
    with pytest.raises(dio.DiagnosticoIOError, match="place_id"):
        dio.salvar_diagnostico({"place_id": ""}, output_dir=tmp_path)


def test_env_define_diretorio_padrao(tmp_path, monkeypatch):
    monkeypatch.setenv(dio.ENV_DIRETORIO_SAIDA, str(tmp_path))

    assert dio.diretorio_saida() == tmp_path


def test_conteudo_gravado_preserva_unicode(tmp_path):
    diagnostico = _diagnostico()
    diagnostico["motivo_crm"] = "Site já adequado — sem abertura clara para nossa oferta."

    caminho = dio.salvar_diagnostico(diagnostico, output_dir=tmp_path)

    lido = json.loads(caminho.read_text(encoding="utf-8"))
    assert lido["motivo_crm"] == "Site já adequado — sem abertura clara para nossa oferta."
