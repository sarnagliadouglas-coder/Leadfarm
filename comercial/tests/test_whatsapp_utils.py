"""Testes de whatsapp_utils.py — nenhum envio, nenhuma abertura de WhatsApp,
só montagem de texto. Cada regra: caso que passa, caso que falha, controle
negativo onde fizer sentido."""

import pytest

from whatsapp_utils import link_whatsapp, link_whatsapp_com_mensagem, normalizar_movel_espanhol


# --- normalizar_movel_espanhol --------------------------------------------

@pytest.mark.parametrize("bruto, esperado", [
    ("600000101", "600000101"),
    ("712345678", "712345678"),
    ("+34 600 00 01 01", "600000101"),
    ("0034600000101", "600000101"),
    ("34600000101", "600000101"),
    ("600-000-101", "600000101"),
    ("600.000.101", "600000101"),
    ("(600) 000 101", "600000101"),
])
def test_movel_espanhol_valido_normaliza_para_9_digitos(bruto, esperado):
    assert normalizar_movel_espanhol(bruto) == esperado


@pytest.mark.parametrize("bruto", [
    "912345678",  # fixo (começa 9) -- controle negativo central da regra
    "812345678",  # fixo (começa 8)
    "60000010",   # 8 dígitos, curto demais
    "6000001010", # 10 dígitos, longo demais
    "",
    None,
    "abc",
    "912345678901234",  # numero longo, nao e nem parece celular ES
])
def test_nao_celular_espanhol_devolve_none(bruto):
    assert normalizar_movel_espanhol(bruto) is None


def test_prefixo_mais34_e_prefixo_00_34_dao_o_mesmo_resultado():
    """Controle: as duas formas de prefixo internacional convergem pro
    mesmo número -- nunca duas WhatsApp diferentes pro mesmo lead."""
    assert normalizar_movel_espanhol("+34600000101") == normalizar_movel_espanhol("0034600000101")


# --- link_whatsapp / link_whatsapp_com_mensagem ---------------------------

def test_link_whatsapp_simples():
    assert link_whatsapp("600000101") == "https://wa.me/34600000101"


def test_link_whatsapp_com_mensagem_codifica_acento_interrogacao_e_virgula():
    """As três bordas exigidas: acento, "¿" e vírgula -- todas viram
    percent-encoding, nunca aparecem cruas na URL (o que quebraria o link)."""
    link = link_whatsapp_com_mensagem("600000101", "¿Cómo está, 5,0?")
    assert link.startswith("https://wa.me/34600000101?text=")
    texto_codificado = link.split("?text=", 1)[1]
    assert "¿" not in texto_codificado
    assert "ó" not in texto_codificado
    assert "," not in texto_codificado
    assert " " not in texto_codificado
    assert "%C2%BF" in texto_codificado  # ¿
    assert "%C3%B3" in texto_codificado  # ó
    assert "%2C" in texto_codificado     # ,


def test_link_whatsapp_com_mensagem_decodifica_de_volta_para_o_texto_original():
    """Controle direto: a URL, decodificada, tem que devolver exatamente a
    mensagem original -- prova que a codificação é reversível, não só que
    "parece" codificada."""
    from urllib.parse import unquote

    mensagem = "¿Cómo está, 5,0? Últimas noticias."
    link = link_whatsapp_com_mensagem("600000101", mensagem)
    texto_codificado = link.split("?text=", 1)[1]
    assert unquote(texto_codificado) == mensagem
