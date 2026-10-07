"""Contrato 2.3.0 (multicidade, diretor 06/10/2026): `campanha_cidade` por lead e por
descartado, no padrão de campanha_id/campanha_nicho; coluna 20 do CSV humano. Dados fictícios."""
import csv

import jsonschema
import pytest

import contrato
import saida_humana as sh
from test_contrato_2_2_0 import _doc, _nata
from test_output_json import _emp, _qualificado

CARIMBO = {"campanha_id": "camp-teste", "campanha_nicho": "Psicólogos (teste)", "campanha_cidade": "Murcia"}


def test_lead_carrega_a_cidade_confirmada_e_valida():
    doc = _doc([_nata(**CARIMBO, possivel_mesmo_negocio=[])])
    assert doc["nata"][0]["campanha_cidade"] == {"valor": "Murcia", "estado": "CONFIRMADO_PRESENTE"}
    contrato.validar(doc)


def test_lead_anterior_a_2_3_0_vem_nao_verificado_e_valida():
    sem_cidade = {k: v for k, v in CARIMBO.items() if k != "campanha_cidade"}
    doc = _doc([_nata(**sem_cidade, possivel_mesmo_negocio=[])])
    assert doc["nata"][0]["campanha_cidade"] == {"valor": None, "estado": "NAO_VERIFICADO"}
    contrato.validar(doc)


def test_descartado_carrega_a_cidade():
    reprovado = {"dados_empresa": _emp(place_id="r1", **CARIMBO), "status": "rejected",
                 "rejection_reason": "large_organization"}
    antigo = {"dados_empresa": _emp(place_id="r2"), "status": "rejected", "rejection_reason": "large_organization"}
    doc = _doc([], [reprovado, antigo])
    por_id = {d["place_id"]: d for d in doc["descartados"]}
    assert por_id["r1"]["campanha_cidade"] == {"valor": "Murcia", "estado": "CONFIRMADO_PRESENTE"}
    assert por_id["r2"]["campanha_cidade"] == {"valor": None, "estado": "NAO_VERIFICADO"}
    contrato.validar(doc)


@pytest.mark.parametrize("lista", ["nata", "descartados"])
def test_schema_exige_campanha_cidade(lista):
    """Controle negativo: sem o campo, o documento não valida (campo obrigatório na 2.3.0)."""
    reprovado = {"dados_empresa": _emp(place_id="r1", **CARIMBO), "status": "rejected",
                 "rejection_reason": "large_organization"}
    doc = _doc([_nata(**CARIMBO, possivel_mesmo_negocio=[])], [reprovado])
    contrato.validar(doc)
    del doc[lista][0]["campanha_cidade"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, contrato.carregar_schema())


def test_csv_humano_tem_a_cidade_na_coluna_20():
    assert sh.COLUNAS[19] == "campanha_cidade" and len(sh.COLUNAS) == 20
    [linha] = sh.montar_linhas([_qualificado(**CARIMBO)], [])
    assert linha["campanha_cidade"] == "Murcia"
    [antiga] = sh.montar_linhas([_qualificado()], [])
    assert antiga["campanha_cidade"] == "NAO_VERIFICADO"


def test_csv_humano_gravado_relido(tmp_path):
    caminho = tmp_path / "qualificador_x.csv"
    sh.escrever_csv(sh.montar_linhas([_qualificado(**CARIMBO, possivel_mesmo_negocio=[])], []), str(caminho))
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        leitor = csv.DictReader(f, delimiter=";")
        [linha] = list(leitor)
    assert leitor.fieldnames[-1] == "campanha_cidade" and linha["campanha_cidade"] == "Murcia"
