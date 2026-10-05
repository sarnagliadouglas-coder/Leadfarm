"""Pré-filtro ICP, qualificação da Onda 1 (qualificar_onda1) e ranking. 100% Python, custo $0,
nunca chama LLM — a Onda 1 inteira roda sem API, igual à Onda 2 (ver seção 5 do funil original:
eliminar candidatos óbvios antes de gastar dinheiro; hoje isso vale pro funil inteiro)."""
import json
import os

import telefone_utils

CAMINHO_ICP = os.path.join(os.path.dirname(__file__), "config", "ideal_customer_profile.json")

# Categorias NÃO moram mais no ICP (decisão do diretor, 04/10/2026): a única fonte é a
# campanha ativa (campanha.py, EQC/config/campanha_ativa.json), aplicada no import antes da
# separação em ondas. Chave de categoria esquecida num ICP antigo é ignorada.
ICP_DEFAULT = {
    "rating_minimo": 0,
    "reviews_minimo": 0,
    "cidades_prioritarias": [],
    "sinais_valorizados": {"sem_site": True, "instagram_ativo": True, "facebook_ativo": False},
}

ORDEM_PRIORIDADE = {"alta": 2, "media": 1, "baixa": 0}


def carregar_icp(caminho: str = CAMINHO_ICP) -> dict:
    """Nunca quebra o pipeline: config ausente ou malformada vira defaults 100% permissivos
    (nenhum lead é cortado por engano) + aviso no console."""
    if not os.path.exists(caminho):
        print(f"[ICP] Config não encontrada em '{caminho}' — usando defaults permissivos.")
        return dict(ICP_DEFAULT)
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            icp = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[ICP] Falha ao ler '{caminho}' ({e}) — usando defaults permissivos.")
        return dict(ICP_DEFAULT)
    return {**ICP_DEFAULT, **icp}


def icp_tem_filtro_ativo(icp: dict) -> bool:
    """True se o ICP tem QUALQUER corte configurado. Com a config padrão (listas vazias e
    pisos em 0) o pré-filtro não reprova ninguém — o relatório usa isto pra dizer
    "nenhum filtro configurado" em vez de deixar parecer que a etapa falhou. Reputação
    nunca corta por padrão (decisão do Douglas: nota é sinal, não gate). Categoria não conta:
    vive na campanha ativa (campanha.py), não no ICP."""
    return bool(
        (icp.get("rating_minimo") or 0) > 0
        or (icp.get("reviews_minimo") or 0) > 0
    )


def _motivo_exclusao_icp(lead: dict, icp: dict) -> str | None:
    """Só corta por rating/reviews CONHECIDOS abaixo do piso configurado. Nunca corta por
    ausência de dado, e rating/reviews ficam desligados por padrão (piso 0) — reputação é
    sinal, nunca gate automático. Categoria NÃO é critério daqui (04/10/2026): o corte de
    categoria é da campanha ativa, no import (campanha.motivo_categoria)."""
    rating_minimo = icp.get("rating_minimo") or 0
    nota = lead.get("nota_google")
    if rating_minimo > 0 and nota is not None and nota < rating_minimo:
        return "icp_rating_abaixo_minimo"

    reviews_minimo = icp.get("reviews_minimo") or 0
    reviews = lead.get("review_count")
    if reviews_minimo > 0 and reviews is not None and reviews < reviews_minimo:
        return "icp_reviews_abaixo_minimo"

    return None


def filtrar_icp(leads: list[dict], icp: dict) -> tuple[list[dict], list[dict]]:
    """Pré-filtro NOVO, além do filtro comercial que já existe em agent_coletor.py. Devolve
    (aprovados, reprovados) — cada reprovado já vem com 'rejection_reason' anexado, no mesmo
    estilo de AgentColetor._aplicar_filtros_comerciais, pra reaproveitar a persistência em
    leads_reprovados.json sem mudar seu formato."""
    aprovados, reprovados = [], []
    for lead in leads:
        motivo = _motivo_exclusao_icp(lead, icp)
        if motivo:
            lead["rejection_reason"] = motivo
            reprovados.append(lead)
        else:
            aprovados.append(lead)
    return aprovados, reprovados


# --- Filtro de contatabilidade (exclusivo da Onda 1 -- decisão do Douglas) ----------------------
#
# Só a Onda 1 tem esse problema: um lead sem site só pode ser abordado por email, rede social
# ou WhatsApp -- não existe canal a mais. Sem este filtro, um lead sem NENHUM dos três entra na
# esteira, é qualificado, ganha copy... e não há como enviar nada, porque não sobra endereço
# nenhum pra mandar. É trabalho jogado fora, e o lead some do relatório sem explicação (fica
# "qualificado" pra sempre, nunca contactado).
#
# NÃO se aplica à Onda 2: lá um lead pode valer a pena mesmo sem email/rede/celular aparente --
# o site já é o produto sendo avaliado, e o link do site em si é uma forma de abordagem (a copy
# da Onda 2 nem é gerada por este sistema).
#
# 6 e 7 são os dois prefixos de celular espanhol -- só eles recebem WhatsApp. 8/9 são fixo.
# A regra em si (normalização + prefixo) vive em telefone_utils, compartilhada com
# output_json._contato (antes eram duas implementações separadas). Estes wrappers
# ficam só pra não quebrar quem já importa lead_qualification._e_movel_espanhol.
def _numero_nacional_espanhol(telefone) -> str:
    return telefone_utils.numero_nacional_espanhol(telefone)


def _e_movel_espanhol(telefone) -> bool:
    return telefone_utils.e_movel_espanhol(telefone)


def _motivo_exclusao_contato_onda1(lead: dict) -> str | None:
    tem_canal_digital = bool(lead.get("email")) or bool(lead.get("instagram")) or bool(lead.get("facebook"))
    if tem_canal_digital:
        return None
    if _e_movel_espanhol(lead.get("telefone")):
        return None
    return "sem_canal_de_contato"


def filtrar_contactabilidade_onda1(leads: list[dict]) -> tuple[list[dict], list[dict]]:
    """Mesmo estilo de filtrar_icp: devolve (aprovados, reprovados), cada reprovado já com
    'rejection_reason' anexado. Chamar SÓ no funil da Onda 1 (ver docstring acima) -- a Onda 2
    não usa isto."""
    aprovados, reprovados = [], []
    for lead in leads:
        motivo = _motivo_exclusao_contato_onda1(lead)
        if motivo:
            lead["rejection_reason"] = motivo
            reprovados.append(lead)
        else:
            aprovados.append(lead)
    return aprovados, reprovados


def ranquear(itens_qualificados: list[dict]) -> list[dict]:
    """Puro Python, só ordena — nunca filtra, nunca recalcula score. Cada item:
    {"dados_empresa": {...lead...}, "qualificacao": {...saída de qualificar_onda1...}, "status": ...}.
    Desempate: score > prioridade > nº de avaliações (mais dado disponível = mais confiável)."""
    def chave(item):
        qual = item.get("qualificacao", {})
        lead = item.get("dados_empresa", {})
        prioridade = ORDEM_PRIORIDADE.get((qual.get("priority") or "").lower(), 0)
        return (qual.get("score", 0), prioridade, lead.get("review_count") or 0)

    return sorted(itens_qualificados, key=chave, reverse=True)


def separar_top_n(itens_ranqueados: list[dict], top_n: int | None) -> tuple[list[dict], list[dict]]:
    """Slicing puro: (top_n primeiros, resto) — resto fica esperando a próxima rodada, sem
    perder a avaliação da Qualification já paga. top_n=None = sem limite (tudo vira "top",
    resto sempre vazio) — cuidado: NÃO dá pra fazer isso com slicing puro
    (itens[:None] == itens[None:] == itens inteiro, dobraria a lista)."""
    if top_n is None:
        return list(itens_ranqueados), []
    return itens_ranqueados[:top_n], itens_ranqueados[top_n:]


COMMERCIAL_FIT_CONFIG_DEFAULT = {
    "weights": {
        "reputation_strong": 35, "reputation_moderate": 20, "reputation_unknown": 15, "reputation_weak": 5,
        "reviews_high": 20, "reviews_medium": 15, "reviews_low": 8, "reviews_minimal": 3, "reviews_none": 0,
        "sinal_valorizado_presente": 10, "cidade_prioritaria": 15, "tem_telefone": 5, "tem_email": 5,
    },
    "reviews_bands": {"high": 100, "medium": 30, "low": 5, "minimal": 1},
}


def _faixa_reviews(review_count, bands):
    if review_count is None:
        return "none"
    if review_count >= bands["high"]:
        return "high"
    if review_count >= bands["medium"]:
        return "medium"
    if review_count >= bands["low"]:
        return "low"
    if review_count >= bands["minimal"]:
        return "minimal"
    return "none"


def commercial_fit_score(lead: dict, icp: dict, config: dict | None = None) -> tuple[int, list[str]]:
    """Score 0-100 determinístico, $0, NUNCA chama LLM. Usado pela Onda 2 (que não pode gastar
    API) — reaproveita _motivo_exclusao_icp (o mesmo gate que filtrar_icp já usa) em vez de
    reimplementar a decisão de categoria/rating/reviews mínimo, e o mesmo campo
    reputation_signal que agent_coletor.py já grava no lead."""
    config = config or COMMERCIAL_FIT_CONFIG_DEFAULT
    pesos = config["weights"]

    motivo = _motivo_exclusao_icp(lead, icp)
    if motivo:
        return 0, [f"excluído pelo ICP: {motivo}"]

    pontos = 0
    razoes = []

    reputacao = lead.get("reputation_signal") or "unknown"
    chave_reputacao = f"reputation_{reputacao}"
    if chave_reputacao in pesos:
        pontos += pesos[chave_reputacao]
        razoes.append(f"reputação: sinal '{reputacao}' (+{pesos[chave_reputacao]})")

    faixa = _faixa_reviews(lead.get("review_count"), config["reviews_bands"])
    chave_reviews = f"reviews_{faixa}"
    if chave_reviews in pesos and pesos[chave_reviews]:
        pontos += pesos[chave_reviews]
        razoes.append(f"volume de avaliações: faixa '{faixa}' (+{pesos[chave_reviews]})")

    sinais_valorizados = icp.get("sinais_valorizados") or {}
    if sinais_valorizados.get("instagram_ativo") and lead.get("instagram"):
        pontos += pesos["sinal_valorizado_presente"]
        razoes.append("Instagram ativo (sinal valorizado pelo ICP)")
    if sinais_valorizados.get("facebook_ativo") and lead.get("facebook"):
        pontos += pesos["sinal_valorizado_presente"]
        razoes.append("Facebook ativo (sinal valorizado pelo ICP)")

    cidades_prioritarias = [c.lower() for c in (icp.get("cidades_prioritarias") or [])]
    cidade_lead = (lead.get("cidade") or "").lower()
    if cidades_prioritarias and cidade_lead and cidade_lead in cidades_prioritarias:
        pontos += pesos["cidade_prioritaria"]
        razoes.append(f"cidade prioritária: {lead.get('cidade')}")

    if lead.get("telefone"):
        pontos += pesos["tem_telefone"]
        razoes.append("telefone disponível")
    if lead.get("email"):
        pontos += pesos["tem_email"]
        razoes.append("email disponível")

    return max(0, min(100, round(pontos))), razoes


# --- Qualificação da Onda 1 (antes era um LLM -- decisão tomada com o Douglas) -----------------
#
# O skill que orientava o LLM (skills/lead-qualification/SKILL.md, removido) já descrevia regras
# de threshold, não julgamento aberto: "dados quase todos ausentes = reprova", "reputação
# forte/moderada = prioridade alta" etc. Como a Onda 1 usa template fixo (não personalização por
# LLM) e opera em volume, o texto livre que a LLM produzia (reason_to_contact/reasons/risks) não
# alimentava nada além do relatório -- por isso a decisão foi portar tudo pra Python, mesmo
# estilo de commercial_fit_score (já usado pela Onda 2): determinístico, $0, sem API.
#
# Cortes PRÓPRIOS da Onda 1 -- deliberadamente diferentes do priority_thresholds 65/40 da Onda 2
# (config/wave2_scoring.json). Reusar 65/40 aqui era um erro medido: o score da Onda 2 combina
# fit comercial COM análise técnica do site, enquanto a Onda 1 (leads sem site) só tem os sinais
# comerciais. Com o ICP padrão (cidades_prioritarias vazia) o teto aqui é 75, não 100, e o máximo
# observado nos 34 leads reais foi 60 -- ou seja, "alta" (65) era inalcançável e o bucket ficava
# permanentemente vazio.
#
# Calibrado contra o histograma real desses 34 leads: {13:1, 20:6, 33:2, 38:1, 40:1, 43:4, 48:10,
# 55:8, 60:1}. 55/40 dá 9 alta / 15 media / 10 baixa -- as três faixas povoadas. Note que o score
# é grosso (soma de poucos pesos fixos, só 9 valores distintos em 34 leads): NÃO existe threshold
# que reproduza a distribuição da antiga Qualification LLM (4/22/1) -- qualquer corte entre 49 e
# 55 dá alta=9, e qualquer corte entre 56 e 60 dá alta=1. Perseguir aquele número exato seria
# ajustar a régua ao resultado de um modelo que não roda mais; o critério aqui é que os três
# baldes sejam usáveis pra ordenar o dia de trabalho.
LIMIARES_QUALIFICACAO_ONDA1 = {"alta": 55, "media": 40}


def _rotulo_prioridade_por_score(score: int, limiares: dict) -> str:
    if score >= limiares["alta"]:
        return "alta"
    if score >= limiares["media"]:
        return "media"
    return "baixa"


def _contactability(lead: dict) -> str:
    tem_telefone = bool(lead.get("telefone"))
    tem_email = bool(lead.get("email"))
    tem_rede = bool(lead.get("instagram")) or bool(lead.get("facebook"))
    sinais = sum([tem_telefone, tem_email, tem_rede])
    if tem_telefone and sinais >= 2:
        return "alta"
    if tem_telefone or tem_email:
        return "media"
    return "baixa"


def _evidence_onda1(lead: dict) -> list[str]:
    """Só fatos rastreáveis ao lead (mesma régua do skill antigo) -- nunca interpretação."""
    evidence = []
    if lead.get("nota_google") is not None:
        reviews = lead.get("review_count")
        evidence.append(f"{lead['nota_google']}★" + (f" ({reviews} avaliações)" if reviews else " (nº de avaliações desconhecido)"))
    if lead.get("instagram"):
        evidence.append("Instagram ativo")
    if lead.get("facebook"):
        evidence.append("Facebook ativo")
    if lead.get("cidade"):
        evidence.append(f"cidade: {lead['cidade']}")
    evidence.append("nenhum site vinculado à ficha do Google Maps")
    return evidence


def _risks_onda1(lead: dict) -> list[str]:
    risks = []
    if lead.get("nota_google") is None:
        risks.append("sem nota/avaliação disponível — reputação desconhecida")
    elif (lead.get("review_count") or 0) < 15:
        risks.append("poucos dados disponíveis, mensagem terá que ser genérica")
    if not lead.get("cidade"):
        risks.append("cidade não confirmada")
    if not lead.get("instagram") and not lead.get("facebook"):
        risks.append("nenhuma rede social identificada — menor sinal de atividade digital")
    return risks


def _reason_to_contact_onda1(lead: dict) -> str:
    """Curto e objetivo, no mesmo espírito do que o skill antigo pedia — mas montado, não
    'escrito': concatena os fatos reais disponíveis, nunca inventa."""
    partes = []
    if lead.get("nota_google") is not None:
        reviews = lead.get("review_count")
        partes.append(f"{lead['nota_google']}★" + (f" com {reviews} avaliações" if reviews else ""))
    partes.append("sem site")
    return f"{', '.join(partes)} — vale tentar."


def qualificar_onda1(lead: dict, icp: dict, limiares: dict | None = None) -> dict:
    """Substitui a antiga Qualification LLM. 100% Python, $0, determinístico -- mesmo shape de
    saída que o schema antigo (QUALIFICATION_SCHEMA) tinha, pra não quebrar o resto do funil
    (ranking, relatório).

    Reprova (qualified=False) só quando não há NENHUM sinal: nota E review_count ausentes E
    nenhuma rede social -- mesma regra do skill antigo ("dados quase todos ausentes ... nenhuma
    evidência de que é um negócio ativo"). O corte pesado de verdade continua sendo o ranking
    (lead_qualification.ranquear + separar_top_n), não esta função."""
    limiares = limiares or LIMIARES_QUALIFICACAO_ONDA1

    score, razoes = commercial_fit_score(lead, icp)

    sem_reputacao = lead.get("nota_google") is None and lead.get("review_count") is None
    sem_redes = not lead.get("instagram") and not lead.get("facebook")
    qualified = not (sem_reputacao and sem_redes)

    prioridade = _rotulo_prioridade_por_score(score, limiares)

    return {
        "qualified": qualified,
        "score": score,
        # UMA dimensão só. Antes saíam três (priority/website_opportunity/commercial_fit),
        # mas as três vinham do MESMO score com os MESMOS cortes -- davam o mesmo valor em
        # 27 de 27 leads, só com vocabulários diferentes ("media"/"media"/"medio"), e na
        # planilha pareciam três medidas independentes. Na Onda 2 elas são de fato
        # independentes (fit vem do ICP, oportunidade vem da análise de HTML real, priority
        # é a combinação) e continuam separadas lá -- aqui não havia o que separar.
        "priority": prioridade,
        "contactability": _contactability(lead),
        "reasons": razoes,
        "evidence": _evidence_onda1(lead),
        "risks": _risks_onda1(lead),
        "reason_to_contact": _reason_to_contact_onda1(lead) if qualified else "",
    }

