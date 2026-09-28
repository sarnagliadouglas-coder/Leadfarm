"""Testes de eqc.py — só a função nova (`diretorio_capturas`, decisão do
diretor, 24/09/2026, MVP de mensagem por modelo fixo). O resto do módulo já
é exercitado indiretamente por `contrato_loader` e pelo `conftest.py`."""

from pathlib import Path

import eqc


def test_diretorio_capturas_env_override_vence(monkeypatch):
    monkeypatch.setenv(eqc.ENV_CAPTURAS_DIR, "/algum/caminho/capturas")
    assert eqc.diretorio_capturas() == Path("/algum/caminho/capturas")


def test_diretorio_capturas_default_fica_dentro_do_qualificador(monkeypatch):
    monkeypatch.delenv(eqc.ENV_CAPTURAS_DIR, raising=False)
    monkeypatch.delenv(eqc.ENV_EQC_ROOT, raising=False)
    monkeypatch.delenv(eqc.ENV_LEADFARM_ROOT, raising=False)
    caminho = eqc.diretorio_capturas()
    partes = caminho.parts
    assert "qualificador" in partes
    assert "capturas_site" in partes
    assert caminho.parent.parent.parent.parent == eqc.eqc_root().parent
