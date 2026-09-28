"""Fase de renderizacao (Etapa C, passo C4). SEM REDE EXTERNA.

Quase tudo aqui usa um Playwright FALSO e um medidor falso: prova a logica da fase (desligada,
selecao, degradacao, tentativas, retomada) sem navegador e sem rede. Um teste de ponta a ponta usa
Chromium real contra o servidor local 127.0.0.1 (fixtures `pw`/`base_url`, no conftest.py)
e e PULADO, com motivo, se nao houver navegador.
"""
import copy
import json
import os
import sys
from pathlib import Path

import pytest

import main as main_mod
import output_json
import site_classificacao as scl
import site_renderizado as sr
import wave2_scoring
from test_output_json import _com_site

PROPRIO = "https://clinica-um.es"


def _reg(place_id, website, status="analyzed", **extra):
    emp = {"place_id": place_id, "nome": f"Lead {place_id}", "website": website, "website_status": "listed",
           "cidade": "Cartagena", "nicho": "Fisioterapeuta", "nota_google": 4.5, "review_count": 40,
           "telefone": "612345678", "email": None, "instagram": None, "facebook": None, "linkedin": None,
           "endereco": "Calle 1", "reputation_signal": "strong", "google_maps_url": "https://maps.google.com/?cid=1"}
    emp.update(extra)
    return {"dados_empresa": emp, "status": status}


def _grava(leads):
    main_mod.salvar_json(main_mod.PATH_COM_SITE, leads)


def _le():
    return main_mod.carregar_json(main_mod.PATH_COM_SITE)


def _por_id():
    return {l["dados_empresa"]["place_id"]: l for l in _le()}


def _bloco(pid):
    return _por_id()[pid].get("site_renderizado")


def _bytes():
    return Path(main_mod.PATH_COM_SITE).read_bytes()


# --- Playwright e medidor FALSOS ------------------------------------------------------------------

class _Navegador:
    def close(self):
        pass


class _Chromium:
    def __init__(self, falha=None):
        self.falha = falha

    def launch(self, headless=True):
        if self.falha:
            raise self.falha
        return _Navegador()


class _PW:
    def __init__(self, falha=None):
        self.chromium = _Chromium(falha)


class _Contexto:
    def __init__(self, pw_falso=None, falha_ao_entrar=None):
        self.pw, self.falha_ao_entrar, self.saiu, self.entrou = pw_falso or _PW(), falha_ao_entrar, False, False

    def __enter__(self):
        if self.falha_ao_entrar:
            raise self.falha_ao_entrar
        self.entrou = True
        return self.pw

    def __exit__(self, *a):
        self.saiu = True
        return False


@pytest.fixture
def ligada(monkeypatch):
    monkeypatch.setenv("RENDER_ENABLED", "1")


def _ambiente(monkeypatch, contexto=None):
    contexto = contexto or _Contexto()
    monkeypatch.setattr(sr, "abrir_playwright", lambda: contexto)
    return contexto


def _ficha(mobile=None, desktop=None):
    def disp(extra):
        base = {"status": "ok", "http_status": 200, "erro_tipo": None, "antibot_casou": None,
                "screenshot_ref": None, "coletado_em": "2026-09-20T12:00:00Z"}
        base.update(extra or {})
        return base
    return {"lead_id": "?", "website": "?", "gerado_em": "2026-09-20T12:00:01Z",
            "por_dispositivo": {"mobile": disp(mobile), "desktop": disp(desktop)}}


class _Medidor:
    """Substitui site_renderizado.processar_lead. Registra chamadas e concorrencia."""

    def __init__(self, respostas=None, padrao=None, ao_entrar=None):
        self.chamadas, self.respostas, self.padrao, self.ao_entrar = [], respostas or {}, padrao or _ficha(), ao_entrar
        self.em_andamento = self.max_concorrencia = 0
        self.pastas = []

    def __call__(self, playwright, lead_id, website, pasta):
        self.em_andamento += 1
        self.max_concorrencia = max(self.max_concorrencia, self.em_andamento)
        try:
            self.chamadas.append(lead_id)
            self.pastas.append(pasta)
            if self.ao_entrar:
                self.ao_entrar(lead_id)
            r = self.respostas.get(lead_id, self.padrao)
            if callable(r):
                r = r()
            if isinstance(r, BaseException):
                raise r
            ficha = copy.deepcopy(r)
            ficha["lead_id"], ficha["website"] = lead_id, website
            return ficha
        finally:
            self.em_andamento -= 1


def _medidor(monkeypatch, **kw):
    m = _Medidor(**kw)
    monkeypatch.setattr(sr, "processar_lead", m)
    return m


def _proibe_navegador(monkeypatch):
    def tocou(*a, **k):
        raise AssertionError("tocou no Playwright/navegador")
    monkeypatch.setattr(sr, "abrir_playwright", tocou)
    monkeypatch.setattr(sr, "processar_lead", tocou)


# ==================================================================================================
# 1. DESLIGADA: nao muda nada
# ==================================================================================================

def test_desligada_por_padrao_nao_le_nem_grava_nem_abre_navegador(monkeypatch, capsys):
    monkeypatch.delenv("RENDER_ENABLED", raising=False)
    _grava([_reg("a", PROPRIO), _reg("b", "https://www.doctoralia.es/x")])
    antes = _bytes()
    _proibe_navegador(monkeypatch)

    assert main_mod.fase_render() is None

    assert _bytes() == antes                                          # nem um byte do registro mudou
    assert not os.path.exists(main_mod._pasta_capturas())            # nenhuma pasta de capturas
    assert "não ligado" in capsys.readouterr().out


def test_desligada_nem_le_o_arquivo_de_dados(monkeypatch):
    monkeypatch.delenv("RENDER_ENABLED", raising=False)
    monkeypatch.setattr(main_mod, "carregar_json", lambda *a: (_ for _ in ()).throw(AssertionError("leu dados")))
    assert main_mod.fase_render() is None


def _fase_all_com_fases_falsas(monkeypatch, tmp_path):
    for nome in ("PATH_COLETADOS", "PATH_QUALIFICADOS", "PATH_REPROVADOS"):
        Path(getattr(main_mod, nome)).write_text("[]", encoding="utf-8")
    chamadas = []
    monkeypatch.setattr(main_mod, "fase_gbp", lambda: chamadas.append("gbp"))
    monkeypatch.setattr(main_mod, "fase_qualify", lambda: chamadas.append("qualify") or {"custo_total_usd": 0.0})
    monkeypatch.setattr(main_mod, "fase_wave2", lambda: chamadas.append("wave2") or {"avaliados": 0})
    monkeypatch.setattr(main_mod, "fase_psi", lambda: chamadas.append("psi"))
    monkeypatch.setattr(main_mod, "fase_render", lambda: chamadas.append("render"))
    monkeypatch.setattr(main_mod, "fase_saida", lambda: chamadas.append("saida"))
    return chamadas


def test_fase_all_desligada_nem_chama_a_fase_nem_escreve_no_console(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("RENDER_ENABLED", raising=False)
    chamadas = _fase_all_com_fases_falsas(monkeypatch, tmp_path)
    main_mod.fase_all()
    assert chamadas == ["gbp", "qualify", "wave2", "psi", "saida"]
    saida = capsys.readouterr().out
    assert "RENDER" not in saida and "[Render]" not in saida          # zero mudanca ate no console


def test_fase_all_ligada_chama_depois_da_wave2_e_do_psi_e_antes_da_saida(monkeypatch, tmp_path, ligada):
    chamadas = _fase_all_com_fases_falsas(monkeypatch, tmp_path)
    main_mod.fase_all()
    assert chamadas == ["gbp", "qualify", "wave2", "psi", "render", "saida"]


def test_o_contrato_de_saida_transporta_apenas_os_sinais_do_bloco():
    sem = _com_site()
    com = _com_site()
    com["site_renderizado"] = {"estado": "medido", "resultado": {"por_dispositivo": {"mobile": {"status": "ok"}}}}
    a = output_json.montar([], [sem], [])
    b = output_json.montar([], [com], [])
    assert a["candidatos_triagem"] and b["candidatos_triagem"]
    assert "site_renderizado" not in json.dumps(b)
    assert "telefone_na_pagina" in json.dumps(b)


def test_o_comando_render_do_cli_chama_a_fase(monkeypatch):
    chamou = []
    monkeypatch.setattr(main_mod.env_loader, "carregar_env", lambda: [])
    monkeypatch.setattr(main_mod, "fase_render", lambda: chamou.append(1))
    monkeypatch.setattr(sys, "argv", ["main.py", "render"])
    main_mod.run()
    assert chamou == [1]


def test_as_capturas_ficam_sob_o_data_dir_isolado_da_suite(tmp_path):
    assert main_mod._pasta_capturas() == os.path.join(str(tmp_path), "capturas_site")


# ==================================================================================================
# 2. SELECAO: so "proprio"; o resto e PULADO com motivo, nao e erro
# ==================================================================================================

def test_so_mede_leads_de_classe_proprio_e_registra_o_motivo_dos_pulados(monkeypatch, ligada):
    sem_id = _reg("sem_id", "https://outra-clinica.es")
    sem_id["dados_empresa"]["place_id"] = None
    _grava([
        _reg("proprio", PROPRIO),
        _reg("portal", "https://www.doctoralia.es/x"),
        _reg("construtor", "https://clinica.wixsite.com/x"),
        _reg("rede", "https://www.instagram.com/clinica"),
        _reg("google", "https://g.page/clinica"),
        _reg("sem_site", "N/A"),
        sem_id,
    ])
    _ambiente(monkeypatch)
    medidor = _medidor(monkeypatch)

    r = main_mod.fase_render()

    assert medidor.chamadas == ["proprio"]
    assert _bloco("proprio")["estado"] == "medido"
    esperado = {"portal": "classe_site:portal", "construtor": "classe_site:construtor",
                "rede": "classe_site:rede_social", "google": "classe_site:superficie_google",
                "sem_site": "classe_site:sem_site"}
    for pid, motivo in esperado.items():
        b = _bloco(pid)
        assert b["estado"] == "pulado" and b["motivo"] == motivo and b["resultado"] is None, pid
    bloco_sem_id = [l for l in _le() if l["dados_empresa"]["place_id"] is None][0]["site_renderizado"]
    assert bloco_sem_id["estado"] == "pulado" and bloco_sem_id["motivo"] == "sem_place_id"
    assert r["pulado"] == 6 and r["medido"] == 1
    assert all(b["site_renderizado"]["estado"] != "erro" for b in _le())    # pular nao e erro


def test_classe_gravada_na_importacao_vale_e_a_ausente_e_recalculada(monkeypatch, ligada):
    _grava([
        _reg("gravada", PROPRIO, classe_site="portal"),          # classe gravada (C1) manda
        _reg("antiga", "https://www.booksy.com/x"),               # registro anterior ao C1: recalcula (portal)
    ])
    _ambiente(monkeypatch)
    medidor = _medidor(monkeypatch)
    main_mod.fase_render()
    assert medidor.chamadas == []
    assert _bloco("gravada")["motivo"] == "classe_site:portal"
    assert _bloco("antiga")["motivo"] == "classe_site:portal"


def test_pulado_volta_para_a_fila_quando_a_classe_passa_a_proprio(monkeypatch, ligada):
    _grava([_reg("x", "https://www.doctoralia.es/x")])
    _ambiente(monkeypatch)
    medidor = _medidor(monkeypatch)
    main_mod.fase_render()
    assert _bloco("x")["estado"] == "pulado" and medidor.chamadas == []
    leads = _le()
    leads[0]["dados_empresa"]["website"] = PROPRIO                # o site do lead mudou / a lista foi corrigida
    _grava(leads)
    main_mod.fase_render()
    assert medidor.chamadas == ["x"] and _bloco("x")["estado"] == "medido"


def test_so_pulados_nao_abre_navegador_nem_cria_pasta(monkeypatch, ligada):
    _grava([_reg("p", "https://www.doctoralia.es/x"), _reg("q", "https://g.page/y")])
    _proibe_navegador(monkeypatch)
    r = main_mod.fase_render()
    assert r == {"medido": 0, "pulado": 2}
    assert not os.path.exists(main_mod._pasta_capturas())


def test_nada_pendente_nao_abre_navegador(monkeypatch, ligada):
    _grava([_reg("a", PROPRIO)])
    _ambiente(monkeypatch)
    _medidor(monkeypatch)
    main_mod.fase_render()
    _proibe_navegador(monkeypatch)                                # 2a rodada: tudo terminal
    assert main_mod.fase_render() is None


# ==================================================================================================
# 3. DEGRADACAO HONESTA: ambiente sem Playwright/navegador
# ==================================================================================================

def test_sem_playwright_marca_nao_verificado_com_motivo_e_nao_gasta_tentativa(monkeypatch, ligada, capsys):
    _grava([_reg("a", PROPRIO), _reg("b", "https://clinica-dois.es"), _reg("c", "https://www.doctoralia.es/x")])

    def sem_playwright():
        raise sr.PlaywrightIndisponivelError("Playwright nao esta instalado (pip install playwright && playwright install chromium)")
    monkeypatch.setattr(sr, "abrir_playwright", sem_playwright)
    monkeypatch.setattr(sr, "processar_lead", lambda *a, **k: (_ for _ in ()).throw(AssertionError("mediu sem navegador")))

    r = main_mod.fase_render()

    assert r["ambiente_indisponivel"] == "playwright_indisponivel" and r["medido"] == 0
    for pid in ("a", "b"):
        b = _bloco(pid)
        assert b["estado"] == "nao_verificado" and b["motivo"] == "playwright_indisponivel"
        assert b["tentativas"] == 0 and b["resultado"] is None
        assert "playwright install chromium" in b["detalhe"]           # o que fazer, nao erro cru
    assert _bloco("c")["estado"] == "pulado"                          # o pulo nao depende do ambiente
    assert not any(l["site_renderizado"]["estado"] == "medido" for l in _le())
    assert not os.path.exists(main_mod._pasta_capturas())
    saida = capsys.readouterr().out
    assert "INDISPONÍVEL" in saida and "playwright_indisponivel" in saida


def test_ambiente_que_volta_mede_e_a_rodada_sem_ambiente_nao_gastou_tentativa(monkeypatch, ligada):
    _grava([_reg("a", PROPRIO)])
    monkeypatch.setattr(sr, "abrir_playwright", lambda: (_ for _ in ()).throw(sr.PlaywrightIndisponivelError("x")))
    main_mod.fase_render()
    main_mod.fase_render()                                             # duas rodadas sem ambiente
    assert _bloco("a")["tentativas"] == 0
    _ambiente(monkeypatch)
    _medidor(monkeypatch)
    main_mod.fase_render()
    assert _bloco("a")["estado"] == "medido" and _bloco("a")["tentativas"] == 1


def test_playwright_que_nao_inicia_tambem_e_indisponibilidade_e_nao_erro_cru(monkeypatch, ligada):
    _grava([_reg("a", PROPRIO)])
    _ambiente(monkeypatch, _Contexto(falha_ao_entrar=RuntimeError("driver quebrou")))
    r = main_mod.fase_render()
    assert r["ambiente_indisponivel"] == "playwright_indisponivel"
    assert "driver quebrou" in _bloco("a")["detalhe"] and _bloco("a")["estado"] == "nao_verificado"


def test_navegador_ausente_marca_nao_verificado_e_fecha_o_playwright(monkeypatch, ligada):
    _grava([_reg("a", PROPRIO)])
    contexto = _ambiente(monkeypatch, _Contexto(_PW(falha=RuntimeError(
        "BrowserType.launch: Executable doesn't exist at C:/x\n== Looks like Playwright =="))))
    monkeypatch.setattr(sr, "processar_lead", lambda *a, **k: (_ for _ in ()).throw(AssertionError("mediu")))

    r = main_mod.fase_render()

    assert r["ambiente_indisponivel"] == "navegador_indisponivel"
    b = _bloco("a")
    assert b["estado"] == "nao_verificado" and b["motivo"] == "navegador_indisponivel" and b["tentativas"] == 0
    assert b["detalhe"].startswith("BrowserType.launch: Executable doesn't exist") and "\n" not in b["detalhe"]
    assert contexto.saiu is True                                       # nao deixa o Playwright aberto


def test_navegador_de_volta_mede_o_lead(monkeypatch, ligada):
    _grava([_reg("a", PROPRIO)])
    _ambiente(monkeypatch, _Contexto(_PW(falha=RuntimeError("sem chromium"))))
    main_mod.fase_render()
    assert _bloco("a")["motivo"] == "navegador_indisponivel"
    _ambiente(monkeypatch)
    _medidor(monkeypatch)
    main_mod.fase_render()
    assert _bloco("a")["estado"] == "medido"


# ==================================================================================================
# 4. DEGRADACAO HONESTA: o site (erro de rede, anti-bot, fora do ar) e tentativas
# ==================================================================================================

def test_erro_transitorio_repete_ate_o_teto_e_depois_para(monkeypatch, ligada):
    teto = wave2_scoring.carregar_config_wave2()["max_retry_attempts"]
    assert teto == 3
    _grava([_reg("a", PROPRIO)])
    _ambiente(monkeypatch)
    medidor = _medidor(monkeypatch, padrao=_ficha(desktop={"status": "erro", "erro_tipo": "timeout"}))
    for esperado in range(1, teto + 1):
        main_mod.fase_render()
        b = _bloco("a")
        assert b["estado"] == "nao_verificado" and b["motivo"] == "erro:timeout" and b["tentativas"] == esperado
    assert main_mod.fase_render() is None                              # esgotou: nao insiste
    assert medidor.chamadas == ["a"] * teto and _bloco("a")["tentativas"] == teto


def test_erro_que_passa_na_segunda_tentativa_vira_medido_e_nao_e_remedido(monkeypatch, ligada):
    _grava([_reg("a", PROPRIO)])
    _ambiente(monkeypatch)
    respostas = iter([_ficha(mobile={"status": "erro", "erro_tipo": "dns_error"}), _ficha()])
    medidor = _medidor(monkeypatch, respostas={"a": lambda: next(respostas)})
    main_mod.fase_render()
    assert _bloco("a")["estado"] == "nao_verificado"
    main_mod.fase_render()
    assert _bloco("a")["estado"] == "medido" and _bloco("a")["tentativas"] == 2
    assert main_mod.fase_render() is None and medidor.chamadas == ["a", "a"]


def test_anti_bot_e_http_erro_sao_estados_proprios_e_terminais(monkeypatch, ligada):
    _grava([_reg("bot", PROPRIO), _reg("fora", "https://clinica-dois.es"), _reg("ok", "https://clinica-tres.es")])
    _ambiente(monkeypatch)
    medidor = _medidor(monkeypatch, respostas={
        "bot": _ficha(mobile={"status": "anti_bot", "antibot_casou": "titulo:just a moment", "http_status": 403}),
        "fora": _ficha(desktop={"status": "http_erro", "http_status": 503}),
    })
    main_mod.fase_render()
    assert _bloco("bot")["estado"] == "anti_bot" and _bloco("bot")["motivo"] == "anti_bot:titulo:just a moment"
    assert _bloco("fora")["estado"] == "http_erro" and _bloco("fora")["motivo"] == "http_erro:503"
    assert _bloco("ok")["estado"] == "medido"
    assert {"anti_bot", "http_erro"}.isdisjoint({"medido", "nao_verificado"})   # estados proprios, nao "medido"
    chamadas_1 = list(medidor.chamadas)
    assert main_mod.fase_render() is None and medidor.chamadas == chamadas_1     # terminais: nao bate de novo


def test_nunca_marca_medido_quando_so_um_dispositivo_foi_visto(monkeypatch, ligada):
    _grava([_reg("a", PROPRIO)])
    _ambiente(monkeypatch)
    _medidor(monkeypatch, padrao=_ficha(mobile={"status": "ok"}, desktop={"status": "anti_bot", "antibot_casou": "x"}))
    main_mod.fase_render()
    assert _bloco("a")["estado"] == "anti_bot"


def test_excecao_inesperada_num_lead_nao_derruba_o_lote(monkeypatch, ligada):
    _grava([_reg("a", PROPRIO), _reg("b", "https://clinica-dois.es")])
    _ambiente(monkeypatch)
    _medidor(monkeypatch, respostas={"a": RuntimeError("boom")})
    main_mod.fase_render()
    assert _bloco("a")["estado"] == "nao_verificado" and _bloco("a")["motivo"] == "excecao:RuntimeError"
    assert "boom" in _bloco("a")["detalhe"] and _bloco("a")["resultado"] is None
    assert _bloco("b")["estado"] == "medido"


# ==================================================================================================
# 5. SEQUENCIAL, CHECKPOINT E RETOMADA
# ==================================================================================================

def test_um_site_por_vez_na_ordem_do_arquivo_e_grava_a_cada_lead(monkeypatch, ligada):
    _grava([_reg("a", PROPRIO), _reg("b", "https://clinica-dois.es"), _reg("c", "https://clinica-tres.es")])
    _ambiente(monkeypatch)
    em_disco = {}

    def ao_entrar(pid):
        em_disco[pid] = sorted(i for i, l in _por_id().items() if l.get("site_renderizado"))

    medidor = _medidor(monkeypatch, ao_entrar=ao_entrar)
    main_mod.fase_render()
    assert medidor.chamadas == ["a", "b", "c"] and medidor.max_concorrencia == 1
    assert em_disco == {"a": [], "b": ["a"], "c": ["a", "b"]}          # o anterior ja estava em disco (checkpoint)


def test_interrompida_guarda_o_que_mediu_e_retoma_sem_refazer(monkeypatch, ligada):
    _grava([_reg("a", PROPRIO), _reg("b", "https://clinica-dois.es"), _reg("c", "https://clinica-tres.es")])
    contexto = _ambiente(monkeypatch)
    _medidor(monkeypatch, respostas={"b": KeyboardInterrupt()})
    with pytest.raises(KeyboardInterrupt):
        main_mod.fase_render()
    assert _bloco("a")["estado"] == "medido"                           # ficou em disco
    assert _bloco("b") is None and _bloco("c") is None
    assert contexto.saiu is True                                       # e fechou o navegador

    retomada = _medidor(monkeypatch)
    _ambiente(monkeypatch)
    main_mod.fase_render()
    assert retomada.chamadas == ["b", "c"]                             # "a" NAO foi refeito
    assert all(_bloco(p)["estado"] == "medido" for p in "abc")


def test_capturas_vao_para_a_pasta_de_dados_e_a_referencia_e_relativa(monkeypatch, ligada):
    _grava([_reg("a", PROPRIO)])
    _ambiente(monkeypatch)
    pasta = main_mod._pasta_capturas()
    externo = "C:/fora/da/pasta/x_mobile.png"
    medidor = _medidor(monkeypatch, padrao=_ficha(
        mobile={"screenshot_ref": os.path.join(pasta, "a_mobile.png")}, desktop={"screenshot_ref": externo}))
    main_mod.fase_render()
    d = _bloco("a")["resultado"]["por_dispositivo"]
    assert d["mobile"]["screenshot_ref"] == "capturas_site/a_mobile.png"      # relativa ao data/, sem caminho de maquina
    assert d["desktop"]["screenshot_ref"] == externo                          # fora do data/: intacta
    assert Path(medidor.pastas[0]) == Path(pasta) and os.path.isdir(pasta)


def test_o_resto_do_registro_nao_muda(monkeypatch, ligada):
    antes = [_reg("a", PROPRIO), _reg("b", "https://www.doctoralia.es/x")]
    _grava(copy.deepcopy(antes))
    _ambiente(monkeypatch)
    _medidor(monkeypatch)
    main_mod.fase_render()
    for original, depois in zip(antes, _le()):
        assert {k: v for k, v in depois.items() if k != "site_renderizado"} == original


def test_bloco_gravado_guarda_estado_motivo_tentativas_data_url_e_resultado(monkeypatch, ligada):
    _grava([_reg("a", PROPRIO)])
    _ambiente(monkeypatch)
    _medidor(monkeypatch)
    main_mod.fase_render()
    b = _bloco("a")
    assert set(b) == {"estado", "motivo", "detalhe", "tentativas", "avaliado_em", "url", "resultado"}
    assert b["url"] == PROPRIO and b["tentativas"] == 1 and b["avaliado_em"]
    assert set(b["resultado"]["por_dispositivo"]) == {"mobile", "desktop"}


# ==================================================================================================
# 6. PONTA A PONTA com Chromium real contra o servidor LOCAL (pulado, com motivo, sem navegador)
# ==================================================================================================

def test_ponta_a_ponta_com_navegador_real_no_servidor_local(pw, base_url, monkeypatch, ligada):
    _grava([_reg("ok", base_url + "/ok"), _reg("bot", base_url + "/desafio403"), _reg("fora", base_url + "/404")])
    # O Playwright sincrono nao aninha: a fixture `pw` (sessao) ja tem um aberto. A fase usa ESTA instancia
    # real; verificar_navegador, processar_lead e o Chromium sao os de verdade.
    _ambiente(monkeypatch, _Contexto(pw))

    r = main_mod.fase_render()

    assert _bloco("ok")["estado"] == "medido"
    assert _bloco("bot")["estado"] == "anti_bot" and _bloco("fora")["estado"] == "http_erro"
    assert (r["medido"], r["anti_bot"], r["http_erro"], r["pulado"]) == (1, 1, 1, 0)
    ok = _bloco("ok")["resultado"]["por_dispositivo"]
    assert ok["mobile"]["menu_hamburguer"] == "abre" and ok["mobile"]["coletado_em"]
    assert ok["desktop"]["has_tel_link"] is True and "Pedir cita" in ok["desktop"]["botoes_textos"]
    for pid in ("ok", "bot", "fora"):                                   # uma captura limpa por dispositivo, em data/, fora do Git
        for disp in ("mobile", "desktop"):
            ref = _bloco(pid)["resultado"]["por_dispositivo"][disp]["screenshot_ref"]
            assert ref.startswith("capturas_site/") and (Path(main_mod.DATA_DIR) / ref).is_file()
    fora = _bloco("fora")["resultado"]["por_dispositivo"]["desktop"]
    assert fora["has_form"] is None and fora["botoes_textos"] is None   # a pagina de erro nao vira sinal
