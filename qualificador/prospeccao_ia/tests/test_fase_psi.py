import json

import main as main_mod
import psi_client


def _isolar(tmp_path, monkeypatch):
    caminho = tmp_path / "com_site.json"
    monkeypatch.setattr(main_mod, "PATH_COM_SITE", str(caminho))
    monkeypatch.setattr(main_mod, "DATA_DIR", str(tmp_path))
    return caminho


def _registro(place_id="s1", status="analyzed", **extra):
    r = {
        "dados_empresa": {"place_id": place_id, "nome": "B", "website": "https://b.es"},
        "status": status,
    }
    r.update(extra)
    return r


def test_fase_psi_pulada_quando_desabilitado(tmp_path, monkeypatch):
    monkeypatch.delenv("PSI_ENABLED", raising=False)
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([_registro()]), encoding="utf-8")

    assert main_mod.fase_psi() is None
    # nada gravado -- registro segue sem bloco psi
    assert "psi" not in json.loads(caminho.read_text(encoding="utf-8"))[0]


def test_fase_psi_mede_so_analyzed_sem_medicao(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([
        _registro(place_id="s1", status="analyzed"),
        _registro(place_id="s2", status="needs_review"),
        _registro(place_id="s3", status="analyzed", psi={"estado": "CONFIRMADO_PRESENTE"}),
    ]), encoding="utf-8")

    monkeypatch.setattr(psi_client, "medir",
                        lambda url, **k: {"estado": "CONFIRMADO_PRESENTE", "performance_score": 55, "medido_em": "x"})

    resultado = main_mod.fase_psi()

    assert resultado["medidos"] == 1
    salvo = {r["dados_empresa"]["place_id"]: r for r in json.loads(caminho.read_text(encoding="utf-8"))}
    assert salvo["s1"]["psi"]["performance_score"] == 55
    assert "psi" not in salvo["s2"]                    # needs_review não é medido
    assert salvo["s3"]["psi"] == {"estado": "CONFIRMADO_PRESENTE"}  # já tinha, não remede


def test_fase_psi_sem_alvos_retorna_none(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([_registro(status="queued_future")]), encoding="utf-8")
    assert main_mod.fase_psi() is None


# --- teto de lote e reagendamento entre rodadas -----------------------------------------
# Base empírica: falha transiente domina no PSI (dos 51 que falharam numa rodada real, 47
# passaram na re-medição). Reagendar vale a pena; reagendar SEM teto queimaria quota pra
# sempre nos sites permanentemente quebrados, e medir sem batch_size vira rodada de horas.

def _falhou(place_id, transiente=True, rodadas=1, **extra):
    psi = {"estado": psi_client.NAO_VERIFICADO, "motivo": "falha na chamada PSI: x",
           "falha_transiente": transiente, "rodadas": rodadas, "tentativas": 2}
    psi.update(extra)
    return _registro(place_id=place_id, status="analyzed", psi=psi)


def _medir_ok(monkeypatch, registrar=None):
    def _fake(url, **k):
        if registrar is not None:
            registrar.append(url)
        return {"estado": "CONFIRMADO_PRESENTE", "performance_score": 70, "medido_em": "x"}
    monkeypatch.setattr(psi_client, "medir", _fake)


def test_batch_size_limita_o_lote_e_informa_pendentes(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    monkeypatch.setattr(main_mod, "PSI_BATCH_SIZE", 2)
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([_registro(place_id=f"s{i}") for i in range(5)]), encoding="utf-8")
    _medir_ok(monkeypatch)

    resultado = main_mod.fase_psi()

    assert resultado["medidos"] == 2, "batch_size tem que cortar o lote"
    assert resultado["pendentes"] == 3
    salvo = json.loads(caminho.read_text(encoding="utf-8"))
    assert sum(1 for r in salvo if r.get("psi")) == 2


def test_falha_transiente_volta_pra_fila_na_rodada_seguinte(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([_falhou("s1")]), encoding="utf-8")
    _medir_ok(monkeypatch)

    assert main_mod.fase_psi()["medidos"] == 1
    salvo = json.loads(caminho.read_text(encoding="utf-8"))[0]
    assert salvo["psi"]["estado"] == "CONFIRMADO_PRESENTE"
    assert salvo["psi"]["rodadas"] == 2, "rodadas tem que acumular entre execuções"


def test_falha_permanente_nao_volta_pra_fila(tmp_path, monkeypatch):
    """4xx/resposta inesperada dariam o mesmo erro -- reagendar só gastaria quota."""
    monkeypatch.setenv("PSI_ENABLED", "1")
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([_falhou("s1", transiente=False)]), encoding="utf-8")
    _medir_ok(monkeypatch)

    assert main_mod.fase_psi() is None


def test_lead_que_esgotou_as_rodadas_sai_da_fila(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    monkeypatch.setattr(main_mod, "PSI_MAX_RODADAS_POR_LEAD", 3)
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([_falhou("s1", rodadas=3)]), encoding="utf-8")
    _medir_ok(monkeypatch)

    assert main_mod.fase_psi() is None


def test_registro_antigo_sem_metadado_ainda_e_reagendado(tmp_path, monkeypatch):
    """Medições gravadas antes de 'falha_transiente'/'rodadas' existirem não podem ficar
    presas pra sempre por ausência de metadado."""
    monkeypatch.setenv("PSI_ENABLED", "1")
    caminho = _isolar(tmp_path, monkeypatch)
    antigo = _registro(place_id="s1", psi={"estado": psi_client.NAO_VERIFICADO, "motivo": "x"})
    caminho.write_text(json.dumps([antigo]), encoding="utf-8")
    _medir_ok(monkeypatch)

    assert main_mod.fase_psi()["medidos"] == 1
    salvo = json.loads(caminho.read_text(encoding="utf-8"))[0]
    assert salvo["psi"]["rodadas"] == 2, "assume rodadas=1 no registro antigo, então grava 2"


def test_nunca_medido_tem_prioridade_sobre_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    monkeypatch.setattr(main_mod, "PSI_BATCH_SIZE", 1)
    caminho = _isolar(tmp_path, monkeypatch)
    # retry primeiro na ordem do arquivo: só a prioridade da fila pode inverter isso
    caminho.write_text(json.dumps([
        _falhou("retry", **{}),
        _registro(place_id="novo"),
    ]), encoding="utf-8")
    medidos = []

    def _fake(url, **k):
        medidos.append(url)
        return {"estado": "CONFIRMADO_PRESENTE", "medido_em": "x"}

    monkeypatch.setattr(psi_client, "medir", _fake)
    main_mod.fase_psi()

    salvo = {r["dados_empresa"]["place_id"]: r for r in json.loads(caminho.read_text(encoding="utf-8"))}
    assert salvo["novo"]["psi"]["estado"] == "CONFIRMADO_PRESENTE"
    assert salvo["retry"]["psi"]["estado"] == psi_client.NAO_VERIFICADO, "retry fica pra próxima"


def test_guarda_de_tempo_interrompe_e_deixa_o_resto_pra_proxima(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    monkeypatch.setattr(main_mod, "PSI_MAX_RUNTIME_SECONDS", 10)
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([_registro(place_id=f"s{i}") for i in range(4)]), encoding="utf-8")

    relogio = iter([0, 0, 100, 100, 100, 100])  # 2ª checagem já estoura o teto
    monkeypatch.setattr(main_mod.time, "time", lambda: next(relogio))
    _medir_ok(monkeypatch)

    resultado = main_mod.fase_psi()

    assert resultado["interrompido_por_tempo"] is True
    assert resultado["medidos"] == 1
    assert resultado["pendentes"] == 3, "o que não coube continua na fila"


def test_medicao_boa_nunca_e_refeita(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([
        _registro(place_id="s1", psi={"estado": "CONFIRMADO_PRESENTE", "performance_score": 91, "rodadas": 1}),
    ]), encoding="utf-8")
    _medir_ok(monkeypatch)

    assert main_mod.fase_psi() is None
    salvo = json.loads(caminho.read_text(encoding="utf-8"))[0]
    assert salvo["psi"]["performance_score"] == 91


# --- segunda medição dos sites com LCP >= 10 s (decisão do diretor, 12/10/2026) ------------

def _lento(place_id, lcp_ms, rodadas=1, **extra):
    psi = {"estado": "CONFIRMADO_PRESENTE", "performance_score": 20, "lcp_ms": lcp_ms,
           "medido_em": "m1", "falha_transiente": False, "rodadas": rodadas}
    psi.update(extra)
    return _registro(place_id=place_id, psi=psi)


def _medir_lcp(monkeypatch, lcp_ms, estado="CONFIRMADO_PRESENTE", transiente=False, registrar=None):
    def _fake(url, **k):
        if registrar is not None:
            registrar.append(url)
        return {"estado": estado, "lcp_ms": lcp_ms if estado == "CONFIRMADO_PRESENTE" else None,
                "medido_em": "m2", "motivo": None if estado == "CONFIRMADO_PRESENTE" else "falha",
                "falha_transiente": transiente, "tentativas": 1, "performance_score": 30}
    monkeypatch.setattr(psi_client, "medir", _fake)


def _salvo(caminho):
    return {r["dados_empresa"]["place_id"]: r for r in json.loads(caminho.read_text(encoding="utf-8"))}


def test_so_quem_deu_10s_ou_mais_tem_segunda_medicao(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([
        _lento("lento", 12000), _lento("no_limiar", 10000), _lento("rapido", 9999),
    ]), encoding="utf-8")
    medidos = []
    _medir_lcp(monkeypatch, 11000, registrar=medidos)

    resultado = main_mod.fase_psi()

    assert resultado["medidos"] == 2
    salvo = _salvo(caminho)
    assert "segunda_medicao" in salvo["lento"]["psi"]
    assert "segunda_medicao" in salvo["no_limiar"]["psi"]
    assert "segunda_medicao" not in salvo["rapido"]["psi"], "9,999 s não é medido de novo"
    assert salvo["rapido"]["psi"]["lcp_ms"] == 9999


def test_concordancia_cita_o_menor_dos_dois(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([_lento("a", 14000), _lento("b", 11000)]), encoding="utf-8")
    _medir_lcp(monkeypatch, 12500)

    main_mod.fase_psi()

    salvo = _salvo(caminho)
    for pid, menor, primeira in (("a", 12500, 14000), ("b", 11000, 11000)):
        psi = salvo[pid]["psi"]
        assert psi["segunda_medicao"]["concorda"] is True
        assert psi["segunda_medicao"]["lcp_ms_primeira"] == primeira
        assert psi["segunda_medicao"]["lcp_ms"] == 12500
        assert psi["lcp_ms"] == menor
        assert psi["rodadas"] == 2
        assert psi["performance_score"] == 20, "o resto do bloco continua sendo o da primeira"


def test_segunda_abaixo_do_limiar_nao_concorda_e_fica_a_mais_recente(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([_lento("a", 15000)]), encoding="utf-8")
    _medir_lcp(monkeypatch, 9999)

    main_mod.fase_psi()

    psi = _salvo(caminho)["a"]["psi"]
    assert psi["segunda_medicao"]["concorda"] is False
    assert psi["lcp_ms"] == 9999
    # e não volta pra fila: a medição válida mais recente ficou abaixo do limiar
    assert main_mod.fase_psi() is None


def test_segunda_que_falhou_nao_concorda_e_mantem_a_primeira(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([_lento("perm", 13000), _lento("trans", 13000)]), encoding="utf-8")
    _medir_lcp(monkeypatch, None, estado=psi_client.NAO_VERIFICADO, transiente=False)
    main_mod.fase_psi()
    psi = _salvo(caminho)["perm"]["psi"]
    assert psi["segunda_medicao"]["concorda"] is False
    assert psi["lcp_ms"] == 13000
    assert psi["estado"] == "CONFIRMADO_PRESENTE"
    # falha permanente: nada a reagendar
    assert main_mod.fase_psi() is None


def test_segunda_com_falha_transiente_volta_ate_o_teto(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([_lento("a", 13000)]), encoding="utf-8")
    medidos = []
    _medir_lcp(monkeypatch, None, estado=psi_client.NAO_VERIFICADO, transiente=True, registrar=medidos)
    for _ in range(main_mod.PSI_MAX_RODADAS_POR_LEAD + 2):
        main_mod.fase_psi()
    assert len(medidos) == main_mod.PSI_MAX_RODADAS_POR_LEAD
    assert _salvo(caminho)["a"]["psi"]["segunda_medicao"]["rodadas"] == main_mod.PSI_MAX_RODADAS_POR_LEAD

    # depois de uma transiente, a segunda que dá certo concorda com a PRIMEIRA medição
    caminho.write_text(json.dumps([_lento("b", 13000)]), encoding="utf-8")
    _medir_lcp(monkeypatch, None, estado=psi_client.NAO_VERIFICADO, transiente=True)
    main_mod.fase_psi()
    _medir_lcp(monkeypatch, 16000)
    main_mod.fase_psi()
    psi = _salvo(caminho)["b"]["psi"]
    assert psi["segunda_medicao"]["concorda"] is True
    assert psi["segunda_medicao"]["lcp_ms_primeira"] == 13000
    assert psi["lcp_ms"] == 13000


def test_segunda_medicao_acontece_uma_vez_so(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([_lento("a", 13000)]), encoding="utf-8")
    medidos = []
    _medir_lcp(monkeypatch, 12000, registrar=medidos)
    main_mod.fase_psi()
    assert main_mod.fase_psi() is None
    assert len(medidos) == 1


def test_nunca_medido_e_retry_vem_antes_da_segunda_medicao(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_ENABLED", "1")
    monkeypatch.setattr(main_mod, "PSI_BATCH_SIZE", 2)
    caminho = _isolar(tmp_path, monkeypatch)
    caminho.write_text(json.dumps([
        _lento("lento", 13000), _falhou("retry"), _registro(place_id="novo"),
    ]), encoding="utf-8")
    _medir_lcp(monkeypatch, 3000)

    main_mod.fase_psi()

    salvo = _salvo(caminho)
    assert "segunda_medicao" not in salvo["lento"]["psi"], "segunda medição fica pra próxima"
    assert salvo["novo"]["psi"]["estado"] == "CONFIRMADO_PRESENTE"
    assert salvo["retry"]["psi"]["estado"] == "CONFIRMADO_PRESENTE"
