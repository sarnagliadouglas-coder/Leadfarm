"""
Testes de validador_dossie.py — mesmo padrão de rigor de test_contrato_loader.py.
"""

import copy
import sys
from pathlib import Path

import pytest

FERRAMENTAS_DIR = Path(__file__).resolve().parent.parent / "ferramentas"
sys.path.insert(0, str(FERRAMENTAS_DIR))

import validador_dossie as vd  # noqa: E402


# --- Fixtures --------------------------------------------------------------


def _lead_origem() -> dict:
    return {
        "place_id": "PLACE123",
        "estagio_analise": "COMPLETO_COM_SITE",
        "reputacao": {
            "nota_google": {"valor": 4.5, "estado": "CONFIRMADO_PRESENTE"},
            "review_count": {"valor": 10, "estado": "CONFIRMADO_PRESENTE"},
            "reputation_signal": "strong",
        },
    }


def _dossie_valido() -> dict:
    return {
        "schema_version": "2.0",
        "place_id": "PLACE123",
        "lote_origem": "leads_qualificados_20260908-074342_v1.1.0.json",
        "investigado_em": "2026-09-08T10:00:00Z",
        "modelo": "claude-sonnet-5",
        "escalonamento": {"ocorreu": False, "motivo": None},
        "status_investigacao": "parcial",
        "negocio": {
            "nome": "Negócio Teste",
            "nicho": "Categoria",
            "localizacao": "Cidade",
            "servicos_principais": [],
            "website": "https://teste.es",
            "google_maps_url": "https://maps.google.com/?cid=1",
            "rating_coletado": {"valor": 4.5, "estado": "CONFIRMADO_PRESENTE"},
            "total_avaliacoes_coletado": {"valor": 10, "estado": "CONFIRMADO_PRESENTE"},
            "rating_verificado": 4.5,
            "total_avaliacoes_verificado": 10,
            "redes_sociais": {"instagram": None, "facebook": None, "linkedin": None},
            "canais_de_contato": [],
            "divergencias_com_qualificador": [],
        },
        "presenca_digital": {
            "website": "funcional",
            "mobile": "adequado",
            "desktop": "adequado",
            "https": True,
            "gbp": "ativo_incompleto",
            "caminho_para_contato": "claro",
            "carregamento_percebido": "nao_avaliado",
        },
        "fatos_observados": [
            {
                "id": "fato_001",
                "categoria": "identidade_negocio",
                "natureza": "neutro",
                "afirmacao": "A homepage descreve o negócio.",
                "dispositivo": "ambos",
                "confianca": "alta",
                "fontes_ref": ["fonte_001"],
            }
        ],
        "fontes_dos_fatos": [
            {"id": "fonte_001", "tipo": "url", "local": "https://teste.es", "como_verificado": "Leitura da homepage."}
        ],
        "inferencias": [],
        "incertezas": [],
        "dados_nao_encontrados": [],
        "por_dispositivo": {
            "mobile": {"funcionamento": "ok", "fatos_ref": ["fato_001"]},
            "desktop": {"funcionamento": "ok", "fatos_ref": []},
        },
        "jornada_principal": {
            "entrada": "https://teste.es",
            "etapas": [],
            "resultado": "nao_testavel",
            "onde_interrompeu": None,
            "caminhos_alternativos": [],
        },
        "qualificador": {
            "sinais_recebidos": {
                "estagio_analise": "COMPLETO_COM_SITE",
                "evidencias_qualificador": {"fatos": []},
                "priorizacao_nao_autoritativa": {
                    "commercial_fit_score": 50,
                    "priority_label": None,
                    "reasons": [],
                },
            },
            "procedencia": [],
        },
    }


# --- Caminho válido ----------------------------------------------------


def test_dossie_valido_passa_com_lead_origem():
    vd.validar_dossie(_dossie_valido(), lead_origem=_lead_origem())  # não levanta


def test_dossie_valido_passa_sem_lead_origem():
    """Sem lead_origem, as checagens de place_id/eco são puladas -- não é erro."""
    vd.validar_dossie(_dossie_valido())  # não levanta


# --- Conformidade de schema ----------------------------------------------


def test_campo_obrigatorio_ausente_falha():
    dossie = _dossie_valido()
    del dossie["modelo"]

    with pytest.raises(vd.DossieInvalidoError, match=r"\[schema\]"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_modelo_fora_do_enum_falha():
    dossie = _dossie_valido()
    dossie["modelo"] = "gpt-4"

    with pytest.raises(vd.DossieInvalidoError, match=r"\[schema\]"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_consequencia_observavel_ausente_em_problema_falha():
    dossie = _dossie_valido()
    dossie["fatos_observados"][0]["natureza"] = "problema"
    # consequencia_observavel ausente

    with pytest.raises(vd.DossieInvalidoError, match=r"\[schema\]"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_consequencia_observavel_presente_em_nao_problema_falha():
    dossie = _dossie_valido()
    dossie["fatos_observados"][0]["consequencia_observavel"] = "não deveria estar aqui"
    # natureza continua "neutro"

    with pytest.raises(vd.DossieInvalidoError, match=r"\[schema\]"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_escalonamento_ocorreu_sem_motivo_falha():
    dossie = _dossie_valido()
    dossie["escalonamento"] = {"ocorreu": True, "motivo": None}

    with pytest.raises(vd.DossieInvalidoError, match=r"\[schema\]"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


# --- Referência cruzada ----------------------------------------------------


def test_fonte_ref_inexistente_falha():
    dossie = _dossie_valido()
    dossie["fatos_observados"][0]["fontes_ref"] = ["fonte_999"]

    with pytest.raises(vd.DossieInvalidoError, match=r"fontes_ref aponta para 'fonte_999'"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_baseada_em_inexistente_falha():
    dossie = _dossie_valido()
    dossie["inferencias"] = [
        {"id": "inf_001", "afirmacao": "conclusão qualquer", "baseada_em": ["fato_999"], "confianca": "media"}
    ]

    with pytest.raises(vd.DossieInvalidoError, match=r"baseada_em aponta para 'fato_999'"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_por_dispositivo_fatos_ref_inexistente_falha():
    dossie = _dossie_valido()
    dossie["por_dispositivo"]["mobile"]["fatos_ref"] = ["fato_999"]

    with pytest.raises(vd.DossieInvalidoError, match=r"por_dispositivo\.mobile\.fatos_ref"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_jornada_fato_ref_inexistente_falha():
    dossie = _dossie_valido()
    dossie["jornada_principal"]["etapas"] = [
        {"etapa": "Homepage", "resultado": "ok", "fato_ref": "fato_999"}
    ]

    with pytest.raises(vd.DossieInvalidoError, match=r"jornada_principal\.etapas\[0\]\.fato_ref"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_qualificador_procedencia_fatos_ref_inexistente_falha():
    dossie = _dossie_valido()
    dossie["qualificador"]["procedencia"] = [
        {
            "origem": "qualificador", "insumo_usado": "x",
            "o_que_foi_investigado": "y", "o_que_foi_encontrado": "z",
            "relevancia_comercial": "n/a", "fatos_ref": ["fato_999"],
        }
    ]

    with pytest.raises(vd.DossieInvalidoError, match=r"qualificador\.procedencia\[0\]\.fatos_ref"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_inferencia_referenciada_como_fato_falha_no_schema():
    """Regra 9: um id de `inferencias` nunca pode aparecer onde o schema
    espera um `fato_observado` -- o padrão '^fato_' do JSON Schema já barra
    isso antes mesmo da checagem de referência rodar."""
    dossie = _dossie_valido()
    dossie["por_dispositivo"]["mobile"]["fatos_ref"] = ["inf_001"]

    with pytest.raises(vd.DossieInvalidoError, match=r"\[schema\]"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


# --- Divergências com o qualificador ---------------------------------------


def test_divergencia_com_campo_invalido_falha():
    dossie = _dossie_valido()
    dossie["negocio"]["divergencias_com_qualificador"] = [
        {
            "campo": "campo_que_nao_existe",
            "valor_coletado": "x",
            "valor_verificado": "y",
            "observacao": "qualquer",
        }
    ]

    with pytest.raises(vd.DossieInvalidoError, match=r"não é um campo reconhecido"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_divergencia_com_campo_valido_passa():
    dossie = _dossie_valido()
    dossie["negocio"]["divergencias_com_qualificador"] = [
        {
            "campo": "nicho",
            "valor_coletado": "Centro médico",
            "valor_verificado": "Odontologia",
            "observacao": "QUALIFICADOR classificou diferente do site.",
        }
    ]

    vd.validar_dossie(dossie, lead_origem=_lead_origem())  # não levanta


# --- Contra o lead de origem -------------------------------------------


def test_place_id_diferente_do_lead_origem_falha():
    dossie = _dossie_valido()
    dossie["place_id"] = "PLACE_ERRADO"

    with pytest.raises(vd.DossieInvalidoError, match=r"place_id do dossiê"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_rating_coletado_nao_e_eco_fiel_falha():
    """rating_coletado é eco, não recálculo -- divergência aqui é bug do A1."""
    dossie = _dossie_valido()
    dossie["negocio"]["rating_coletado"] = {"valor": 3.0, "estado": "CONFIRMADO_PRESENTE"}

    with pytest.raises(vd.DossieInvalidoError, match=r"rating_coletado.*não bate com"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_total_avaliacoes_coletado_nao_e_eco_fiel_falha():
    dossie = _dossie_valido()
    dossie["negocio"]["total_avaliacoes_coletado"] = {"valor": 999, "estado": "CONFIRMADO_PRESENTE"}

    with pytest.raises(vd.DossieInvalidoError, match=r"total_avaliacoes_coletado.*não bate com"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


def test_estado_diferente_tambem_conta_como_divergencia_do_eco():
    """Eco fiel inclui o ESTADO, não só o valor -- {valor:4.5, estado:NAO_VERIFICADO}
    não é o mesmo eco que {valor:4.5, estado:CONFIRMADO_PRESENTE}."""
    dossie = _dossie_valido()
    dossie["negocio"]["rating_coletado"] = {"valor": 4.5, "estado": "NAO_VERIFICADO"}

    with pytest.raises(vd.DossieInvalidoError, match=r"rating_coletado"):
        vd.validar_dossie(dossie, lead_origem=_lead_origem())


# --- Acumula problemas, não para no primeiro -------------------------------


def test_acumula_multiplos_problemas_numa_so_excecao():
    dossie = _dossie_valido()
    dossie["place_id"] = "PLACE_ERRADO"
    dossie["fatos_observados"][0]["fontes_ref"] = ["fonte_999"]
    dossie["negocio"]["divergencias_com_qualificador"] = [
        {"campo": "invalido", "valor_coletado": "a", "valor_verificado": "b", "observacao": "c"}
    ]

    with pytest.raises(vd.DossieInvalidoError) as exc:
        vd.validar_dossie(dossie, lead_origem=_lead_origem())

    texto = str(exc.value)
    assert "place_id do dossiê" in texto
    assert "fontes_ref aponta para 'fonte_999'" in texto
    assert "não é um campo reconhecido" in texto
    assert "3 problema(s)" in texto


# --- Schema/carregamento ----------------------------------------------------


def test_schema_dossie_arquivo_existe_e_carrega():
    schema = vd.carregar_schema_dossie()
    assert schema["title"].startswith("Dossiê do Agente 1")


def test_schema_ausente_falha_alto(tmp_path):
    with pytest.raises(vd.DossieInvalidoError, match="não encontrado"):
        vd.carregar_schema_dossie(tmp_path / "nao_existe.schema.json")
