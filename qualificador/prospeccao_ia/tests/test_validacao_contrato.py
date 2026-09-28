import json

import jsonschema
import pytest

import contrato
import main as main_mod
import output_json
from test_output_json import _com_site, _qualificado, _render


def _doc():
    return output_json.montar([], [_com_site(site_renderizado=_render(
        mobile={"contato_visivel": False}, desktop={"contato_visivel": False}))], [])


def test_montar_produz_doc_v2_valido():
    doc = _doc()
    assert doc["contract_version"] == contrato.CONTRACT_VERSION  # 2.1.0 (adiciona texto_site, MINOR)
    jsonschema.Draft202012Validator(contrato.carregar_schema()).validate(doc)


@pytest.mark.parametrize("mutacao", [
    lambda d: d.pop("nata"),
    lambda d: d["nata"][0].update({"campo_fantasma": "x"}),
    lambda d: d["contract_version"].__class__ and d.update({"contract_version": "1.1.0"}),
])
def test_schema_rejeita_documento_invalido(mutacao):
    doc = _doc()
    mutacao(doc)
    with pytest.raises(jsonschema.exceptions.ValidationError):
        contrato.validar(doc)


def test_validacao_nao_escreve_json_invalido(tmp_path, monkeypatch):
    out = tmp_path / "saida"
    monkeypatch.setenv("QUALIFICADOR_OUTPUT_DIR", str(out))
    doc = _doc()
    doc["nata"][0]["problema_vendavel"][0]["tipo"] = "inventado"
    with pytest.raises(jsonschema.exceptions.ValidationError):
        contrato.validar(doc)
    assert not out.exists()


def _fase_saida_isolada_deve_falhar(tmp_path, monkeypatch, doc):
    out_dir = tmp_path / "saida"
    monkeypatch.setenv("QUALIFICADOR_OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(main_mod, "PATH_QUALIFICADOS", str(tmp_path / "qual.json"))
    monkeypatch.setattr(main_mod, "PATH_COM_SITE", str(tmp_path / "site.json"))
    monkeypatch.setattr(main_mod, "PATH_REPROVADOS", str(tmp_path / "rep.json"))
    monkeypatch.setattr(main_mod, "PATH_IMPORT_META", str(tmp_path / "meta.json"))
    monkeypatch.setattr(main_mod.output_json, "montar", lambda *a, **k: doc)
    with pytest.raises(jsonschema.exceptions.ValidationError):
        main_mod.fase_saida()
    assert not out_dir.exists() or list(out_dir.glob("leads_qualificados_*")) == []


def test_lead_sem_site_nao_entra_em_lista_de_trabalho():
    doc = output_json.montar([_qualificado()], [], [])
    assert doc["nata"] == [] and doc["candidatos_triagem"] == []


def test_saida_real_do_all_passa_na_validacao():
    doc = _doc()
    jsonschema.Draft202012Validator(contrato.carregar_schema()).validate(doc)
    assert set(doc) >= {"nata", "candidatos_triagem", "descartados"}


def test_campo_obrigatorio_removido_levanta_e_nao_grava(tmp_path, monkeypatch):
    doc = _doc()
    del doc["nata"][0]["contato"]
    _fase_saida_isolada_deve_falhar(tmp_path, monkeypatch, doc)


def test_campo_extra_nao_previsto_levanta_e_nao_grava(tmp_path, monkeypatch):
    doc = _doc()
    doc["nata"][0]["campo_fantasma"] = "xyz"
    _fase_saida_isolada_deve_falhar(tmp_path, monkeypatch, doc)


def test_autoritativo_true_levanta_e_nao_grava(tmp_path, monkeypatch):
    doc = _doc()
    doc["nata"][0]["priorizacao"]["autoritativo"] = True
    _fase_saida_isolada_deve_falhar(tmp_path, monkeypatch, doc)


def test_contract_version_errada_levanta(tmp_path, monkeypatch):
    doc = _doc()
    doc["contract_version"] = "1.1.0"
    _fase_saida_isolada_deve_falhar(tmp_path, monkeypatch, doc)


def test_reputation_signal_fora_do_enum_levanta(tmp_path, monkeypatch):
    doc = _doc()
    doc["nata"][0]["reputacao"]["reputation_signal"] = "excelente"
    _fase_saida_isolada_deve_falhar(tmp_path, monkeypatch, doc)


def test_lead_com_site_nao_medido_tem_psi_objeto_nao_verificado():
    registro = _com_site(psi=None)
    lead = output_json.montar([], [registro], [])["candidatos_triagem"][0]
    assert lead["estagio_analise"] == "COMPLETO_COM_SITE"
    assert lead["psi"]["estado"] == "NAO_VERIFICADO"
    jsonschema.Draft202012Validator(contrato.carregar_schema()).validate(
        output_json.montar([], [registro], []))
