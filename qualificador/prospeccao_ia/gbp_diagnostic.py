"""Diagnóstico determinístico de completude da ficha do Google Business Profile (GBP).
100% Python, $0, ZERO LLM (não importa anthropic/claude em lugar nenhum, de propósito).
Mesmo padrão de wave2_scoring.website_opportunity_score: soma ponderada de sinais binários,
pesos em config. Nunca decide corte -- só descreve lacunas pro Sistema 2 julgar.

Roda para TODOS os leads (com e sem site), antes da bifurcação por website_status. Pro lead
SEM site é o sinal de oportunidade mais relevante -- a ficha do Google é a presença digital
inteira do negócio.

Estado de verificação por campo (restrição do handoff: nunca "valor nu"):
  CONFIRMADO_PRESENTE -- Detail Scraped confirma o deep-scrape e o campo tinha valor
  CONFIRMADO_AUSENTE  -- deep-scrape rodou e o campo veio vazio  => lacuna real
  NAO_VERIFICADO      -- deep-scrape não rodou pra este lead, OU o health-check rebaixou o
                         campo no lote inteiro (seletor provavelmente quebrado no extractor)

O gate é a coluna 'Detail Scraped'. Foi ela que desambiguou o bug do 'Claimed' (vazio
significava duas coisas opostas). O mesmo problema atinge qualquer campo sem esse 3º estado.
"""

CONFIRMADO_PRESENTE = "CONFIRMADO_PRESENTE"
CONFIRMADO_AUSENTE = "CONFIRMADO_AUSENTE"
NAO_VERIFICADO = "NAO_VERIFICADO"

# Pesos: somam 100. score_completude = soma dos pesos dos sinais CONFIRMADO_AUSENTE (score
# alto = ficha mais incompleta = mais oportunidade, mesma polaridade do website_opportunity).
# Justificativa de cada peso está no handoff (§9). tem_dono_listado e tem_plus_code são só
# informativos (peso zero): Owner compartilha o seletor possivelmente invertido do bug do
# Claimed; Plus Code é auto-gerado pelo Google, ausência quase sempre = falha de scrape, não
# lacuna do dono. Reincorporar ao score é decisão à parte quando o extractor for corrigido.
CONFIG_DEFAULT = {
    "weights": {
        "no_ficha_reivindicada": 28,
        "no_horario": 24,
        "no_foto_destaque": 22,
        "no_descricao": 16,
        "no_faixa_preco": 10,
    },
    "informational_only": ["tem_dono_listado", "tem_plus_code"],
    "health_check": {
        "sample_floor": 15,     # abaixo disso o health-check nem roda (estatisticamente vazio)
        "hard_zero_min_n": 15,  # 0% de presença sobre >=15 deep-scrapes => seletor quebrado
        "near_zero_rate": 0.02,
        "near_zero_min_n": 50,  # <=2% sobre >=50: quebrado que casa por acaso; exige +amostra
    },
}

# sinal (nome no output) -> (campo cru no lead, chave de peso). Chave de peso None = informativo.
_SINAIS = {
    "ficha_reivindicada": ("gbp_reivindicada", "no_ficha_reivindicada"),
    "tem_horario":        ("gbp_horario",       "no_horario"),
    "tem_foto_destaque":  ("gbp_foto_destaque", "no_foto_destaque"),
    "tem_descricao":      ("gbp_descricao",     "no_descricao"),
    "tem_faixa_preco":    ("gbp_faixa_preco",   "no_faixa_preco"),
    "tem_plus_code":      ("gbp_plus_code",     None),
    "tem_dono_listado":   ("gbp_dono",          None),
}

_LACUNA_TEXTO = {
    "ficha_reivindicada": "ficha do Google não reivindicada pelo dono",
    "tem_horario": "ficha do Google sem horário de funcionamento",
    "tem_foto_destaque": "ficha do Google sem foto de destaque",
    "tem_descricao": "ficha do Google sem descrição do negócio",
    "tem_faixa_preco": "ficha do Google sem faixa de preço",
}

# O CSV é raspado com locale pt-BR (ver agent_coletor), então valores yes/no podem chegar em
# português. Lista generosa -- ajustar quando os valores REAIS do 'Detail Scraped'/'Claimed'
# do extractor corrigido forem conhecidos.
_VERDADEIROS = {"yes", "true", "1", "y", "sim", "si", "sí", "verdadeiro", "verdadero", "claimed", "reivindicada"}
_FALSOS = {"no", "false", "0", "n", "nao", "não", "falso", "unclaimed", "sin reclamar",
           "no reclamada", "nao reivindicada", "não reivindicada"}


def _merge_config(config):
    base = CONFIG_DEFAULT
    if not config:
        return {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in base.items()}
    return {
        "weights": {**base["weights"], **(config.get("weights") or {})},
        "informational_only": config.get("informational_only") or base["informational_only"],
        "health_check": {**base["health_check"], **(config.get("health_check") or {})},
    }


def _tem_valor(cru):
    return cru is not None and str(cru).strip() != ""


def _presenca_padrao(cru):
    return _tem_valor(cru)


def _presenca_reivindicada(cru):
    """'Claimed' é yes/no, não "tem valor". Presente = reivindicada. Valor não-vazio e não
    explicitamente negativo conta como reivindicada (conservador: não marca ficha gerida como
    lacuna por causa de um rótulo inesperado do extractor)."""
    if not _tem_valor(cru):
        return False
    return str(cru).strip().lower() not in _FALSOS


_PRESENCA = {"ficha_reivindicada": _presenca_reivindicada}


def detail_scraped(lead):
    """True só quando o extractor confirma que o deep-scrape rodou pra este lead. Coluna
    ausente (CSV antigo) ou valor não-reconhecido => False (conservador: 'não sabemos')."""
    cru = lead.get("gbp_detalhe_scraped")
    if not _tem_valor(cru):
        return False
    return str(cru).strip().lower() in _VERDADEIROS


def avaliar_saude_do_lote(leads, config=None):
    """Passada 1 (por CAMPO, não por lead). Sobre os leads com Detail Scraped=YES no lote,
    calcula a taxa de presença de cada campo. Campo com taxa suspeita (health_check) é
    rebaixado a NAO_VERIFICADO no LOTE INTEIRO -- não é ausência, é seletor quebrado, e não
    pode virar "lacuna". Determinístico e self-healing: extractor corrigido + CSV novo => a
    taxa sobe do limiar e o campo volta ao score sozinho.

    Devolve (campos_rebaixados: set[str], avisos: list[dict])."""
    cfg = _merge_config(config)
    hc = cfg["health_check"]

    verificaveis = [l for l in leads if detail_scraped(l)]
    n = len(verificaveis)
    rebaixados = set()
    avisos = []

    if n < hc["sample_floor"]:
        if leads:
            avisos.append({"aviso": f"amostra insuficiente para health-check (N={n} < {hc['sample_floor']})", "n": n})
        return rebaixados, avisos

    for sinal, (campo, _peso) in _SINAIS.items():
        presenca_fn = _PRESENCA.get(sinal, _presenca_padrao)
        presentes = sum(1 for l in verificaveis if presenca_fn(l.get(campo)))
        taxa = presentes / n
        disparou = (
            (presentes == 0 and n >= hc["hard_zero_min_n"])
            or (taxa <= hc["near_zero_rate"] and n >= hc["near_zero_min_n"])
        )
        if disparou:
            rebaixados.add(sinal)
            avisos.append({
                "campo": sinal,
                "taxa_presenca": round(taxa, 4),
                "n": n,
                "diagnostico": "vazio apesar de deep-scrape — provável seletor quebrado no extractor",
            })
    return rebaixados, avisos


def diagnosticar(lead, campos_rebaixados=frozenset(), config=None):
    """Passada 2. Bloco gbp_diagnostico de UM lead.

    score_completude é None quando Detail Scraped=NÃO (nada é verificável -- não dá pra afirmar
    "completa" nem "incompleta"). Quando verificável, é a soma dos pesos dos sinais pontuados
    CONFIRMADO_AUSENTE; o teto pode ser < 100 se algum campo foi rebaixado pelo health-check."""
    cfg = _merge_config(config)
    pesos = cfg["weights"]
    verificado = detail_scraped(lead)

    sinais = {}
    score = 0
    lacunas_pesadas = []

    for sinal, (campo, peso_key) in _SINAIS.items():
        presenca_fn = _PRESENCA.get(sinal, _presenca_padrao)
        if sinal in campos_rebaixados or not verificado:
            estado = NAO_VERIFICADO
        elif presenca_fn(lead.get(campo)):
            estado = CONFIRMADO_PRESENTE
        else:
            estado = CONFIRMADO_AUSENTE
        sinais[sinal] = {"estado": estado}

        if peso_key and estado == CONFIRMADO_AUSENTE:
            w = pesos.get(peso_key, 0)
            score += w
            lacunas_pesadas.append((w, sinal))

    lacunas = [_LACUNA_TEXTO[s] for _w, s in sorted(lacunas_pesadas, key=lambda x: x[0], reverse=True)]

    return {
        "score_completude": score if verificado else None,
        "detail_scraped": verificado,
        "sinais": sinais,
        "lacunas": lacunas,
    }
