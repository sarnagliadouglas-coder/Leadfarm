import gbp_diagnostic as gd


def _lead(**gbp):
    base = {
        "gbp_detalhe_scraped": "YES",
        "gbp_reivindicada": "YES",
        "gbp_horario": "Lun-Vie 9:00-18:00",
        "gbp_foto_destaque": "http://x/foto.jpg",
        "gbp_descricao": "Clínica de fisioterapia en Sevilla.",
        "gbp_faixa_preco": "€€",
        "gbp_plus_code": "8CGX+2M Sevilla",
        "gbp_dono": "María Ficticia",
    }
    base.update(gbp)
    return base


# --- estados de verificação ---------------------------------------------------------------

def test_ficha_completa_score_zero_e_sem_lacunas():
    d = gd.diagnosticar(_lead())
    assert d["detail_scraped"] is True
    assert d["score_completude"] == 0
    assert d["lacunas"] == []
    assert all(s["estado"] == gd.CONFIRMADO_PRESENTE for s in d["sinais"].values())


def test_campo_vazio_com_deep_scrape_vira_confirmado_ausente_e_pontua():
    d = gd.diagnosticar(_lead(gbp_horario=None, gbp_descricao=""))
    assert d["sinais"]["tem_horario"]["estado"] == gd.CONFIRMADO_AUSENTE
    assert d["sinais"]["tem_descricao"]["estado"] == gd.CONFIRMADO_AUSENTE
    assert d["score_completude"] == 24 + 16
    assert d["lacunas"] == [
        "ficha do Google sem horário de funcionamento",
        "ficha do Google sem descrição do negócio",
    ]  # ordenado por peso desc (24 antes de 16)


def test_sem_detail_scraped_tudo_nao_verificado_e_score_none():
    d = gd.diagnosticar(_lead(gbp_detalhe_scraped="NO", gbp_horario=None))
    assert d["detail_scraped"] is False
    assert d["score_completude"] is None
    assert d["lacunas"] == []
    assert all(s["estado"] == gd.NAO_VERIFICADO for s in d["sinais"].values())


def test_coluna_detail_scraped_ausente_csv_antigo_nao_quebra():
    lead = _lead()
    del lead["gbp_detalhe_scraped"]
    d = gd.diagnosticar(lead)
    assert d["detail_scraped"] is False
    assert d["score_completude"] is None


# --- ficha_reivindicada: parsing yes/no ---------------------------------------------------

def test_claimed_negativo_e_lacuna_de_maior_peso():
    d = gd.diagnosticar(_lead(gbp_reivindicada="NO"))
    assert d["sinais"]["ficha_reivindicada"]["estado"] == gd.CONFIRMADO_AUSENTE
    assert d["score_completude"] == 28
    assert d["lacunas"][0] == "ficha do Google não reivindicada pelo dono"


def test_claimed_em_portugues_e_reconhecido():
    assert gd.diagnosticar(_lead(gbp_reivindicada="Sim"))["sinais"]["ficha_reivindicada"]["estado"] == gd.CONFIRMADO_PRESENTE
    assert gd.diagnosticar(_lead(gbp_reivindicada="Não"))["sinais"]["ficha_reivindicada"]["estado"] == gd.CONFIRMADO_AUSENTE


# --- sinais informativos: nunca pontuam, nunca viram lacuna ------------------------------

def test_dono_e_plus_code_ausentes_nao_afetam_score_nem_lacunas():
    d = gd.diagnosticar(_lead(gbp_dono=None, gbp_plus_code=None))
    assert d["sinais"]["tem_dono_listado"]["estado"] == gd.CONFIRMADO_AUSENTE
    assert d["sinais"]["tem_plus_code"]["estado"] == gd.CONFIRMADO_AUSENTE
    assert d["score_completude"] == 0
    assert d["lacunas"] == []


# --- health-check por campo -------------------------------------------------------------

def test_health_check_rebaixa_campo_com_zero_presenca_apesar_de_deep_scrape():
    # 20 leads, todos com deep-scrape, todos sem descrição -> seletor quebrado, não lacuna.
    leads = [_lead(gbp_descricao=None) for _ in range(20)]
    rebaixados, avisos = gd.avaliar_saude_do_lote(leads)
    assert "tem_descricao" in rebaixados
    assert any(a.get("campo") == "tem_descricao" for a in avisos)

    d = gd.diagnosticar(leads[0], rebaixados)
    assert d["sinais"]["tem_descricao"]["estado"] == gd.NAO_VERIFICADO
    assert d["score_completude"] == 0  # não conta como lacuna
    assert "ficha do Google sem descrição do negócio" not in d["lacunas"]


def test_health_check_nao_rebaixa_campo_legitimamente_presente():
    leads = [_lead() for _ in range(20)]
    rebaixados, _ = gd.avaliar_saude_do_lote(leads)
    assert rebaixados == set()


def test_health_check_pulado_com_amostra_pequena():
    leads = [_lead(gbp_descricao=None) for _ in range(10)]  # < sample_floor
    rebaixados, avisos = gd.avaliar_saude_do_lote(leads)
    assert rebaixados == set()
    assert avisos and "amostra insuficiente" in avisos[0]["aviso"]

    # sem rebaixamento: com deep-scrape, campo vazio continua sendo lacuna real
    d = gd.diagnosticar(leads[0])
    assert d["sinais"]["tem_descricao"]["estado"] == gd.CONFIRMADO_AUSENTE


def test_health_check_ignora_leads_sem_deep_scrape_na_amostra():
    # 30 leads sem deep-scrape + 5 com deep-scrape e descrição vazia: amostra efetiva = 5 < floor
    leads = [_lead(gbp_detalhe_scraped="NO") for _ in range(30)] + [_lead(gbp_descricao=None) for _ in range(5)]
    rebaixados, avisos = gd.avaliar_saude_do_lote(leads)
    assert rebaixados == set()
    assert avisos and avisos[0]["n"] == 5


def test_config_customizada_muda_pesos():
    cfg = {"weights": {"no_horario": 99}}
    d = gd.diagnosticar(_lead(gbp_horario=None), config=cfg)
    assert d["score_completude"] == 99
