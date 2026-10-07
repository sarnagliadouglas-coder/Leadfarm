"""Contrato 2.2.0: carimbo da campanha (campanha_id, campanha_nicho) e aviso
possivel_mesmo_negocio por lead; campanha e detalhe do corte nos descartados. Dados fictícios."""
import json

import jsonschema
import pytest

import contrato
import output_json as oj
from test_output_json import _com_site, _emp, _render

CARIMBO = {"campanha_id": "camp-teste", "campanha_nicho": "Psicólogos (teste)"}


def _nata(**emp_over):
    return _com_site(dados_empresa=_emp(**emp_over), site_renderizado=_render(
        mobile={"contato_visivel": False}, desktop={"contato_visivel": False}))


def _doc(com_site, reprovados=()):
    return oj.montar([], list(com_site), list(reprovados))


def test_versao_do_codigo_bate_com_o_const_do_schema():
    # 2.3.0 desde 06/10/2026 (campanha_cidade, multicidade); os campos da 2.2.0 continuam.
    assert contrato.CONTRACT_VERSION == "2.3.0"
    assert contrato.carregar_schema()["properties"]["contract_version"]["const"] == "2.3.0"


def test_lead_novo_carrega_o_carimbo_confirmado_e_valida():
    doc = _doc([_nata(**CARIMBO, possivel_mesmo_negocio=[])])
    lead = doc["nata"][0]
    assert lead["campanha_id"] == {"valor": "camp-teste", "estado": "CONFIRMADO_PRESENTE"}
    assert lead["campanha_nicho"] == {"valor": "Psicólogos (teste)", "estado": "CONFIRMADO_PRESENTE"}
    contrato.validar(doc)


def test_lead_antigo_sem_carimbo_vem_nao_verificado_e_valida():
    doc = _doc([_nata()])
    lead = doc["nata"][0]
    for campo in ("campanha_id", "campanha_nicho", "possivel_mesmo_negocio"):
        assert lead[campo] == {"valor": None, "estado": "NAO_VERIFICADO"}
    contrato.validar(doc)


def test_aviso_tem_os_tres_estados():
    par = [{"place_id": "p-outro", "por": "telefone", "chave": "600000001"}]
    com_par = _doc([_nata(**CARIMBO, possivel_mesmo_negocio=par)])["nata"][0]["possivel_mesmo_negocio"]
    sem_par = _doc([_nata(**CARIMBO, possivel_mesmo_negocio=[])])["nata"][0]["possivel_mesmo_negocio"]
    assert com_par == {"valor": par, "estado": "CONFIRMADO_PRESENTE"}
    assert sem_par == {"valor": None, "estado": "CONFIRMADO_AUSENTE"}


def test_candidato_triagem_tambem_carrega_os_campos():
    doc = _doc([_com_site(dados_empresa=_emp(**CARIMBO, possivel_mesmo_negocio=[]))])
    assert doc["candidatos_triagem"][0]["campanha_id"]["valor"] == "camp-teste"
    contrato.validar(doc)


def test_descartado_carrega_campanha_e_detalhe_do_corte():
    reprovado = {"dados_empresa": _emp(place_id="r1", **CARIMBO), "status": "rejected",
                 "rejection_reason": "rede_ou_multiunidade",
                 "rejection_detail": {"por": "telefone", "chave": "600000001", "tamanho_grupo": 3}}
    antigo = {"dados_empresa": _emp(place_id="r2"), "status": "rejected", "rejection_reason": "large_organization"}
    doc = _doc([], [reprovado, antigo])
    novo, velho = doc["descartados"]
    assert novo["campanha_id"] == {"valor": "camp-teste", "estado": "CONFIRMADO_PRESENTE"}
    assert novo["campos_do_corte"]["detalhe_do_corte"]["valor"]["tamanho_grupo"] == 3
    assert set(novo["campos_do_corte"]) >= {"nome", "telefone", "website"}
    assert velho["campanha_id"] == {"valor": None, "estado": "NAO_VERIFICADO"}
    assert "detalhe_do_corte" not in velho["campos_do_corte"]
    contrato.validar(doc)


# --- controles negativos: o schema 2.2.0 recusa o que deve recusar ---------------------------

@pytest.mark.parametrize("mutacao", [
    lambda d: d["nata"][0].pop("campanha_id"),
    lambda d: d["nata"][0].pop("possivel_mesmo_negocio"),
    lambda d: d["nata"][0]["campanha_id"].update({"estado": "TALVEZ"}),
    lambda d: d["nata"][0]["possivel_mesmo_negocio"].update(
        {"valor": [{"place_id": "x", "por": "email", "chave": "y"}]}),
    lambda d: d["descartados"][0].pop("campanha_nicho"),
    lambda d: d.update({"contract_version": "2.1.0"}),
])
def test_schema_2_2_0_recusa_documento_invalido(mutacao):
    reprovado = {"dados_empresa": _emp(place_id="r1", **CARIMBO), "status": "rejected",
                 "rejection_reason": "large_organization"}
    doc = _doc([_nata(**CARIMBO, possivel_mesmo_negocio=[])], [reprovado])
    contrato.validar(doc)                       # controle: antes da mutação, válido
    mutacao(doc)
    with pytest.raises(jsonschema.exceptions.ValidationError):
        contrato.validar(doc)


def test_fase_saida_grava_a_versao_vigente_com_carimbo(tmp_path, monkeypatch):
    import main as main_mod
    registro = _nata(**CARIMBO, possivel_mesmo_negocio=[])
    (tmp_path / "leads_com_site.json").write_text(json.dumps([registro]), encoding="utf-8")
    main_mod.fase_saida()
    saida_dir = tmp_path / "_saida"
    [arquivo] = [p for p in saida_dir.iterdir() if not p.name.endswith(".meta.json")]
    assert arquivo.name.endswith("_v2.3.0.json")
    doc = json.loads(arquivo.read_text(encoding="utf-8"))
    assert doc["nata"][0]["campanha_id"]["valor"] == "camp-teste"
