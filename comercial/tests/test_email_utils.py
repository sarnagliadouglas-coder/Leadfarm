"""Testes de email_utils.py — nenhum envio de e-mail, só monta o link
`mailto:` (coluna "Abrir e-mail", decisão do diretor, 24/09/2026, quarta
rodada)."""

import json

import pytest

from email_utils import (
    ConfigAssuntoEmailInvalidaError,
    carregar_assuntos_email,
    link_mailto,
)


def test_sem_email_devolve_string_vazia():
    assert link_mailto(None, "Asunto", "Mensaje") == ""
    assert link_mailto("", "Asunto", "Mensaje") == ""


def test_com_email_monta_o_link_mailto():
    link = link_mailto("cliente@ejemplo.es", "Asunto", "Mensaje")
    assert link.startswith("mailto:cliente@ejemplo.es?subject=")
    assert "&body=" in link


def test_acento_interrogacao_e_quebra_de_linha_sao_codificados():
    """Controle central: acento, "¿" e quebra de linha nunca vazam crus para
    a URL -- tudo percent-encoded."""
    link = link_mailto("cliente@ejemplo.es", "Una observación", "¿Le interesa?\nGracias.")
    assert " " not in link
    assert "¿" not in link
    assert "\n" not in link
    assert "%C2%BF" in link  # "¿" percent-encoded
    assert "%0A" in link  # quebra de linha percent-encoded
    assert "%C3%B3n" in link  # "ó" de "observación" percent-encoded


def test_mensagem_vazia_ou_none_nao_quebra():
    assert link_mailto("cliente@ejemplo.es", "Asunto", "") != ""
    assert link_mailto("cliente@ejemplo.es", "Asunto", None) != ""


def test_carregar_assuntos_email_le_o_arquivo_real():
    config = carregar_assuntos_email()
    assert "direta" in config
    assert "nata" in config


def test_carregar_assuntos_email_arquivo_ausente_levanta_erro_claro(tmp_path):
    with pytest.raises(ConfigAssuntoEmailInvalidaError, match="não encontrada"):
        carregar_assuntos_email(tmp_path / "nao-existe.json")


def test_carregar_assuntos_email_json_invalido_levanta_erro_claro(tmp_path):
    caminho = tmp_path / "a.json"
    caminho.write_text("{ nao e json", encoding="utf-8")
    with pytest.raises(ConfigAssuntoEmailInvalidaError, match="JSON válido"):
        carregar_assuntos_email(caminho)


def test_carregar_assuntos_email_sem_chaves_exigidas_levanta_erro_claro(tmp_path):
    caminho = tmp_path / "a.json"
    caminho.write_text(json.dumps({"direta": "x"}), encoding="utf-8")
    with pytest.raises(ConfigAssuntoEmailInvalidaError):
        carregar_assuntos_email(caminho)
