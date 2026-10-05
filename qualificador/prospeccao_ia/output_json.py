"""Monta o JSON único de saída -- o contrato de handoff QUALIFICADOR -> COMERCIAL.
100% Python, $0, sem LLM.

Contrato (restrições do handoff):
  - Nenhum valor nu: todo campo que pode virar evidência viaja como {"valor", "estado"},
    estado ∈ {CONFIRMADO_PRESENTE, CONFIRMADO_AUSENTE, NAO_VERIFICADO}.
  - estagio_analise é enum EXPLÍCITO: o consumidor faz switch nisso, nunca infere de
    "algum bloco é null".
  - descartados carregam identidade + motivo + os campos concretos que motivaram o corte.
  - Um lead sem site e um lead com site convivem no mesmo array 'leads'.
  - FATO e JULGAMENTO são separados por bloco (contract_version 1.0.0):
      evidencias_qualificador -> fatos coletados (nunca interpretação)
      priorizacao             -> scoring/julgamento do QUALIFICADOR (autoritativo=false;
                                 o COMERCIAL é quem decide)
      analise_tecnica_site    -> metadado do processo de análise (nem fato do lead, nem
                                 julgamento): status/error_type/avaliado_em
  - contract_version é o que o COMERCIAL deve checar; schema_version continua existindo
    como versão interna do formato de trabalho do QUALIFICADOR.
"""
from datetime import datetime, timezone

import contrato
import gbp_diagnostic
import psi_client
import site_classificacao
import site_renderizado
import telefone_utils
from gbp_diagnostic import CONFIRMADO_AUSENTE, CONFIRMADO_PRESENTE, NAO_VERIFICADO

SCHEMA_VERSION = contrato.SCHEMA_VERSION_INTERNO
LIMITE_CHARS_TEXTO_SITE = site_renderizado.carregar_config_texto_site()

ESTAGIO_SEM_SITE = "COMPLETO_SEM_SITE"
ESTAGIO_COM_SITE = "COMPLETO_COM_SITE"

# status de leads_com_site.json que já têm análise (entram na saída). 'queued_future' NÃO
# entra -- ainda pendente, igual a um lead da Onda 1 ainda não qualificado.
_STATUS_ONDA2_PRONTOS = {"analyzed", "needs_review", "unavailable_permanent"}

# sinal do gbp_diagnostico -> campo cru correspondente no lead (pro bloco gbp_campos_crus).
_SINAL_PARA_CAMPO_CRU = {
    "ficha_reivindicada": "gbp_reivindicada",
    "tem_horario": "gbp_horario",
    "tem_foto_destaque": "gbp_foto_destaque",
    "tem_descricao": "gbp_descricao",
    "tem_faixa_preco": "gbp_faixa_preco",
    "tem_plus_code": "gbp_plus_code",
    "tem_dono_listado": "gbp_dono",
}

# motivo do corte -> campos do lead a expor em campos_do_corte (além de identidade + motivo).
_CAMPOS_POR_MOTIVO = {
    "large_organization": ["nome", "nicho"],
    "no_contact_no_signal": ["telefone", "email", "nota_google"],
    "sem_canal_de_contato": ["telefone", "email", "instagram", "facebook"],
    "qualification_declined": ["nota_google", "review_count", "instagram", "facebook"],
    "icp_categoria_fora_do_perfil": ["nicho"],
    "icp_categoria_excluida": ["nicho"],
    "icp_rating_abaixo_minimo": ["nota_google"],
    "icp_reviews_abaixo_minimo": ["review_count"],
    # contract_version 2.2.0: filtro de redes / multiunidade (rede_multiunidade.py).
    "rede_ou_multiunidade": ["nome", "telefone", "website"],
    # contract_version 2.2.0: linha de CSV deslocada sem recuperação segura (agent_coletor).
    "linha_deslocada_irrecuperavel": ["nicho"],
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _campo_verificado(valor, presente_quando=None):
    """Wrapper {valor, estado} pros campos do list-scrape (telefone, email, nota...). O
    list-scrape sempre roda, então vazio = CONFIRMADO_AUSENTE (genuinamente não listado),
    nunca NAO_VERIFICADO."""
    presente = presente_quando(valor) if presente_quando else (valor not in (None, "", []))
    return {"valor": valor, "estado": CONFIRMADO_PRESENTE if presente else CONFIRMADO_AUSENTE}


def _identidade(emp):
    return {
        "nome": emp.get("nome"),
        "nicho": emp.get("nicho"),
        "cidade": emp.get("cidade"),
        "endereco": emp.get("endereco"),
        "google_maps_url": emp.get("google_maps_url"),
    }


def _contato(emp):
    tel = emp.get("telefone")
    email = emp.get("email")
    insta = emp.get("instagram")
    face = emp.get("facebook")
    # Mesma regra do filtro de contatabilidade da Onda 1 -- agora numa função só
    # (telefone_utils), antes eram duas implementações separadas.
    whatsapp_apto = bool(email or insta or face) or telefone_utils.e_movel_espanhol(tel)
    return {
        "telefone": _campo_verificado(tel),
        "email": _campo_verificado(email),
        "instagram": _campo_verificado(insta),
        "facebook": _campo_verificado(face),
        # contract_version 1.1.0: só transporte de evidência para o COMERCIAL.
        # NÃO entra em whatsapp_apto nem em nenhum score.
        "linkedin": _campo_verificado(emp.get("linkedin")),
        "whatsapp_apto": whatsapp_apto,
    }


def _campo_do_import(emp, campo):
    """contract_version 2.2.0: campo gravado pelo import (carimbo da campanha). Lead
    importado antes de existir o campo -> NAO_VERIFICADO, nunca valor inventado."""
    if campo not in emp:
        return {"valor": None, "estado": NAO_VERIFICADO}
    return _campo_verificado(emp.get(campo))


def _possivel_mesmo_negocio(emp):
    """contract_version 2.2.0: aviso do filtro de redes (grupo de 2 fichas por telefone ou
    domínio próprio). Ausente = lead anterior ao filtro (NAO_VERIFICADO); [] = checado, sem
    par (CONFIRMADO_AUSENTE); lista = place_id(s) da(s) outra(s) ficha(s).

    Uma entrada por place_id: quando o par divide telefone E domínio, fica só a 1ª
    ocorrência (ordem estável; rede_multiunidade.agrupar põe telefone antes de domínio) --
    mesma deduplicação do CSV humano (saida_humana._possivel_mesmo_negocio)."""
    if "possivel_mesmo_negocio" not in emp:
        return {"valor": None, "estado": NAO_VERIFICADO}
    pares = emp.get("possivel_mesmo_negocio") or []
    if not pares:
        return {"valor": None, "estado": CONFIRMADO_AUSENTE}
    valor, vistos = [], set()
    for p in pares:
        pid = p.get("place_id")
        if pid in vistos:
            continue
        vistos.add(pid)
        valor.append({"place_id": pid, "por": p.get("por"), "chave": p.get("chave")})
    return {"valor": valor, "estado": CONFIRMADO_PRESENTE}


def _reputacao(emp):
    return {
        "nota_google": _campo_verificado(emp.get("nota_google"), presente_quando=lambda v: v is not None),
        "review_count": _campo_verificado(emp.get("review_count"), presente_quando=lambda v: v is not None),
        "reputation_signal": emp.get("reputation_signal") or "unknown",
    }


def _presenca_digital(emp):
    status = emp.get("website_status")
    website = emp.get("website")
    tem_site = status == "listed"
    social = website if (website and status == "not_listed_google_maps") else None
    return {
        "tem_site_proprio": {"valor": tem_site, "estado": CONFIRMADO_PRESENTE if tem_site else CONFIRMADO_AUSENTE},
        "website_url": {"valor": website if tem_site else None,
                        "estado": CONFIRMADO_PRESENTE if tem_site else CONFIRMADO_AUSENTE},
        "site_via_rede_social": {"valor": social,
                                 "estado": CONFIRMADO_PRESENTE if social else CONFIRMADO_AUSENTE},
    }


def _gbp_campos_crus(emp, gbp_diag):
    """Valor cru + estado (herdado do gbp_diagnostico). detail_scraped como campo próprio."""
    sinais = (gbp_diag or {}).get("sinais") or {}
    crus = {}
    for sinal, campo in _SINAL_PARA_CAMPO_CRU.items():
        estado = (sinais.get(sinal) or {}).get("estado", NAO_VERIFICADO)
        crus[sinal] = {"valor": emp.get(campo), "estado": estado}
    crus["detail_scraped"] = (gbp_diag or {}).get("detail_scraped", False)
    return crus


# --- FATO: evidências do qualificador -------------------------------------------------------

_CANAL_CONVERSAO = [
    ("has_form", "formulário"),
    ("has_tel_link", "telefone clicável"),
    ("has_whatsapp_link", "WhatsApp"),
    ("has_email_link", "email clicável"),
]


def _fatos_de_sinais(sinais):
    """Onda 2: relato NEUTRO do que o website_analyzer encontrou no HTML -- descreve o
    que está/não está presente, sem 'bom'/'ruim'/'oportunidade' (isso é priorizacao).
    Deriva de 'sinais' (o dict cru também vai inteiro em evidencias_qualificador.sinais_site)."""
    if not sinais:
        return []
    fatos = []
    fatos.append("título presente" if sinais.get("has_title") else "sem título no HTML")
    fatos.append("meta description presente" if sinais.get("has_meta_description") else "sem meta description no HTML")
    fatos.append("meta viewport presente" if sinais.get("has_viewport_meta") else "sem meta viewport no HTML")
    if sinais.get("has_lang_attribute"):
        fatos.append(f"atributo lang no HTML: {sinais.get('html_lang')}")
    else:
        fatos.append("sem atributo lang no HTML")
    canais = [rotulo for chave, rotulo in _CANAL_CONVERSAO if sinais.get(chave)]
    fatos.append("caminhos de contato no HTML: " + ", ".join(canais) if canais
                 else "nenhum caminho de contato (formulário/telefone/WhatsApp/email) no HTML")
    fatos.append("link de página legal presente no HTML" if sinais.get("has_legal_page_link")
                 else "sem link de página legal no HTML")
    fatos.append("palavra de chamada à ação encontrada no HTML" if sinais.get("has_cta_keyword")
                 else "nenhuma palavra de chamada à ação encontrada no HTML")
    fatos.append(f"{sinais.get('images_missing_alt_count') or 0} de {sinais.get('image_count') or 0} "
                 f"imagem(ns) sem texto alternativo")
    fatos.append(f"{sinais.get('script_count') or 0} tag(s) <script> no HTML")
    return fatos


def _evidencias_qualificador(registro, onda2):
    if onda2:
        sinais = (registro.get("website_analysis") or {}).get("signals")
        return {"fatos": _fatos_de_sinais(sinais), "sinais_site": sinais or None}
    qual = registro.get("qualificacao") or {}
    return {"fatos": qual.get("evidence") or [], "sinais_site": None}


# --- JULGAMENTO: priorização do qualificador (não autoritativa) -----------------------------

def _priorizacao(registro, onda2):
    if onda2:
        cf = registro.get("commercial_fit") or {}
        wo = registro.get("website_opportunity")
        return {
            "autoritativo": False,
            "commercial_fit_score": cf.get("score"),
            "priority": None,                       # 'priority' é rótulo da Onda 1
            "contactability": None,                 # exclusivo da Onda 1
            "risks": None,                          # exclusivo da Onda 1
            "reasons": cf.get("reasons") or [],     # breakdown do commercial_fit (roda nas 2 ondas)
            "website_opportunity_score": (wo or {}).get("score") if wo else None,
            "priority_score": registro.get("priority_score"),
            "priority_label": registro.get("priority_label"),
            "lacunas_interpretadas": ((wo or {}).get("reasons") or []) if wo else [],
        }
    qual = registro.get("qualificacao") or {}
    return {
        "autoritativo": False,
        "commercial_fit_score": qual.get("score"),
        "priority": qual.get("priority"),
        "contactability": qual.get("contactability"),
        "risks": qual.get("risks") or [],
        "reasons": qual.get("reasons") or [],
        "website_opportunity_score": None,
        "priority_score": None,
        "priority_label": None,
        "lacunas_interpretadas": None,
    }


# --- METADADO: processo de análise técnica do site ----------------------------------------

def _analise_tecnica_site(registro, onda2):
    if not onda2:
        return {
            "status": None, "error_type": None, "avaliado_em": None,
            "telefone_na_pagina": {"valor": None, "estado": NAO_VERIFICADO},
        }
    wa = registro.get("website_analysis") or {}
    render = registro.get("site_renderizado") or {}
    por_dispositivo = render.get("resultado", {}).get("por_dispositivo", {})
    telefone = _telefone_na_pagina(render, por_dispositivo)
    return {
        "status": wa.get("status"),
        "error_type": wa.get("error_type"),
        "avaliado_em": registro.get("wave2_evaluated_at"),
        "telefone_na_pagina": telefone,
    }


def _telefone_na_pagina(render, por_dispositivo):
    if render.get("estado") != site_renderizado.ESTADO_MEDIDO:
        return {"valor": None, "estado": NAO_VERIFICADO}
    dispositivos = list(por_dispositivo.values())
    if any(d.get("has_tel_link") or d.get("telefone_clicavel") is True for d in dispositivos):
        return {"valor": "link", "estado": CONFIRMADO_PRESENTE}
    if any(d.get("telefone_clicavel") is False for d in dispositivos):
        return {"valor": "texto", "estado": CONFIRMADO_PRESENTE}
    return {"valor": None, "estado": CONFIRMADO_AUSENTE}


def _coleta_render(render, por_dispositivo):
    refs = {d: r.get("screenshot_ref") for d, r in por_dispositivo.items() if r.get("screenshot_ref")}
    datas = [r.get("coletado_em") for r in por_dispositivo.values() if r.get("coletado_em")]
    return refs, max(datas) if datas else render.get("avaliado_em")


def _problemas_vendaveis(registro):
    render = registro.get("site_renderizado") or {}
    por_dispositivo = (render.get("resultado") or {}).get("por_dispositivo") or {}
    problemas = []
    if render.get("estado") == site_renderizado.ESTADO_MEDIDO:
        if por_dispositivo and all(r.get("contato_visivel") is False for r in por_dispositivo.values()):
            _, coletado_em = _coleta_render(render, por_dispositivo)
            problemas.append({
                "tipo": "sem_contato_visivel",
                "evidencia": "contato_visivel=false em mobile e desktop",
                "medicao": "site_renderizado",
                "coletado_em": coletado_em,
            })

    psi = registro.get("psi") or {}
    if psi.get("estado") == psi_client.CONFIRMADO_PRESENTE and (psi.get("lcp_ms") or 0) > 4000:
        # 4000 ms é PROVISÓRIO (corte oficial do Google); está em estudo corte acima de
        # 8000 ms ou nota de desempenho abaixo de 50.
        problemas.append({
            "tipo": "lento_no_celular",
            "evidencia": f"psi.lcp_ms={psi['lcp_ms']} > 4000",
            "medicao": "psi",
            "coletado_em": psi.get("medido_em"),
        })

    # fora_do_ar só quando TODOS os dispositivos medidos falharam (cada um já depois da
    # repetição de site_renderizado._fetch_dispositivo). Um falha e o outro abre normal é
    # "instavel" -- achado real (FISIOFICTICIA, 24/09/2026): um timeout isolado no desktop,
    # com o celular ok, entrou na nata como fora_do_ar por engano. anti_bot e 403 nunca
    # contam como falha (site_renderizado.indica_falha_dispositivo).
    if por_dispositivo and site_renderizado.avaliar_estabilidade(por_dispositivo) == site_renderizado.ESTABILIDADE_FALHA:
        dispositivos_falhos = sorted(por_dispositivo)
        evidencias = []
        coletados_em = []
        for dispositivo in dispositivos_falhos:
            resultado = por_dispositivo[dispositivo]
            status = resultado.get("http_status")
            erro_tipo = resultado.get("erro_tipo")
            evidencias.append(
                f"{dispositivo}: " + (f"http_status={status}" if status is not None else f"erro_tipo={erro_tipo}")
            )
            if resultado.get("coletado_em"):
                coletados_em.append(resultado["coletado_em"])
        problemas.append({
            "tipo": "fora_do_ar",
            "evidencia": "; ".join(evidencias),
            "medicao": "site_renderizado",
            "coletado_em": max(coletados_em) if coletados_em else None,
        })
    return problemas


def _texto_site(por_dispositivo):
    """Campo `texto_site` do contrato (2.1.0, opcional): texto visível do
    site, preferindo `mobile`, com `desktop` como alternativa. Mesmo
    vocabulário de `psi` -- NÃO é `{valor, estado}`: `None` puro quando a
    renderização não mediu nenhum dos dois dispositivos (nem
    `por_dispositivo` existe), `{estado: NAO_VERIFICADO, ...}` quando
    mediu mas nenhum dos dois capturou texto (erro/anti_bot/http_erro nos
    dois), ou objeto completo com `estado: CONFIRMADO_PRESENTE`."""
    for dispositivo in ("mobile", "desktop"):
        resultado = (por_dispositivo or {}).get(dispositivo) or {}
        texto = resultado.get("texto_visivel_normalizado")
        if texto:
            chars_originais = len(texto)
            return {
                "estado": CONFIRMADO_PRESENTE,
                "texto": texto[:LIMITE_CHARS_TEXTO_SITE],
                "chars_originais": chars_originais,
                "truncado": chars_originais > LIMITE_CHARS_TEXTO_SITE,
                "dispositivo": dispositivo,
                "coletado_em": resultado.get("coletado_em"),
            }
    if not por_dispositivo:
        return None
    return {"estado": NAO_VERIFICADO, "motivo": "renderizacao_nao_mediu_texto", "medido_em": None}


def _lead_site(registro):
    emp = registro.get("dados_empresa") or {}
    classe = emp.get("classe_site") or site_classificacao.classificar_site(emp.get("website"))
    if classe != site_classificacao.PROPRIO:
        return None
    lead = _lead_saida(registro, ESTAGIO_COM_SITE)
    problemas = _problemas_vendaveis(registro)
    lead["classe_site"] = classe
    lead["problema_vendavel"] = problemas
    render = registro.get("site_renderizado") or {}
    por_dispositivo = (render.get("resultado") or {}).get("por_dispositivo") or {}
    lead["texto_site"] = _texto_site(por_dispositivo)
    refs, coletado_em = _coleta_render(render, por_dispositivo)
    review_count = emp.get("review_count")
    if not problemas and isinstance(review_count, (int, float)) and review_count >= 10:
        lead["candidato_triagem_visual"] = {
            "captura_ref": refs.get("mobile") or refs.get("desktop"),
            "coletado_em": coletado_em,
        }
        return "candidatos_triagem", lead
    if problemas:
        lead.pop("candidato_triagem_visual", None)
        return "nata", lead
    return None


def _lead_saida(registro, estagio):
    emp = registro.get("dados_empresa") or {}
    gbp_diag = registro.get("gbp_diagnostico")
    onda2 = estagio == ESTAGIO_COM_SITE
    return {
        "place_id": emp.get("place_id"),
        "estagio_analise": estagio,
        "campanha_id": _campo_do_import(emp, "campanha_id"),
        "campanha_nicho": _campo_do_import(emp, "campanha_nicho"),
        "possivel_mesmo_negocio": _possivel_mesmo_negocio(emp),
        "identidade": _identidade(emp),
        "contato": _contato(emp),
        "reputacao": _reputacao(emp),
        "presenca_digital": _presenca_digital(emp),
        "gbp_diagnostico": gbp_diag,
        "gbp_campos_crus": _gbp_campos_crus(emp, gbp_diag),
        "evidencias_qualificador": _evidencias_qualificador(registro, onda2),
        "priorizacao": _priorizacao(registro, onda2),
        "analise_tecnica_site": _analise_tecnica_site(registro, onda2),
        "psi": _psi(registro, estagio),
    }


def _psi(registro, estagio):
    """Lead sem site nunca tem PSI (não há URL). Lead com site sem medição -> NAO_VERIFICADO
    explícito (fase_psi pulada / degradada), nunca null silencioso."""
    if estagio != ESTAGIO_COM_SITE:
        return None
    return registro.get("psi") or {"estado": NAO_VERIFICADO, "motivo": "não medido", "medido_em": None}


# --- Pré-condição: fase anterior obrigatória já rodou --------------------------------------


class FaseAnteriorAusenteError(Exception):
    """Uma fase anterior obrigatória (GBP) não rodou para lead(s) que entrariam no
    contrato. Sem esta checagem, a validação de schema (contrato.validar) falha com
    algo como "None is not of type 'object'" em 'candidatos_triagem/N/gbp_diagnostico'
    -- verdadeiro, mas não diz a causa real (achado real, RODADA REAL 23/09/2026,
    REGISTRO-QUEBRAS.md). Levantado ANTES da validação de schema; nada é gravado."""


def _verificar_gbp_presente(nata, candidatos_triagem):
    """`main.fase_gbp()` roda ANTES da bifurcação Onda 1/2 e grava `gbp_diagnostico` em
    TODO registro que tem `dados_empresa`, sempre como objeto completo -- não é uma fase
    opcional como PSI/render (que degradam para NAO_VERIFICADO quando desligadas por
    config). Por isso `gbp_diagnostico` ausente (`None`) só tem UMA leitura possível: a
    fase GBP não rodou ainda para esse lead -- nunca "rodou e não mediu". Detecta antes
    da validação de schema, que reprovaria com uma mensagem que não aponta a causa."""
    faltando = [lead.get("place_id") or "(sem place_id)" for lead in nata + candidatos_triagem
                if lead.get("gbp_diagnostico") is None]
    if not faltando:
        return
    amostra = ", ".join(faltando[:10])
    resto = f" (+{len(faltando) - 10} outro(s))" if len(faltando) > 10 else ""
    raise FaseAnteriorAusenteError(
        f"{len(faltando)} lead(s) sem 'gbp_diagnostico' -- a fase GBP não rodou ainda "
        f"para eles. Rode 'python main.py gbp' antes de 'python main.py saida'. "
        f"place_id(s): {amostra}{resto}."
    )


def _descartado_saida(registro):
    emp = registro.get("dados_empresa") or {}
    motivo = registro.get("rejection_reason", "unknown")
    campos = {}
    for campo in _CAMPOS_POR_MOTIVO.get(motivo, []):
        presente_quando = (lambda v: v is not None) if campo in ("nota_google", "review_count") else None
        campos[campo] = _campo_verificado(emp.get(campo), presente_quando)
    # 2.2.0: o detalhe do corte gravado no import (categoria que causou o corte de
    # campanha; grupo de rede com por/chave/tamanho_grupo; padrão de linha deslocada)
    # atravessa como fato.
    detalhe = registro.get("rejection_detail")
    if detalhe:
        campos["detalhe_do_corte"] = {"valor": detalhe, "estado": CONFIRMADO_PRESENTE}
    return {
        "place_id": emp.get("place_id"),
        "campanha_id": _campo_do_import(emp, "campanha_id"),
        "campanha_nicho": _campo_do_import(emp, "campanha_nicho"),
        "identidade": {"nome": emp.get("nome"), "nicho": emp.get("nicho"), "cidade": emp.get("cidade")},
        "motivo": motivo,
        "campos_do_corte": campos,
    }


def montar(qualificados, com_site, reprovados, origem_csv=None):
    """qualificados = leads_qualificados.json (Onda 1, status 'qualified').
    com_site = leads_com_site.json (Onda 2; só os com análise entram).
    reprovados = leads_reprovados.json (todos os cortes).
    origem_csv = nome do CSV do EXTRATOR usado nesta rodada (rastreabilidade)."""
    nata = []
    candidatos_triagem = []
    for r in com_site:
        if r.get("status") in _STATUS_ONDA2_PRONTOS and r.get("dados_empresa"):
            classificado = _lead_site(r)
            if classificado:
                lista, lead = classificado
                (nata if lista == "nata" else candidatos_triagem).append(lead)

    _verificar_gbp_presente(nata, candidatos_triagem)

    descartados = [_descartado_saida(r) for r in reprovados if r.get("dados_empresa")]

    pendentes_onda2 = sum(1 for r in com_site if r.get("status") == "queued_future")

    # Recomputa o health-check do GBP sobre a população inteira (determinístico, barato) pra
    # levar os avisos de "seletor provavelmente quebrado no extractor" pra dentro da saída --
    # o COMERCIAL precisa saber que um campo veio NAO_VERIFICADO em massa, não campo a campo.
    todos = [r["dados_empresa"] for r in list(qualificados) + list(com_site) if r.get("dados_empresa")]
    _rebaixados, gbp_avisos = gbp_diagnostic.avaliar_saude_do_lote(todos)

    return {
        "contract_version": contrato.CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "origem_csv": origem_csv,
        "stats": {
            "nata": len(nata),
            "candidatos_triagem": len(candidatos_triagem),
            "leads_total": len(nata) + len(candidatos_triagem),
            "sem_site": 0,
            "com_site": len(nata) + len(candidatos_triagem),
            "descartados": len(descartados),
            "onda2_ainda_pendente": pendentes_onda2,
            "gbp_field_warnings": gbp_avisos,
        },
        "nata": nata,
        "candidatos_triagem": candidatos_triagem,
        "descartados": descartados,
    }
