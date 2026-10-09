"""Testes de pendencias_registro.py -- só leitura, dados fictícios, tudo em
tmp_path. Prova nas duas pontas: o que está em dia não é acusado; envio sem
registro e acompanhamento divergente são acusados; nada é escrito."""

import datetime

from openpyxl import Workbook

import pendencias_registro as pr
import registro_abordagens as ra

_FUNIL = {"etapa": ["1º contato"], "resultado": ["sem resposta", "resposta positiva"],
          "mensagem": ["enviada como está"], "decidi_nao_enviar": ["sim"]}
_CAB = ["place_id", "nome", "telefone", "Data 1º contato", "Etapa", "Resultado", "Enviada como",
        "Decidi não enviar", "Canal", "Ângulo", "Variante"]


def _planilha(caminho, linhas):
    wb = Workbook()
    ws = wb.active
    ws.title = "Geral"
    ws.append(_CAB)
    for l in linhas:
        ws.append([l.get(c) for c in _CAB])
    wb.create_sheet("Nata").append(_CAB)
    wb.save(caminho)
    return caminho


def _lead(pid, **over):
    base = {"place_id": pid, "nome": f"Clínica Ficticia {pid}", "telefone": "600000101",
            "Data 1º contato": datetime.datetime(2026, 9, 25), "Etapa": "1º contato", "Canal": "whatsapp",
            "Ângulo": "sem_site", "Variante": "A"}
    base.update(over)
    return base


def _registrar(tmp_path, planilha):
    ra.registrar_envios(planilha, diretorio_registro=tmp_path / "_abordagens", opcoes_funil=_FUNIL)
    return ra.caminho_registro(tmp_path / "_abordagens")


def test_nada_pendente_quando_registro_bate_com_a_planilha(tmp_path):
    planilha = _planilha(tmp_path / "p.xlsx", [_lead("p1"), _lead("p2")])
    registro = _registrar(tmp_path, planilha)
    r = pr.pendencias(planilha, registro)
    assert r == {"nao_registrados": [], "eventos_nao_registrados": [], "divergentes": []}
    assert pr.main([str(planilha), "--registro", str(registro)]) == 0


def test_envio_sem_registro_e_acusado(tmp_path):
    planilha = _planilha(tmp_path / "p.xlsx", [_lead("p1")])
    registro = _registrar(tmp_path, planilha)
    planilha2 = _planilha(tmp_path / "p2.xlsx", [_lead("p1"), _lead("p9")])
    r = pr.pendencias(planilha2, registro)
    assert [x["place_id"] for x in r["nao_registrados"]] == ["p9"]
    assert pr.main([str(planilha2), "--registro", str(registro)]) == 1


def test_resultado_preenchido_depois_do_registro_e_acusado(tmp_path):
    """O caso real que motivou o comando: o diretor preenche Resultado na
    planilha depois que o envio já foi registrado. Desde o funil por eventos
    (diretor, 08/10/2026) é uma mudança a registrar, não uma divergência --
    e depois de registrada não é mais acusada."""
    planilha = _planilha(tmp_path / "p.xlsx", [_lead("p1"), _lead("p2")])
    registro = _registrar(tmp_path, planilha)
    depois = _planilha(tmp_path / "p_depois.xlsx", [_lead("p1", Resultado="resposta positiva"), _lead("p2")])
    r = pr.pendencias(depois, registro)
    assert r["nao_registrados"] == []
    assert r["divergentes"] == []
    assert r["eventos_nao_registrados"] == [{
        "place_id": "p1", "nome": "Clínica Ficticia p1", "coluna": "Resultado",
        "no_registro": "", "na_planilha": "resposta positiva",
    }]
    assert pr.main([str(depois), "--registro", str(registro)]) == 1
    _registrar(tmp_path, depois)
    assert pr.pendencias(depois, registro) == {"nao_registrados": [], "eventos_nao_registrados": [], "divergentes": []}
    assert pr.main([str(depois), "--registro", str(registro)]) == 0


def test_resultado_apagado_e_outras_colunas_continuam_divergencia(tmp_path):
    """Controle negativo: só Resultado NOVO preenchido vira evento. Resultado
    apagado na planilha e Etapa diferente seguem para o diretor decidir."""
    planilha = _planilha(tmp_path / "p.xlsx", [_lead("p1", Resultado="resposta positiva")])
    registro = _registrar(tmp_path, planilha)
    depois = _planilha(tmp_path / "p_depois.xlsx", [_lead("p1", Resultado=None, Etapa="follow-up 1")])
    r = pr.pendencias(depois, registro)
    assert r["eventos_nao_registrados"] == []
    assert {d["coluna"] for d in r["divergentes"]} == {"Resultado", "Etapa"}
    assert pr.main([str(depois), "--registro", str(registro)]) == 1


def test_linha_sem_envio_nem_decisao_nao_e_pendencia(tmp_path):
    planilha = _planilha(tmp_path / "p.xlsx", [_lead("p1", **{"Data 1º contato": None, "Etapa": None})])
    r = pr.pendencias(planilha, tmp_path / "registro_inexistente.xlsx")
    assert r == {"nao_registrados": [], "eventos_nao_registrados": [], "divergentes": []}


def test_nunca_escreve_nem_na_planilha_nem_no_registro(tmp_path):
    planilha = _planilha(tmp_path / "p.xlsx", [_lead("p1")])
    registro = _registrar(tmp_path, planilha)
    depois = _planilha(tmp_path / "p_depois.xlsx", [_lead("p1", Resultado="sem resposta"), _lead("p7")])
    antes = (depois.read_bytes(), registro.read_bytes())
    pr.main([str(depois), "--registro", str(registro)])
    assert (depois.read_bytes(), registro.read_bytes()) == antes


def test_planilha_ausente_da_exit_2(tmp_path):
    assert pr.main([str(tmp_path / "nao_existe.xlsx"), "--registro", str(tmp_path / "r.xlsx")]) == 2


def test_sem_argumento_usa_a_planilha_mais_recente_do_diretorio(tmp_path, monkeypatch):
    _planilha(tmp_path / "planilha_envio_20260101-000000.xlsx", [_lead("p1")])
    _planilha(tmp_path / "planilha_envio_20260927-134806.xlsx", [_lead("p2")])
    assert pr.planilha_mais_recente(tmp_path).name == "planilha_envio_20260927-134806.xlsx"
    monkeypatch.setenv(pr.ENV_PLANILHAS_DIR, str(tmp_path))
    assert pr.main(["--registro", str(tmp_path / "r.xlsx")]) == 1  # p2 sem registro


def test_sem_argumento_le_o_diretorio_do_comercial_env(tmp_path, monkeypatch, capsys):
    """COMERCIAL_PLANILHAS_DIR vindo só de comercial/.env (não do ambiente)
    precisa valer -- é onde o diretor configura a pasta da planilha em uso."""
    import env_loader

    pasta = tmp_path / "Resultado"
    pasta.mkdir()
    _planilha(pasta / "planilha_envio_20260927-134806.xlsx", [_lead("p2")])
    env = tmp_path / ".env"
    env.write_text(f'{pr.ENV_PLANILHAS_DIR}="{pasta}"\n', encoding="utf-8")
    monkeypatch.setattr(env_loader, "_ENV_PATH", env)
    monkeypatch.setenv(pr.ENV_PLANILHAS_DIR, "x")  # registra o original para o undo
    monkeypatch.delenv(pr.ENV_PLANILHAS_DIR)
    assert pr.main(["--registro", str(tmp_path / "r.xlsx")]) == 1
    assert str(pasta / "planilha_envio_20260927-134806.xlsx") in capsys.readouterr().out
