import wave2_scoring as ws


def _config():
    import json
    return json.loads(json.dumps(ws.CONFIG_DEFAULT))


def _analise_ok(**sinais_overrides):
    sinais = {
        "has_viewport_meta": True, "has_title": True, "title_length": 40,
        "has_meta_description": True, "meta_description_length": 80,
        "script_count": 1, "image_count": 2, "images_missing_alt_count": 0,
        "has_form": True, "has_tel_link": True, "has_whatsapp_link": False, "has_email_link": False,
        "has_legal_page_link": True, "has_lang_attribute": True, "html_lang": "es",
        "has_cta_keyword": True,
    }
    sinais.update(sinais_overrides)
    return {
        "status": "ok", "signals_available": True, "signals": sinais,
        "facts": {"response_time_ms": 200.0, "http_status": 200, "https": True},
    }


def _analise_indisponivel():
    return {"status": "unavailable", "signals_available": False, "signals": None, "facts": {}}


def test_website_opportunity_none_quando_signals_indisponivel():
    config = _config()["website_opportunity"]
    score, razoes = ws.website_opportunity_score(_analise_indisponivel(), config["weights"], config["thresholds"])
    assert score is None
    assert razoes == []


def test_site_com_todos_sinais_positivos_tem_opportunity_baixo():
    config = _config()["website_opportunity"]
    score, razoes = ws.website_opportunity_score(_analise_ok(), config["weights"], config["thresholds"])
    assert score < 30


def test_site_sem_nenhum_sinal_positivo_tem_opportunity_alto():
    config = _config()["website_opportunity"]
    analise = _analise_ok(
        has_viewport_meta=False, has_title=False, title_length=0, has_meta_description=False,
        has_form=False, has_tel_link=False, has_whatsapp_link=False, has_email_link=False,
        has_legal_page_link=False, has_lang_attribute=False, has_cta_keyword=False,
        images_missing_alt_count=3,
    )
    score, razoes = ws.website_opportunity_score(analise, config["weights"], config["thresholds"])
    assert score > 70
    assert len(razoes) >= 5


def test_sem_caminho_de_conversao_pesa_mais_que_sinal_isolado():
    config = _config()["website_opportunity"]
    sem_conversao = _analise_ok(has_form=False, has_tel_link=False, has_whatsapp_link=False, has_email_link=False)
    so_sem_form = _analise_ok(has_form=False)  # tem tel_link -> ainda tem caminho de conversão

    score_sem_conversao, _ = ws.website_opportunity_score(sem_conversao, config["weights"], config["thresholds"])
    score_so_sem_form, _ = ws.website_opportunity_score(so_sem_form, config["weights"], config["thresholds"])
    assert score_sem_conversao > score_so_sem_form


def test_resposta_lenta_soma_pontos():
    config = _config()["website_opportunity"]
    analise = _analise_ok()
    analise["facts"]["response_time_ms"] = 5000.0
    score, razoes = ws.website_opportunity_score(analise, config["weights"], config["thresholds"])
    assert any("lenta" in r for r in razoes)


def test_priority_score_combina_pesos_default_50_50():
    pesos = {"commercial_fit": 0.5, "website_opportunity": 0.5}
    assert ws.priority_score(80, 60, pesos) == 70


def test_priority_score_none_quando_website_opportunity_none():
    pesos = {"commercial_fit": 0.5, "website_opportunity": 0.5}
    assert ws.priority_score(80, None, pesos) is None


def test_priority_label_conforme_thresholds():
    thresholds = {"alta": 65, "media": 40}
    assert ws.priority_label(70, thresholds) == "alta"
    assert ws.priority_label(50, thresholds) == "media"
    assert ws.priority_label(10, thresholds) == "baixa"


def test_priority_label_needs_review_quando_score_none():
    assert ws.priority_label(None, {"alta": 65, "media": 40}) == "needs_review"


def test_ranquear_ordena_por_priority_desc_e_manda_none_pro_final():
    itens = [
        {"priority_score": None, "commercial_fit": {"score": 90}},
        {"priority_score": 50, "commercial_fit": {"score": 50}},
        {"priority_score": 80, "commercial_fit": {"score": 60}},
    ]
    ranqueados = ws.ranquear(itens)
    assert [i["priority_score"] for i in ranqueados] == [80, 50, None]


def test_carregar_config_wave2_sem_arquivo_usa_defaults(tmp_path):
    config = ws.carregar_config_wave2(str(tmp_path / "nao_existe.json"))
    assert config == ws.CONFIG_DEFAULT


def test_carregar_config_wave2_malformado_usa_defaults(tmp_path):
    caminho = tmp_path / "cfg.json"
    caminho.write_text("{ nao é json", encoding="utf-8")
    config = ws.carregar_config_wave2(str(caminho))
    assert config == ws.CONFIG_DEFAULT


def test_carregar_config_wave2_faz_merge_raso_por_secao(tmp_path):
    caminho = tmp_path / "cfg.json"
    caminho.write_text('{"batch_size": 5}', encoding="utf-8")
    config = ws.carregar_config_wave2(str(caminho))
    assert config["batch_size"] == 5
    assert config["priority_thresholds"] == ws.CONFIG_DEFAULT["priority_thresholds"]
