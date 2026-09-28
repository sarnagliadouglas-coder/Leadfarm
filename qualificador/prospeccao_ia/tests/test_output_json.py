import json

import pytest

import output_json as oj


def _emp(**over):
    base = {
        "place_id": "p1", "nome": "Clínica X", "nicho": "Fisioterapeuta", "cidade": "Sevilla",
        "endereco": "Calle Falsa 1", "google_maps_url": "https://maps.google.com/?cid=1",
        "nota_google": 4.8, "review_count": 120, "reputation_signal": "strong",
        "telefone": "612345678", "email": None, "instagram": "@x", "facebook": None,
        "website": "https://x.es", "website_status": "listed",
        "gbp_reivindicada": "NO", "gbp_horario": None,
    }
    base.update(over)
    return base


def _gbp_diag():
    return {"score_completude": 52, "detail_scraped": True, "sinais": {}, "lacunas": []}


def _qualificado(**over):
    return {"dados_empresa": _emp(website=None, website_status="not_listed_google_maps", **over),
            "qualificacao": {"score": 48, "priority": "media", "contactability": "alta",
                             "evidence": ["4.8★ (120 avaliações)"], "risks": [], "reasons": []},
            "gbp_diagnostico": _gbp_diag(), "status": "qualified"}


def _render(estado="medido", mobile=None, desktop=None, avaliado_em="2026-09-04T10:00:00Z"):
    def dispositivo(**over):
        base = {"status": "ok", "http_status": 200, "contato_visivel": True,
                "telefone_clicavel": True, "has_tel_link": True,
                "coletado_em": avaliado_em, "screenshot_ref": "captura.png"}
        base.update(over)
        return base
    return {"estado": estado, "avaliado_em": avaliado_em,
            "resultado": {"por_dispositivo": {
                "mobile": dispositivo(**(mobile or {})),
                "desktop": dispositivo(**(desktop or {})),
            }}}


def _com_site(**over):
    registro = {
        "dados_empresa": _emp(),
        "gbp_diagnostico": _gbp_diag(),
        "website_analysis": {"status": "ok", "error_type": None, "signals": {}},
        "commercial_fit": {"score": 40, "reasons": []},
        "wave2_evaluated_at": "2026-09-04T10:00:00Z",
        "site_renderizado": _render(),
        "psi": {"estado": "CONFIRMADO_PRESENTE", "lcp_ms": 2000,
                "medido_em": "2026-09-04T10:00:00Z"},
        "status": "analyzed",
    }
    registro.update(over)
    return registro


def test_separa_nata_candidatos_e_exclui_sem_problema_com_poucas_avaliacoes():
    nata = _com_site(site_renderizado=_render(mobile={"contato_visivel": False},
                                               desktop={"contato_visivel": False}))
    candidato = _com_site()
    poucos = _com_site(dados_empresa=_emp(review_count=9))
    saida = oj.montar([_qualificado()], [nata, candidato, poucos], [])
    assert [l["place_id"] for l in saida["nata"]] == ["p1"]
    assert len(saida["candidatos_triagem"]) == 1
    assert saida["stats"]["nata"] == 1


def test_problemas_vendaveis_aceitos_e_controles_negativos():
    casos = [
        ("sem_contato_visivel", _com_site(site_renderizado=_render(
            mobile={"contato_visivel": False}, desktop={"contato_visivel": False}))),
        ("lento_no_celular", _com_site(psi={"estado": "CONFIRMADO_PRESENTE", "lcp_ms": 4001,
                                             "medido_em": "2026-09-04T10:00:00Z"})),
        ("fora_do_ar", _com_site(site_renderizado=_render(
            mobile={"status": "http_erro", "http_status": 404},
            desktop={"status": "http_erro", "http_status": 404}))),
    ]
    for tipo, registro in casos:
        lead = oj.montar([], [registro], [])["nata"][0]
        assert [p["tipo"] for p in lead["problema_vendavel"]] == [tipo]

    assert oj.montar([], [_com_site(psi={"estado": "NAO_VERIFICADO", "lcp_ms": 9000})], [])["nata"] == []
    assert oj.montar([], [_com_site(site_renderizado=_render(
        mobile={"status": "http_erro", "http_status": 403}))], [])["nata"] == []
    assert oj.montar([], [_com_site(site_renderizado=_render(
        mobile={"telefone_clicavel": False}, desktop={"telefone_clicavel": False}))], [])["nata"] == []
    rede = _com_site(site_renderizado=_render(
        mobile={"status": "erro", "http_status": None, "erro_tipo": "dns_error"},
        desktop={"status": "erro", "http_status": None, "erro_tipo": "dns_error"}))
    assert oj.montar([], [rede], [])["nata"][0]["problema_vendavel"][0]["tipo"] == "fora_do_ar"
    so_mobile = _com_site(site_renderizado=_render(
        mobile={"contato_visivel": True}, desktop={"contato_visivel": False}))
    assert oj.montar([], [so_mobile], [])["nata"] == []


def test_fora_do_ar_exige_falha_consistente_nos_dois_dispositivos():
    """Achado real (supervisão, 24/09/2026): FISIOFICTICIA entrou na nata como fora_do_ar por
    UM timeout no desktop, com o celular abrindo normal (status ok, 3,5s) e PSI normal.
    Reprodução exata do caso, com nome fictício: só o desktop falha -- não é fora_do_ar."""
    fisioficticia = _com_site(
        dados_empresa=_emp(review_count=5),  # < 10: sem isto, sem problema, iria pra candidatos_triagem
        site_renderizado=_render(
            mobile={"status": "ok", "http_status": 200, "tempo_carregamento_ms": 3500},
            desktop={"status": "erro", "http_status": None, "erro_tipo": "timeout"},
        ),
        psi={"estado": "CONFIRMADO_PRESENTE", "lcp_ms": 2000, "medido_em": "2026-09-04T10:00:00Z"},
    )
    saida = oj.montar([], [fisioficticia], [])
    assert saida["nata"] == []
    assert saida["candidatos_triagem"] == []


def test_fora_do_ar_com_os_dois_dispositivos_falhando_por_motivos_diferentes():
    """Não precisa ser o MESMO tipo de falha nos dois -- só que os dois tenham falhado."""
    registro = _com_site(site_renderizado=_render(
        mobile={"status": "http_erro", "http_status": 500},
        desktop={"status": "erro", "http_status": None, "erro_tipo": "timeout"},
    ))
    lead = oj.montar([], [registro], [])["nata"][0]
    assert [p["tipo"] for p in lead["problema_vendavel"]] == ["fora_do_ar"]
    assert "mobile" in lead["problema_vendavel"][0]["evidencia"]
    assert "desktop" in lead["problema_vendavel"][0]["evidencia"]


def test_anti_bot_nunca_conta_mesmo_com_o_outro_dispositivo_falhando():
    """Controle negativo: anti_bot (403) num dispositivo + falha real no outro -- ainda não é
    "os dois falharam" (403 nunca é falha), então não é fora_do_ar."""
    registro = _com_site(
        dados_empresa=_emp(review_count=5),  # < 10: sem isto, sem problema, iria pra candidatos_triagem
        site_renderizado=_render(
            mobile={"status": "http_erro", "http_status": 403},
            desktop={"status": "erro", "http_status": None, "erro_tipo": "timeout"},
        ),
    )
    saida = oj.montar([], [registro], [])
    assert saida["nata"] == []
    assert saida["candidatos_triagem"] == []


def test_telefone_na_pagina_tem_os_quatro_estados_e_texto_nao_e_problema():
    def telefone(registro):
        return oj.montar([], [registro], [])[ "candidatos_triagem"][0]["analise_tecnica_site"]["telefone_na_pagina"]

    assert telefone(_com_site()) == {"valor": "link", "estado": "CONFIRMADO_PRESENTE"}
    assert telefone(_com_site(site_renderizado=_render(
        mobile={"telefone_clicavel": False, "has_tel_link": False},
        desktop={"telefone_clicavel": False, "has_tel_link": False}))) == {
        "valor": "texto", "estado": "CONFIRMADO_PRESENTE"}
    assert telefone(_com_site(site_renderizado=_render(
        mobile={"telefone_clicavel": None, "has_tel_link": False},
        desktop={"telefone_clicavel": None, "has_tel_link": False}))) == {
        "valor": None, "estado": "CONFIRMADO_AUSENTE"}
    assert telefone(_com_site(site_renderizado={"estado": "nao_verificado"})) == {
        "valor": None, "estado": "NAO_VERIFICADO"}
    texto = _com_site(site_renderizado=_render(
        mobile={"telefone_clicavel": False, "has_tel_link": False},
        desktop={"telefone_clicavel": False, "has_tel_link": False}))
    assert oj.montar([], [texto], [])["candidatos_triagem"][0]["problema_vendavel"] == []


def test_candidato_tem_captura_e_so_site_proprio_entra():
    candidato = oj.montar([], [_com_site()], [])[ "candidatos_triagem"][0]
    assert candidato["classe_site"] == "proprio"
    assert candidato["candidato_triagem_visual"]["captura_ref"] == "captura.png"
    assert "veredito" not in json.dumps(candidato)
    excluido = _com_site(dados_empresa=_emp(website="https://instagram.com/x"))
    assert oj.montar([], [excluido], [])["nata"] == []
    assert oj.montar([], [excluido], [])["candidatos_triagem"] == []


# Regressões preservadas da versão 1.1.0, adaptadas às listas de trabalho v2.
def _todos_leads(saida):
    return saida["nata"] + saida["candidatos_triagem"]


def test_onda1_e_onda2_convivem_com_estagio_explicito():
    saida = oj.montar([], [
        _com_site(site_renderizado=_render(mobile={"contato_visivel": False},
                                           desktop={"contato_visivel": False})),
        _com_site(),
    ], [])
    assert sorted(l["estagio_analise"] for l in _todos_leads(saida)) == [
        "COMPLETO_COM_SITE", "COMPLETO_COM_SITE"]
    assert saida["stats"]["nata"] == 1
    assert saida["stats"]["candidatos_triagem"] == 1
    assert saida["stats"]["descartados"] == 0 and saida["stats"]["onda2_ainda_pendente"] == 0


def test_blocos_antigos_removidos_do_contrato():
    for lead in _todos_leads(oj.montar([], [_com_site()], [])):
        assert "site_analise" not in lead
        assert "qualificacao_comercial" not in lead
        assert "extractor_opportunity_raw" not in lead
        assert {"evidencias_qualificador", "priorizacao", "analise_tecnica_site"} <= lead.keys()


def test_lead_onda2_fato_e_julgamento_separados():
    sinais = {"images_missing_alt_count": 2, "image_count": 5,
              "has_meta_description": False, "has_title": True,
              "has_viewport_meta": True, "script_count": 3,
              "has_lang_attribute": True, "html_lang": "es",
              "has_form": True, "has_tel_link": False,
              "has_whatsapp_link": False, "has_email_link": False,
              "has_legal_page_link": True, "has_cta_keyword": False}
    registro = _com_site(website_analysis={"status": "ok", "error_type": None,
                                           "signals": sinais},
                         website_opportunity={"score": 55,
                                              "reasons": ["sem meta description no HTML",
                                                          "resposta lenta (4000ms)"]},
                         priority_score=48, priority_label="media")
    lead = oj.montar([], [registro], [])["candidatos_triagem"][0]
    ev = lead["evidencias_qualificador"]
    assert ev["sinais_site"]["images_missing_alt_count"] == 2
    pri = lead["priorizacao"]
    assert pri["autoritativo"] is False
    assert pri["commercial_fit_score"] == 40
    assert pri["website_opportunity_score"] == 55
    assert pri["priority_score"] == 48 and pri["priority_label"] == "media"
    assert pri["priority"] is None and pri["contactability"] is None and pri["risks"] is None
    assert lead["analise_tecnica_site"]["status"] == "ok"


def test_onda2_queued_future_nao_entra_na_saida():
    saida = oj.montar([], [_com_site(status="queued_future")], [])
    assert saida["nata"] == [] and saida["candidatos_triagem"] == []
    assert saida["stats"]["onda2_ainda_pendente"] == 1


def test_onda2_needs_review_entra_na_saida():
    saida = oj.montar([], [_com_site(status="needs_review")], [])
    assert len(saida["candidatos_triagem"]) == 1
    assert saida["candidatos_triagem"][0]["estagio_analise"] == "COMPLETO_COM_SITE"


def test_todo_campo_de_contato_viaja_com_estado():
    lead = oj.montar([], [_com_site()], [])["candidatos_triagem"][0]
    assert lead["contato"]["telefone"] == {"valor": "612345678", "estado": "CONFIRMADO_PRESENTE"}
    assert lead["contato"]["email"] == {"valor": None, "estado": "CONFIRMADO_AUSENTE"}
    assert lead["contato"]["whatsapp_apto"] is True


def test_linkedin_no_lead_chega_ao_contrato_e_sem_linkedin_vem_ausente():
    com = oj.montar([], [_com_site(dados_empresa=_emp(
        linkedin="https://www.linkedin.com/company/clinica-x/"))], [])["candidatos_triagem"][0]
    assert com["contato"]["linkedin"]["estado"] == "CONFIRMADO_PRESENTE"
    sem = oj.montar([], [_com_site()], [])["candidatos_triagem"][0]
    assert sem["contato"]["linkedin"] == {"valor": None, "estado": "CONFIRMADO_AUSENTE"}


def test_linkedin_nao_afeta_whatsapp_apto():
    reg = _com_site(dados_empresa=_emp(linkedin="https://linkedin.com/in/x",
                                        telefone="960000105", email=None,
                                        instagram=None, facebook=None))
    lead = oj.montar([], [reg], [])["candidatos_triagem"][0]
    assert lead["contato"]["linkedin"]["valor"] == "https://linkedin.com/in/x"
    assert lead["contato"]["whatsapp_apto"] is False


def test_gbp_campos_crus_herdam_estado_do_diagnostico():
    diag = _gbp_diag()
    diag["sinais"] = {"ficha_reivindicada": {"estado": "CONFIRMADO_AUSENTE"},
                      "tem_horario": {"estado": "CONFIRMADO_AUSENTE"}}
    lead = oj.montar([], [_com_site(gbp_diagnostico=diag)], [])["candidatos_triagem"][0]
    assert lead["gbp_campos_crus"]["ficha_reivindicada"]["estado"] == "CONFIRMADO_AUSENTE"
    assert lead["gbp_campos_crus"]["tem_horario"]["estado"] == "CONFIRMADO_AUSENTE"
    assert lead["gbp_campos_crus"]["detail_scraped"] is True


def test_extractor_opportunity_raw_nao_atravessa_o_contrato():
    emp = _emp(extractor_opportunity_raw="SUSPECT - Shared Website")
    dump = json.dumps(oj.montar([], [_com_site(dados_empresa=emp)], []),
                      ensure_ascii=False).lower()
    assert "extractor_opportunity" not in dump
    assert "shared website" not in dump


def test_reason_to_contact_nunca_aparece_no_contrato():
    qual = _qualificado()["qualificacao"]
    qual["reason_to_contact"] = "4.8★ com 120 avaliações, sem site — vale tentar."
    reg = {"dados_empresa": _emp(website=None, website_status="not_listed_google_maps"),
           "qualificacao": qual, "gbp_diagnostico": _gbp_diag(), "status": "qualified"}
    assert "reason_to_contact" not in json.dumps(oj.montar([reg], [_com_site()], []))


def test_presenca_digital_distingue_site_proprio_de_rede_social():
    social = _com_site(dados_empresa=_emp(website="https://instagram.com/x"))
    saida = oj.montar([], [social], [])
    assert saida["nata"] == [] and saida["candidatos_triagem"] == []
    com = oj.montar([], [_com_site()], [])["candidatos_triagem"][0]
    assert com["presenca_digital"]["tem_site_proprio"]["valor"] is True
    assert com["presenca_digital"]["website_url"]["valor"] == "https://x.es"


def test_descartado_carrega_motivo_e_campos_concretos():
    reprovado = {"dados_empresa": _emp(nota_google=None, review_count=None,
                                        instagram=None, facebook=None),
                 "status": "rejected", "rejection_reason": "qualification_declined"}
    d = oj.montar([], [], [reprovado])["descartados"][0]
    assert d["motivo"] == "qualification_declined"
    assert d["identidade"]["nome"] == "Clínica X"
    assert d["campos_do_corte"]["nota_google"] == {
        "valor": None, "estado": "CONFIRMADO_AUSENTE"}
    assert d["campos_do_corte"]["instagram"] == {
        "valor": None, "estado": "CONFIRMADO_AUSENTE"}


def test_descartado_large_organization_expoe_nicho_e_nome():
    reprovado = {"dados_empresa": _emp(nome="Hospital General", nicho="Hospital"),
                 "status": "rejected", "rejection_reason": "large_organization"}
    d = oj.montar([], [], [reprovado])["descartados"][0]
    assert d["campos_do_corte"]["nicho"]["valor"] == "Hospital"
    assert d["campos_do_corte"]["nome"]["valor"] == "Hospital General"


# --- Pré-condição: fase GBP tem que ter rodado (Achado 3, RODADA REAL 23/09/2026) ---------


def test_gbp_ausente_em_lead_de_candidato_levanta_com_mensagem_acionavel():
    registro = _com_site()
    del registro["gbp_diagnostico"]  # fase_gbp nunca rodou pra este lead

    with pytest.raises(oj.FaseAnteriorAusenteError) as exc:
        oj.montar([], [registro], [])

    msg = str(exc.value)
    assert "gbp_diagnostico" in msg
    assert "python main.py gbp" in msg
    assert "1 lead" in msg
    assert "p1" in msg  # place_id do lead afetado, pra quem for procurar


def test_gbp_ausente_em_lead_de_nata_tambem_levanta():
    registro = _com_site(site_renderizado=_render(mobile={"contato_visivel": False},
                                                    desktop={"contato_visivel": False}))
    del registro["gbp_diagnostico"]

    with pytest.raises(oj.FaseAnteriorAusenteError):
        oj.montar([], [registro], [])


def test_gbp_ausente_conta_cada_lead_afetado():
    a = _com_site(dados_empresa=_emp(place_id="pa"))
    b = _com_site(dados_empresa=_emp(place_id="pb"))
    del a["gbp_diagnostico"]
    del b["gbp_diagnostico"]

    with pytest.raises(oj.FaseAnteriorAusenteError) as exc:
        oj.montar([], [a, b], [])

    msg = str(exc.value)
    assert "2 lead" in msg
    assert "pa" in msg and "pb" in msg


def test_gbp_presente_mas_com_sinais_nao_verificados_nao_levanta():
    """Controle negativo, ponta oposta: gbp_diagnostico EXISTE (fase rodou), mesmo que os
    sinais individuais dentro dele sejam NAO_VERIFICADO -- isso é 'rodou e não mediu
    tudo', não 'não rodou', e não deve disparar o erro novo."""
    registro = _com_site(gbp_diagnostico={
        "score_completude": None, "detail_scraped": False, "sinais": {}, "lacunas": []
    })
    saida = oj.montar([], [registro], [])  # não levanta
    assert len(saida["candidatos_triagem"]) == 1


def test_gbp_ausente_em_lead_que_nem_entraria_na_saida_nao_levanta():
    """Onda1 (qualificados) nunca vira nata/candidatos_triagem -- gbp ausente ali não é
    o defeito que este erro cobre (não quebraria a validação de schema)."""
    qualificado_sem_gbp = _qualificado()
    del qualificado_sem_gbp["gbp_diagnostico"]
    saida = oj.montar([qualificado_sem_gbp], [], [])  # não levanta
    assert saida["nata"] == [] and saida["candidatos_triagem"] == []


def test_gbp_ausente_em_lead_que_vira_espera_nao_levanta():
    """Um com_site 'proprio', sem problema e sem avaliações suficientes pra triagem
    nunca entra em nata/candidatos_triagem (vira Espera, fora do contrato) -- gbp
    ausente nele não quebraria a validação, então não precisa do erro novo aqui."""
    registro = _com_site(dados_empresa=_emp(review_count=5))
    del registro["gbp_diagnostico"]
    saida = oj.montar([], [registro], [])  # não levanta
    assert saida["nata"] == [] and saida["candidatos_triagem"] == []


# --- texto_site (contrato 2.1.0, campo opcional) --------------------------

def test_texto_site_confirmado_presente_prefere_mobile():
    registro = _com_site(site_renderizado=_render(
        mobile={"texto_visivel_normalizado": "Texto do celular"},
        desktop={"texto_visivel_normalizado": "Texto do desktop"},
    ))
    lead = oj.montar([], [registro], [])["candidatos_triagem"][0]
    assert lead["texto_site"]["estado"] == "CONFIRMADO_PRESENTE"
    assert lead["texto_site"]["texto"] == "Texto do celular"
    assert lead["texto_site"]["dispositivo"] == "mobile"


def test_texto_site_cai_para_desktop_quando_mobile_nao_tem_texto():
    """Controle: mobile sem texto (ex.: erro/anti_bot naquele dispositivo) --
    usa o desktop como alternativa, não fica sem nada."""
    registro = _com_site(site_renderizado=_render(
        mobile={"texto_visivel_normalizado": None},
        desktop={"texto_visivel_normalizado": "Texto do desktop"},
    ))
    lead = oj.montar([], [registro], [])["candidatos_triagem"][0]
    assert lead["texto_site"]["estado"] == "CONFIRMADO_PRESENTE"
    assert lead["texto_site"]["dispositivo"] == "desktop"
    assert lead["texto_site"]["texto"] == "Texto do desktop"


def test_texto_site_nao_verificado_quando_nenhum_dispositivo_tem_texto():
    registro = _com_site(site_renderizado=_render(
        mobile={"texto_visivel_normalizado": None}, desktop={"texto_visivel_normalizado": None},
    ))
    lead = oj.montar([], [registro], [])["candidatos_triagem"][0]
    assert lead["texto_site"] == {
        "estado": "NAO_VERIFICADO", "motivo": "renderizacao_nao_mediu_texto", "medido_em": None,
    }


def test_texto_site_trunca_no_limite_configurado_e_marca_truncado():
    texto_longo = "palabra " * 1000  # bem acima do limite de 4000 chars
    registro = _com_site(site_renderizado=_render(mobile={"texto_visivel_normalizado": texto_longo}))
    lead = oj.montar([], [registro], [])["candidatos_triagem"][0]
    campo = lead["texto_site"]
    assert campo["truncado"] is True
    assert campo["chars_originais"] == len(texto_longo)
    assert len(campo["texto"]) == oj.LIMITE_CHARS_TEXTO_SITE


def test_texto_site_nunca_trunca_abaixo_do_limite():
    """Controle negativo: texto curto -- truncado=False, chars_originais bate exato."""
    registro = _com_site(site_renderizado=_render(mobile={"texto_visivel_normalizado": "Texto curto"}))
    lead = oj.montar([], [registro], [])["candidatos_triagem"][0]
    campo = lead["texto_site"]
    assert campo["truncado"] is False
    assert campo["chars_originais"] == len("Texto curto")
    assert campo["texto"] == "Texto curto"
