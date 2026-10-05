"""Ajustes da revisão do contrato 2.2.0 (aprovados pelo diretor, 05/10/2026):
(a) campo de campanha presente mas vazio sai CONFIRMADO_AUSENTE, a saída valida no schema
    2.2.0 e o schema documenta esse estado;
(b) par que divide telefone E domínio aparece uma vez só em possivel_mesmo_negocio no JSON,
    igual ao CSV humano. Dados fictícios."""
import pytest

import contrato
import output_json as oj
import saida_humana as sh
from test_output_json import _com_site, _emp, _qualificado, _render

PAR_DUPLO = [
    {"place_id": "p-outro", "por": "telefone", "chave": "600000001"},
    {"place_id": "p-outro", "por": "dominio", "chave": "ficticio.es"},
]


def _nata(**emp_over):
    return _com_site(dados_empresa=_emp(**emp_over), site_renderizado=_render(
        mobile={"contato_visivel": False}, desktop={"contato_visivel": False}))


# --- (a) campanha vazia ----------------------------------------------------------------------

@pytest.mark.parametrize("vazio", ["", None])
def test_campanha_vazia_sai_confirmado_ausente_e_valida(vazio):
    doc = oj.montar([], [_nata(campanha_id=vazio, campanha_nicho=vazio, possivel_mesmo_negocio=[])], [])
    lead = doc["nata"][0]
    assert lead["campanha_id"]["estado"] == "CONFIRMADO_AUSENTE"
    assert lead["campanha_nicho"]["estado"] == "CONFIRMADO_AUSENTE"
    contrato.validar(doc)


def test_campanha_preenchida_continua_confirmado_presente():
    """Controle: o caso vazio não contamina o preenchido."""
    doc = oj.montar([], [_nata(campanha_id="c1", campanha_nicho="N", possivel_mesmo_negocio=[])], [])
    assert doc["nata"][0]["campanha_id"] == {"valor": "c1", "estado": "CONFIRMADO_PRESENTE"}


def test_schema_documenta_o_estado_da_campanha_vazia():
    descricao = contrato.carregar_schema()["$defs"]["campo_texto_import"]["description"]
    assert "CONFIRMADO_AUSENTE" in descricao


# --- (b) par por telefone E domínio ------------------------------------------------------------

def test_par_duplo_aparece_uma_vez_no_json_e_igual_ao_csv():
    doc = oj.montar([], [_nata(campanha_id="c1", campanha_nicho="N", possivel_mesmo_negocio=PAR_DUPLO)], [])
    aviso = doc["nata"][0]["possivel_mesmo_negocio"]
    assert aviso["estado"] == "CONFIRMADO_PRESENTE"
    assert aviso["valor"] == [{"place_id": "p-outro", "por": "telefone", "chave": "600000001"}]
    contrato.validar(doc)

    [linha] = sh.montar_linhas([_qualificado(campanha_id="c1", campanha_nicho="N",
                                             possivel_mesmo_negocio=PAR_DUPLO)], [])
    assert linha["possivel_mesmo_negocio"].split(", ") == [p["place_id"] for p in aviso["valor"]]


def test_dois_parceiros_diferentes_continuam_os_dois_em_ordem():
    """Controle negativo da deduplicação: place_ids diferentes não se fundem; ordem estável."""
    pares = [{"place_id": "b", "por": "telefone", "chave": "600000002"},
             {"place_id": "a", "por": "dominio", "chave": "x.es"},
             {"place_id": "b", "por": "dominio", "chave": "x.es"}]
    doc = oj.montar([], [_nata(campanha_id="c1", campanha_nicho="N", possivel_mesmo_negocio=pares)], [])
    assert [p["place_id"] for p in doc["nata"][0]["possivel_mesmo_negocio"]["valor"]] == ["b", "a"]
