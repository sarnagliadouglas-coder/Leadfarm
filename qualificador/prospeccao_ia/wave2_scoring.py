"""Onda 2: scoring determinístico, $0, ZERO LLM (não importa anthropic/claude_client em lugar
nenhum deste módulo, de propósito). Não faz rede — só recebe o resultado de
website_analyzer.analisar_site() e decide o score/prioridade. website_analyzer nunca decide
prioridade; este módulo nunca faz request."""
import json
import os

import lead_qualification
import website_analyzer

CAMINHO_CONFIG = os.path.join(os.path.dirname(__file__), "config", "wave2_scoring.json")

CONFIG_DEFAULT = {
    "http": {
        "timeout_seconds": website_analyzer.DEFAULT_TIMEOUT_SECONDS,
        "max_bytes": website_analyzer.DEFAULT_MAX_BYTES,
        "user_agent": website_analyzer.DEFAULT_USER_AGENT,
    },
    "commercial_fit": {
        "weights": {
            "reputation_strong": 35, "reputation_moderate": 20, "reputation_unknown": 15, "reputation_weak": 5,
            "reviews_high": 20, "reviews_medium": 15, "reviews_low": 8, "reviews_minimal": 3, "reviews_none": 0,
            "sinal_valorizado_presente": 10, "cidade_prioritaria": 15, "tem_telefone": 5, "tem_email": 5,
        },
        "reviews_bands": {"high": 100, "medium": 30, "low": 5, "minimal": 1},
    },
    "website_opportunity": {
        "weights": {
            "no_viewport_meta": 20, "no_title_or_short": 10, "no_meta_description": 10, "no_cta_keyword": 15,
            "no_conversion_path": 20, "no_legal_page_link": 5, "no_lang_attribute": 5,
            "images_missing_alt": 5, "slow_response": 10,
        },
        "thresholds": {"short_title_chars": 15, "slow_response_ms": 3000},
    },
    "priority_weights": {"commercial_fit": 0.5, "website_opportunity": 0.5},
    "priority_thresholds": {"alta": 65, "media": 40},
    # Diagnóstico de completude de ficha GBP (gbp_diagnostic.py). Vive aqui só por
    # conveniência de um único arquivo de config -- este módulo não lê esta seção, quem lê é
    # fase_gbp() via gbp_diagnostic. Espelha gbp_diagnostic.CONFIG_DEFAULT.
    "gbp_diagnostic": {
        "weights": {
            "no_ficha_reivindicada": 28, "no_horario": 24, "no_foto_destaque": 22,
            "no_descricao": 16, "no_faixa_preco": 10,
        },
        "informational_only": ["tem_dono_listado", "tem_plus_code"],
        "health_check": {
            "sample_floor": 15, "hard_zero_min_n": 15,
            "near_zero_rate": 0.02, "near_zero_min_n": 50,
        },
    },
    # batch_size/max_runtime_seconds = None (sem limite) -- existiam pra conter custo por
    # execução; a Onda 2 sempre foi $0, mas o limite ficou por cautela/tempo de execução.
    # Removido a pedido do Douglas: "roda a lista completa sem sobrar nenhum".
    "batch_size": None,
    "top_n_display": 15,  # não é limitador de processamento -- só quantas linhas o TOP imprime no terminal
    "max_retry_attempts": 3,  # não é limitador de custo -- é quando desistir de um site que sempre falha
    "max_runtime_seconds": None,
}


def carregar_config_wave2(caminho: str = CAMINHO_CONFIG) -> dict:
    """Mesmo contrato de lead_qualification.carregar_icp(): arquivo ausente/malformado nunca
    quebra o pipeline — cai pros defaults (merge raso por seção)."""
    if not os.path.exists(caminho):
        print(f"[Wave2] Config não encontrada em '{caminho}' — usando defaults.")
        return json.loads(json.dumps(CONFIG_DEFAULT))
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[Wave2] Falha ao ler '{caminho}' ({e}) — usando defaults.")
        return json.loads(json.dumps(CONFIG_DEFAULT))

    resultado = json.loads(json.dumps(CONFIG_DEFAULT))
    for chave, valor in config.items():
        if isinstance(valor, dict) and isinstance(resultado.get(chave), dict):
            resultado[chave].update(valor)
        else:
            resultado[chave] = valor
    return resultado


def website_opportunity_score(analise: dict, weights: dict, thresholds: dict) -> tuple:
    """Só roda se signals_available. Score alto = OPORTUNIDADE comercial (lacunas no site
    atual), nunca uma afirmação de 'o site é ruim' ou consequência não comprovada."""
    if not analise.get("signals_available"):
        return None, []

    sinais = analise["signals"]
    facts = analise["facts"]
    pontos = 0
    razoes = []

    if not sinais["has_viewport_meta"]:
        pontos += weights["no_viewport_meta"]
        razoes.append("sem meta viewport (não otimizado pra mobile)")

    if not sinais["has_title"] or sinais["title_length"] < thresholds["short_title_chars"]:
        pontos += weights["no_title_or_short"]
        razoes.append("título ausente ou muito curto")

    if not sinais["has_meta_description"]:
        pontos += weights["no_meta_description"]
        razoes.append("sem meta description")

    if not sinais["has_cta_keyword"]:
        pontos += weights["no_cta_keyword"]
        razoes.append("nenhuma palavra de chamada à ação identificada (agendar/contactar/reservar)")

    tem_caminho_conversao = sinais["has_form"] or sinais["has_tel_link"] or sinais["has_whatsapp_link"] or sinais["has_email_link"]
    if not tem_caminho_conversao:
        pontos += weights["no_conversion_path"]
        razoes.append("sem formulário, telefone, WhatsApp ou email clicável")

    if not sinais["has_legal_page_link"]:
        pontos += weights["no_legal_page_link"]
        razoes.append("nenhum link de página legal identificado")

    if not sinais["has_lang_attribute"]:
        pontos += weights["no_lang_attribute"]
        razoes.append("atributo lang ausente no HTML")

    if sinais["images_missing_alt_count"] > 0:
        pontos += weights["images_missing_alt"]
        razoes.append(f"{sinais['images_missing_alt_count']} imagem(ns) sem texto alternativo")

    if facts["response_time_ms"] is not None and facts["response_time_ms"] > thresholds["slow_response_ms"]:
        pontos += weights["slow_response"]
        razoes.append(f"resposta lenta ({facts['response_time_ms']:.0f}ms)")

    return max(0, min(100, round(pontos))), razoes


def priority_score(commercial_fit: int, website_opportunity, weights: dict):
    """None se website_opportunity é None — nunca inventa prioridade sem os dois insumos."""
    if website_opportunity is None:
        return None
    return round(commercial_fit * weights["commercial_fit"] + website_opportunity * weights["website_opportunity"])


def priority_label(score, thresholds: dict) -> str:
    if score is None:
        return "needs_review"
    if score >= thresholds["alta"]:
        return "alta"
    if score >= thresholds["media"]:
        return "media"
    return "baixa"


def avaliar_lead(lead: dict, icp: dict, config: dict) -> dict:
    """Orquestra 1 lead: website_analyzer -> commercial_fit_score -> website_opportunity_score
    -> priority. Ponto de entrada único usado por main.py. NUNCA chama LLM."""
    analise = website_analyzer.analisar_site(
        lead.get("website"),
        timeout=config["http"]["timeout_seconds"],
        max_bytes=config["http"]["max_bytes"],
        user_agent=config["http"]["user_agent"],
    )

    cf_score, cf_reasons = lead_qualification.commercial_fit_score(lead, icp, config["commercial_fit"])
    wo_score, wo_reasons = website_opportunity_score(analise, config["website_opportunity"]["weights"], config["website_opportunity"]["thresholds"])
    p_score = priority_score(cf_score, wo_score, config["priority_weights"])
    p_label = priority_label(p_score, config["priority_thresholds"])

    return {
        "website_analysis": analise,
        "commercial_fit": {"score": cf_score, "reasons": cf_reasons},
        "website_opportunity": {"score": wo_score, "reasons": wo_reasons} if wo_score is not None else None,
        "priority_score": p_score,
        "priority_label": p_label,
        "wave2_evaluated_at": website_analyzer._now_iso(),
    }


def ranquear(itens: list) -> list:
    """Ordena por priority_score desc (None sempre por último), desempate por commercial_fit.
    Paralela a lead_qualification.ranquear() -- shape incompatível (aqui não tem 'qualificacao'),
    não é duplicação de lógica de scoring, só de ordenação trivial."""
    def chave(item):
        p = item.get("priority_score")
        cf = (item.get("commercial_fit") or {}).get("score", 0)
        return (p is not None, p if p is not None else -1, cf)

    return sorted(itens, key=chave, reverse=True)
