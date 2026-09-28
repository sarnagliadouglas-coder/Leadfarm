"""Resolução do campo interno `telefone` a partir das colunas Phone / Phones do CSV do
EXTRATOR (agent_coletor._resolver_telefone) + a regra de celular espanhol consolidada
(telefone_utils), antes duplicada em lead_qualification e output_json._contato.
"""
import lead_qualification as lq
import output_json as oj
import telefone_utils as tu
from agent_coletor import AgentColetor


def _linha(**over):
    linha = {"Name": "Clínica Ejemplo", "Phone": "", "Phones": "",
             "Categories": "Clínica Dental", "Place Id": "p1"}
    linha.update(over)
    return linha


# --- BUGFIX: Phones plural não pode ser concatenado antes de checar o prefixo ---------------

def test_phone_singular_tem_prioridade():
    assert AgentColetor._resolver_telefone(_linha(Phone="960000104", Phones="612345678")) == "960000104"


def test_phones_plural_escolhe_o_primeiro_candidato_que_e_celular():
    # Caso relatado: Phone vazio, Phones = "9xx..., 6xx...". Antes, a normalização
    # concatenava os dígitos ("960000104612345678") e checava o primeiro -> "9" -> fixo.
    linha = _linha(Phone="", Phones="960000104, 612345678")
    tel = AgentColetor._resolver_telefone(linha)
    assert tel == "612345678"
    assert tu.e_movel_espanhol(tel) is True


def test_phones_com_espacos_dentro_do_numero_nao_quebra_o_candidato():
    linha = _linha(Phone="", Phones="960 00 01 04, 612 34 56 78")
    assert AgentColetor._resolver_telefone(linha) == "612 34 56 78"


def test_phones_sem_nenhum_celular_cai_no_primeiro_candidato():
    linha = _linha(Phone="", Phones="960000104 ; 860000105")
    assert AgentColetor._resolver_telefone(linha) == "960000104"


def test_phones_valor_unico_preserva_comportamento_historico():
    assert AgentColetor._resolver_telefone(_linha(Phones="612345678")) == "612345678"


def test_sem_phone_nem_phones_devolve_none():
    assert AgentColetor._resolver_telefone(_linha()) is None


def test_montar_lead_usa_o_celular_do_phones_plural():
    lead = AgentColetor._montar_lead(_linha(Phone="", Phones="960000104, 612345678"))
    assert lead["telefone"] == "612345678"


# --- CONSOLIDAÇÃO: uma regra só, dois pontos de uso ---------------------------------------

def test_lead_qualification_e_output_json_concordam_com_telefone_utils():
    for numero in ["612345678", "+34 612 34 56 78", "0034612345678", "700000102",
                   "960000105", "860000105", "", None, "34612345678"]:
        esperado = tu.e_movel_espanhol(numero)
        # lead_qualification expõe wrappers finos por compat
        assert lq._e_movel_espanhol(numero) is esperado
        # output_json._contato deriva whatsapp_apto da mesma função
        emp = {"telefone": numero, "email": None, "instagram": None, "facebook": None}
        assert oj._contato(emp)["whatsapp_apto"] is esperado
