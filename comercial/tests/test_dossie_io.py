"""Testes de dossie_io.py."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

FERRAMENTAS_DIR = Path(__file__).resolve().parent.parent / "ferramentas"
sys.path.insert(0, str(FERRAMENTAS_DIR))

import dossie_io as dio  # noqa: E402


def _dossie(place_id="PLACE123"):
    return {"place_id": place_id, "schema_version": "2.0"}


def test_salva_com_nome_esperado(tmp_path):
    agora = datetime(2026, 9, 8, 14, 22, 0, tzinfo=timezone.utc)

    caminho = dio.salvar_dossie(_dossie(), output_dir=tmp_path, agora=agora)

    assert caminho.name == "dossie_PLACE123_20260908-142200.json"
    assert caminho.parent == tmp_path
    assert json.loads(caminho.read_text(encoding="utf-8"))["place_id"] == "PLACE123"


def test_cria_diretorio_se_nao_existir(tmp_path):
    destino = tmp_path / "não" / "existe" / "ainda"

    caminho = dio.salvar_dossie(_dossie(), output_dir=destino)

    assert caminho.is_file()


def test_nunca_sobrescreve(tmp_path):
    agora = datetime(2026, 9, 8, 14, 22, 0, tzinfo=timezone.utc)
    dio.salvar_dossie(_dossie(), output_dir=tmp_path, agora=agora)

    with pytest.raises(dio.DossieIOError, match="já existe"):
        dio.salvar_dossie(_dossie(), output_dir=tmp_path, agora=agora)


def test_timestamps_diferentes_geram_arquivos_diferentes(tmp_path):
    t1 = datetime(2026, 9, 8, 14, 22, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 8, 14, 23, 0, tzinfo=timezone.utc)

    c1 = dio.salvar_dossie(_dossie(), output_dir=tmp_path, agora=t1)
    c2 = dio.salvar_dossie(_dossie(), output_dir=tmp_path, agora=t2)

    assert c1 != c2
    assert c1.is_file() and c2.is_file()


def test_place_id_ausente_falha_alto(tmp_path):
    with pytest.raises(dio.DossieIOError, match="place_id"):
        dio.salvar_dossie({"schema_version": "2.0"}, output_dir=tmp_path)


def test_place_id_vazio_falha_alto(tmp_path):
    with pytest.raises(dio.DossieIOError, match="place_id"):
        dio.salvar_dossie({"place_id": ""}, output_dir=tmp_path)


def test_env_define_diretorio_padrao(tmp_path, monkeypatch):
    monkeypatch.setenv(dio.ENV_DIRETORIO_SAIDA, str(tmp_path))

    assert dio.diretorio_saida() == tmp_path


def test_conteudo_gravado_preserva_unicode(tmp_path):
    dossie = _dossie()
    dossie["negocio_nome"] = "Clínica Dental Ficticia — Alicante"

    caminho = dio.salvar_dossie(dossie, output_dir=tmp_path)

    lido = json.loads(caminho.read_text(encoding="utf-8"))
    assert lido["negocio_nome"] == "Clínica Dental Ficticia — Alicante"


# --- D14 (docs/decisoes.md, 18/09/2026): investigado_em é preenchido pela
# ferramenta, com o MESMO instante do carimbo do nome do arquivo — nunca
# pelo agente. Sempre substitui, nunca rejeita.

def test_investigado_em_ausente_e_preenchido_com_o_carimbo_do_nome(tmp_path):
    agora = datetime(2026, 9, 18, 3, 4, 5, tzinfo=timezone.utc)

    caminho = dio.salvar_dossie(_dossie(), output_dir=tmp_path, agora=agora)

    assert caminho.name == "dossie_PLACE123_20260918-030405.json"
    lido = json.loads(caminho.read_text(encoding="utf-8"))
    assert lido["investigado_em"] == "2026-09-18T03:04:05Z"


def test_investigado_em_inventado_e_substituido(tmp_path):
    agora = datetime(2026, 9, 18, 3, 4, 5, tzinfo=timezone.utc)
    dossie = _dossie()
    dossie["investigado_em"] = "2099-01-01T00:00:00Z"  # valor inventado pelo agente

    caminho = dio.salvar_dossie(dossie, output_dir=tmp_path, agora=agora)

    lido = json.loads(caminho.read_text(encoding="utf-8"))
    assert lido["investigado_em"] == "2026-09-18T03:04:05Z"
    assert lido["investigado_em"] != "2099-01-01T00:00:00Z"


def test_preencher_investigado_em_nao_muta_o_dict_original(tmp_path):
    """salvar_dossie não deve alterar o dict que o chamador passou — grava
    uma cópia. Confirma que _preencher_investigado_em copia, não muta."""
    agora = datetime(2026, 9, 18, 3, 4, 5, tzinfo=timezone.utc)
    dossie_original = _dossie()

    dio.salvar_dossie(dossie_original, output_dir=tmp_path, agora=agora)

    assert "investigado_em" not in dossie_original
