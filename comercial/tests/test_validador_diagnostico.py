"""
Testes de validador_diagnostico.py — mesmo padrão de rigor de test_validador_dossie.py.
"""

import copy
import sys
from pathlib import Path

import pytest

FERRAMENTAS_DIR = Path(__file__).resolve().parent.parent / "ferramentas"
sys.path.insert(0, str(FERRAMENTAS_DIR))

import validador_diagnostico as vdi  # noqa: E402


# --- Fixtures ---------------------------------------------------------------


def _dossie_origem(estagio="COMPLETO_COM_SITE") -> dict:
    """Dossiê mínimo do A1 -- só os campos que validador_diagnostico lê
    (place_id, estagio_analise, ids de fatos/inferencias/incertezas). Não
    precisa ser schema-válido contra 01_output_investigacao.schema.json --
    esse módulo confere referência cruzada, não reprocessa o schema do A1."""
    return {
        "place_id": "PLACE123",
        "fatos_observados": [
            {"id": "fato_001"},
            {"id": "fato_002"},
            {"id": "fato_003"},
        ],
        "inferencias": [{"id": "inf_001"}],
        "incertezas": [{"id": "inc_001"}],
        "qualificador": {"sinais_recebidos": {"estagio_analise": estagio}},
    }


def _achado(id_="achado_001", papel="principal", fatos_ref=("fato_001",), **kwargs):
    achado = {
        "id": id_,
        "natureza": "problema",
        "descricao": "Descrição do achado.",
        "relevancia_comercial": "alta",
        "papel": papel,
        "fatos_ref": list(fatos_ref),
        "inferencias_ref": [],
        "incertezas_ref": [],
        "reforca_achado_ref": None,
    }
    achado.update(kwargs)
    return achado


def _diagnostico_prosseguir(estagio="COMPLETO_COM_SITE") -> dict:
    return {
        "schema_version": "1.0",
        "place_id": "PLACE123",
        "dossie_origem": "dossie_PLACE123_20260908-100000.json",
        "lote_origem": "leads_qualificados_20260908-074342_v1.1.0.json",
        "estagio_analise": estagio,
        "diagnosticado_em": "2026-09-08T15:00:00Z",
        "modelo": "claude-sonnet-5",
        "decisao": "prosseguir",
        "achados": [
            _achado("achado_001", "principal", ["fato_001"]),
            _achado("achado_002", "secundario", ["fato_002"]),
            _achado("achado_003", "evidencia", ["fato_003"], reforca_achado_ref="achado_001"),
        ],
        "angulo_principal": {"achado_ref": "achado_001", "justificativa_escolha": "É o mais forte."},
        "sem_angulo": None,
    }


def _diagnostico_sem_angulo(estagio="COMPLETO_COM_SITE", fatos_ref=None) -> dict:
    if fatos_ref is None:
        fatos_ref = ["fato_001"] if estagio == "COMPLETO_SEM_SITE" else []
    return {
        "schema_version": "1.0",
        "place_id": "PLACE123",
        "dossie_origem": "dossie_PLACE123_20260908-100000.json",
        "lote_origem": "leads_qualificados_20260908-074342_v1.1.0.json",
        "estagio_analise": estagio,
        "diagnosticado_em": "2026-09-08T15:00:00Z",
        "modelo": "claude-sonnet-5",
        "decisao": "sem_angulo",
        "achados": [],
        "angulo_principal": None,
        "sem_angulo": {
            "motivo_categoria": "site_adequado_sem_deficiencia_relevante",
            "motivo_descricao": "Sem deficiência relevante encontrada.",
            "motivo_crm": "Site já adequado.",
            "evidencias_consideradas": ["fato_001", "inf_001"],
            "fatos_ref": fatos_ref,
        },
    }


# --- Caminho feliz -----------------------------------------------------------


def test_diagnostico_prosseguir_valido_passa():
    vdi.validar_diagnostico(_diagnostico_prosseguir(), dossie_origem=_dossie_origem())


def test_diagnostico_prosseguir_valido_passa_sem_dossie_origem():
    vdi.validar_diagnostico(_diagnostico_prosseguir())


def test_diagnostico_sem_angulo_com_site_valido_passa():
    vdi.validar_diagnostico(
        _diagnostico_sem_angulo("COMPLETO_COM_SITE"), dossie_origem=_dossie_origem("COMPLETO_COM_SITE")
    )


def test_diagnostico_sem_angulo_sem_site_com_fato_valido_passa():
    vdi.validar_diagnostico(
        _diagnostico_sem_angulo("COMPLETO_SEM_SITE", fatos_ref=["fato_001"]),
        dossie_origem=_dossie_origem("COMPLETO_SEM_SITE"),
    )


# --- Violações de schema -----------------------------------------------------


def test_sem_angulo_sem_site_sem_fatos_ref_reprova():
    """Regra dura: sem_angulo na trilha COMPLETO_SEM_SITE exige fatos_ref não-vazio."""
    diag = _diagnostico_sem_angulo("COMPLETO_SEM_SITE", fatos_ref=[])
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[schema\]"):
        vdi.validar_diagnostico(diag, dossie_origem=_dossie_origem("COMPLETO_SEM_SITE"))


def test_achados_nao_vazio_quando_sem_angulo_reprova():
    diag = _diagnostico_sem_angulo("COMPLETO_COM_SITE")
    diag["achados"] = [_achado()]
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[schema\]"):
        vdi.validar_diagnostico(diag)


def test_achados_vazio_quando_prosseguir_reprova():
    diag = _diagnostico_prosseguir()
    diag["achados"] = []
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[schema\]"):
        vdi.validar_diagnostico(diag)


def test_angulo_principal_preenchido_quando_sem_angulo_reprova():
    diag = _diagnostico_sem_angulo()
    diag["angulo_principal"] = {"achado_ref": "achado_001", "justificativa_escolha": "x"}
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[schema\]"):
        vdi.validar_diagnostico(diag)


def test_achado_sem_fatos_ref_reprova():
    diag = _diagnostico_prosseguir()
    diag["achados"][0]["fatos_ref"] = []
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[schema\]"):
        vdi.validar_diagnostico(diag)


def test_evidencia_sem_reforca_achado_ref_reprova_no_schema():
    diag = _diagnostico_prosseguir()
    diag["achados"][2]["reforca_achado_ref"] = None
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[schema\]"):
        vdi.validar_diagnostico(diag)


def test_id_inferencia_no_lugar_de_fatos_ref_reprova_no_schema():
    """Padrão ^fato_ do schema barra sintaticamente um id de inferencia em fatos_ref."""
    diag = _diagnostico_prosseguir()
    diag["achados"][0]["fatos_ref"] = ["inf_001"]
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[schema\]"):
        vdi.validar_diagnostico(diag)


# --- Violações de papel (Python, pós-schema) ---------------------------------


def test_dois_achados_principal_reprova():
    diag = _diagnostico_prosseguir()
    diag["achados"][1]["papel"] = "principal"
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[papel\].*exatamente um achado"):
        vdi.validar_diagnostico(diag)


def test_nenhum_achado_principal_reprova():
    diag = _diagnostico_prosseguir()
    diag["achados"][0]["papel"] = "secundario"
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[papel\].*exatamente um achado"):
        vdi.validar_diagnostico(diag)


def test_angulo_principal_aponta_para_achado_errado_reprova():
    diag = _diagnostico_prosseguir()
    diag["angulo_principal"]["achado_ref"] = "achado_002"
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[papel\].*não aponta"):
        vdi.validar_diagnostico(diag)


def test_evidencia_reforca_achado_inexistente_reprova():
    diag = _diagnostico_prosseguir()
    diag["achados"][2]["reforca_achado_ref"] = "achado_099"
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[papel\].*não existe entre os achados"):
        vdi.validar_diagnostico(diag)


# --- Violações de referência contra o dossiê de origem -----------------------


def test_fatos_ref_inexistente_no_dossie_reprova():
    diag = _diagnostico_prosseguir()
    diag["achados"][0]["fatos_ref"] = ["fato_099"]
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[referencia\].*fatos_observados do dossiê"):
        vdi.validar_diagnostico(diag, dossie_origem=_dossie_origem())


def test_inferencias_ref_inexistente_no_dossie_reprova():
    diag = _diagnostico_prosseguir()
    diag["achados"][0]["inferencias_ref"] = ["inf_099"]
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[referencia\].*inferencias do dossiê"):
        vdi.validar_diagnostico(diag, dossie_origem=_dossie_origem())


def test_incertezas_ref_inexistente_no_dossie_reprova():
    diag = _diagnostico_prosseguir()
    diag["achados"][0]["incertezas_ref"] = ["inc_099"]
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[referencia\].*incertezas do dossiê"):
        vdi.validar_diagnostico(diag, dossie_origem=_dossie_origem())


def test_sem_angulo_fatos_ref_inexistente_no_dossie_reprova():
    diag = _diagnostico_sem_angulo("COMPLETO_SEM_SITE", fatos_ref=["fato_099"])
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[referencia\].*fatos_observados do dossiê"):
        vdi.validar_diagnostico(diag, dossie_origem=_dossie_origem("COMPLETO_SEM_SITE"))


def test_sem_angulo_evidencias_consideradas_inexistente_reprova():
    diag = _diagnostico_sem_angulo()
    diag["sem_angulo"]["evidencias_consideradas"] = ["fato_099"]
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[referencia\].*nenhum bloco de evidência"):
        vdi.validar_diagnostico(diag, dossie_origem=_dossie_origem())


# --- Eco contra o dossiê de origem -------------------------------------------


def test_place_id_diferente_do_dossie_reprova():
    diag = _diagnostico_prosseguir()
    diag["place_id"] = "OUTRO"
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[origem\].*place_id"):
        vdi.validar_diagnostico(diag, dossie_origem=_dossie_origem())


def test_estagio_analise_diferente_do_dossie_reprova():
    diag = _diagnostico_prosseguir("COMPLETO_COM_SITE")
    with pytest.raises(vdi.DiagnosticoInvalidoError, match=r"\[origem\].*estagio_analise"):
        vdi.validar_diagnostico(diag, dossie_origem=_dossie_origem("COMPLETO_SEM_SITE"))


# --- Acúmulo de múltiplos problemas ------------------------------------------


def test_acumula_multiplos_problemas():
    diag = _diagnostico_prosseguir()
    diag["place_id"] = "OUTRO"
    diag["achados"][0]["fatos_ref"] = ["fato_099"]
    with pytest.raises(vdi.DiagnosticoInvalidoError) as exc_info:
        vdi.validar_diagnostico(diag, dossie_origem=_dossie_origem())
    msg = str(exc_info.value)
    assert "place_id" in msg
    assert "fato_099" in msg


# --- Schema: carregamento -----------------------------------------------------


def test_carregar_schema_diagnostico_padrao():
    schema = vdi.carregar_schema_diagnostico()
    assert schema["title"].startswith("Diagnóstico do Agente 2")


def test_carregar_schema_diagnostico_caminho_inexistente():
    with pytest.raises(vdi.DiagnosticoInvalidoError, match="não encontrado"):
        vdi.carregar_schema_diagnostico(Path("nao/existe.schema.json"))
