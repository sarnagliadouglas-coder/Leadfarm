"""angulo_mensagem.py — MVP de primeira mensagem por MODELO FIXO, com o
ângulo escolhido por regra determinística (mudança de rumo decidida pelo
diretor em 24/09/2026, interna ao COMERCIAL, sem mudar o contrato de
entrada). Substitui, no fluxo da planilha de envio, a chamada de LLM da
Etapa E2 (`pipeline_estrategia_mensagem.py`) e os templates antigos da pista
Direta (`templates_direta.py`) — os dois continuam existindo no código e nos
testes, só saem do fluxo (decisão do diretor).

Nenhuma chamada de LLM aqui: os textos são fixos
(`config/mensagens_angulo.json`), só os placeholders são preenchidos por
programa. Toda mensagem passa pelo MESMO `validador_mensagem.validar_mensagem`
das Etapas anteriores — reusado, não reimplementado.

Ângulo por lead, nesta ordem (nata + candidatos_triagem):
1. `contato` — `analise_tecnica_site.telefone_na_pagina` confirmado como
   `"texto"` (não é link clicável).
2. `poucas_avaliacoes` (renomeado de `reputacao` na sexta rodada de decisões
   do diretor, 24/09/2026) — nota e avaliações confirmadas, nota >=
   `nota_minima` (4,0 — NUNCA abaixo disso, nem por engano), avaliações entre
   `avaliacoes_minimo` e `avaliacoes_maximo` (1 a 30), e existe pelo menos um
   lead do MESMO nicho no lote inteiro (nata + candidatos_triagem +
   descartados — na prática só os dois primeiros contribuem: `descartado`
   não tem bloco `reputacao` no contrato) com avaliações >=
   `multiplicador_concorrente_minimo` (10x) vezes as avaliações deste lead.
   Duas faixas, dois textos (config/mensagens_angulo.json): 5 a 30
   avaliações cita a nota; 1 a 4 não cita (só "todavía tiene solo N
   reseña(s)").
3. `lentidao` — `psi.lcp_ms` confirmado >= `lcp_minimo_ms`. O número de
   segundos só entra na mensagem quando o PSI tem pelo menos
   `rodadas_minimas_para_citar_numero` rodadas medidas (o contrato só guarda
   o `lcp_ms` mais recente, não um histórico por rodada — a checagem usa
   `rodadas` + o `lcp_ms` disponível, não uma verificação rodada a rodada;
   ver limitação no RETORNO da tarefa); sem isso, o mesmo ângulo usa o texto
   sem número.
4. `sem_angulo` — nenhuma das anteriores. Sem mensagem.

Pista Direta: `sem_site` (classe_site == "sem_site") ou `portal` (classe_site
== "portal" — qualquer portal, não só Doctoralia; `{portal}` resolvido pelo
domínio via `nomes_portal` da config, com o domínio cru como default) — os
únicos dois com modelo neste MVP; qualquer outra classe sai como
`sem_angulo`.

Um ângulo que exige um fato ausente (ex.: `poucas_avaliacoes` sem nota/
avaliações confirmadas) nunca é escolhido — "não inventa fato" vale aqui como
em qualquer outra parte do COMERCIAL; a regra cai para a próxima da lista.

Estrutura da mensagem (decisão do diretor, 27/09/2026 — as 4 mudanças
conceituais; abertura A/B aposentada em 29/09/2026, D12 Fase 5.1): SAUDAÇÃO +
APRESENTAÇÃO + FATO + CONSEQUÊNCIA PLAUSÍVEL + CTA. Cada modelo de
`config/mensagens_angulo.json` guarda os três blocos separados (`fato`,
`consequencia` — pode ser `null` —, `cta`), e a carga confere a estrutura com
`afirmacao.py` (fato e CTA sem afirmação de resultado; consequência
obrigatoriamente IMPLICACAO_PLAUSIVEL). A consequência pode ser retirada sem
invalidar o fato (`compor_mensagem(..., incluir_consequencia=False)`). A
apresentação é única (`carregar_apresentacao`) — não há mais alternância de
variante nem distribuidor: a antiga abertura A/B testava sequência de
apresentação, não o objetivo comercial da mensagem, e as duas já tinham o
MESMO texto desde a Fase 5 (sem especialização de setor nem menção a Google
Business Profile).

Novos modelos e ângulos (decisão do diretor, 01/10/2026): `lentidao` e
`sem_site` trocam de texto; entram `lentidao_moderada` (LCP de 5.000 a 9.999
ms) e `defeito_visivel` (texto de modelo esquecido no site, desligado até o
diretor aprovar a lista de padrões -- `regras["defeito_visivel"]`). Esses
modelos trazem a própria `apresentacao`, usam `{nombre}` (nome curto do
negócio) e declaram em `excecoes_validacao` quais checagens do validador
dispensam -- só eles. Quando o nome não limpa com segurança, ou o setor não é
saúde num modelo que fala de "paciente" (`exige_setor_saude`), o lead não
recebe mensagem pronta: `LinhaPedeRevisaoError` e o operador revisa.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

try:
    import validador_mensagem
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import validador_mensagem

import afirmacao
import campanha
from nome_comercial import nome_comercial_limpo

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CAMINHO_REGRAS_PADRAO = _CONFIG_DIR / "angulo_regras.json"
CAMINHO_MENSAGENS_PADRAO = _CONFIG_DIR / "mensagens_angulo.json"
CAMINHO_ABERTURAS_PADRAO = _CONFIG_DIR / "remetente_apresentacao.json"

_CHAVES_REGRAS_OBRIGATORIAS = ("poucas_avaliacoes", "lentidao")
MODELOS = (
    "contato",
    "poucas_avaliacoes_5_30", "poucas_avaliacoes_5_30_singular",
    "poucas_avaliacoes_1_4", "poucas_avaliacoes_1_4_singular",
    "lentidao", "lentidao_sem_numero", "lentidao_moderada", "defeito_visivel",
    "sem_site", "sem_site_sem_reputacao",
    "portal", "portal_sem_reputacao",
    "rede_social", "rede_social_sem_reputacao",
    "construtor", "construtor_sem_reputacao",
)

_CHAVES_MENSAGENS_OBRIGATORIAS = (
    "saudacao",
    "contato",
    "poucas_avaliacoes_5_30", "poucas_avaliacoes_5_30_singular",
    "poucas_avaliacoes_1_4", "poucas_avaliacoes_1_4_singular",
    "lentidao", "lentidao_sem_numero", "lentidao_moderada", "defeito_visivel",
    "sem_site", "sem_site_sem_reputacao",
    "portal", "portal_sem_reputacao", "nomes_portal",
    "rede_social", "rede_social_sem_reputacao", "nomes_rede",
    "construtor", "construtor_sem_reputacao", "nomes_construtor",
)

ANGULOS_NATA = ("contato", "poucas_avaliacoes", "defeito_visivel", "lentidao", "lentidao_moderada")
SEM_ANGULO = "sem_angulo"

# --- tipo de CTA por ângulo (D12 Fase 5, decisão do diretor, 29/09/2026) ----
#
# Não é um campo novo no contrato nem na planilha -- é só uma leitura
# derivada do ângulo já registrado em "Ângulo"/`angulo` (registro_
# abordagens.py). "revision" = oferece a Revisión breve (D12 Fase 4);
# "diagnostico" e "confirmacion" são os mesmos tipos de CTA definidos na
# Fase 3. `construtor` fica "confirmacion" -- NÃO recebe Revisión breve
# neste rollout (sem captura automática, classe_site != "proprio").
CTA_TIPO_POR_ANGULO = {
    "contato": "revision",
    "lentidao": "revision",
    "lentidao_moderada": "revision",
    "defeito_visivel": "revision",
    "poucas_avaliacoes": "diagnostico",
    "sem_site": "diagnostico",
    "portal": "diagnostico",
    "rede_social": "diagnostico",
    "construtor": "confirmacion",
}


class ConfigAnguloInvalidaError(Exception):
    """`config/angulo_regras.json` ausente, ilegível ou incompleto."""


class ConfigMensagensAnguloInvalidaError(Exception):
    """`config/mensagens_angulo.json` ausente, ilegível ou incompleto."""


class LinhaPedeRevisaoError(Exception):
    """O lead tem ângulo, mas a mensagem não sai pronta para enviar: o
    operador revisa antes (nome do negócio sem corte seguro; setor fora da
    saúde num modelo que fala de "paciente"). A mensagem fica vazia -- nunca
    um texto duvidoso na planilha. `str(e)` é o motivo, em português, para a
    coluna `Aviso`."""


class ConfigApresentacaoInvalidaError(Exception):
    """`config/remetente_apresentacao.json` sem `apresentacao_atual`
    utilizável."""


def carregar_regras_angulo(caminho: Path = CAMINHO_REGRAS_PADRAO) -> dict:
    caminho = Path(caminho)
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as e:
        raise ConfigAnguloInvalidaError(f"Config de regras de ângulo não encontrada em {caminho}: {e}") from e
    try:
        config = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ConfigAnguloInvalidaError(f"Config de regras de ângulo em {caminho} não é JSON válido: {e}") from e
    faltando = [c for c in _CHAVES_REGRAS_OBRIGATORIAS if c not in config]
    if faltando:
        raise ConfigAnguloInvalidaError(f"Config de regras de ângulo em {caminho} sem as chaves: {faltando}")
    return config


def carregar_mensagens_angulo(caminho: Path = CAMINHO_MENSAGENS_PADRAO, config_afirmacao: Optional[dict] = None) -> dict:
    """Carrega os modelos e confere a estrutura fato -> consequência -> CTA
    (`problemas_de_estrutura`) -- modelo fora da estrutura derruba a carga,
    nunca gera mensagem. `config_afirmacao` omitido usa a chave `afirmacao`
    de `config/validacao_mensagem.json`."""
    caminho = Path(caminho)
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as e:
        raise ConfigMensagensAnguloInvalidaError(f"Config de mensagens de ângulo não encontrada em {caminho}: {e}") from e
    try:
        config = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ConfigMensagensAnguloInvalidaError(f"Config de mensagens de ângulo em {caminho} não é JSON válido: {e}") from e
    faltando = [c for c in _CHAVES_MENSAGENS_OBRIGATORIAS if c not in config]
    if faltando:
        raise ConfigMensagensAnguloInvalidaError(f"Config de mensagens de ângulo em {caminho} sem as chaves: {faltando}")
    if config_afirmacao is None:
        config_afirmacao = validador_mensagem.carregar_config().get("afirmacao")
    problemas = problemas_de_estrutura(config, config_afirmacao)
    if problemas:
        raise ConfigMensagensAnguloInvalidaError(
            f"Config de mensagens de ângulo em {caminho} fora da estrutura fato -> consequência -> CTA: {problemas}"
        )
    return config


def problemas_de_estrutura(mensagens: dict, config_afirmacao: Optional[dict]) -> list:
    """Confere cada modelo de `MODELOS` (decisão do diretor, 27/09/2026):
    `fato` e `cta` strings não vazias, `cta` termina em "?", `consequencia`
    string ou `null` (um modelo pode dispensar, em
    `excecoes_validacao`, o "?" do CTA -- `sem_pergunta_final` -- e os
    marcadores de implicação da consequência -- `consequencia_sem_marcador`).
    Com `config_afirmacao`: `fato` e `cta` nunca afirmam
    resultado; `consequencia`, quando existe, é IMPLICACAO_PLAUSIVEL (nem
    fato cru, nem resultado afirmado). Devolve a lista de problemas (vazia =
    ok) -- nunca aceita em silêncio."""
    problemas = []
    for chave in MODELOS:
        modelo = mensagens.get(chave)
        if not isinstance(modelo, dict):
            problemas.append(f"{chave}: não é um objeto com fato/consequencia/cta")
            continue
        for bloco in ("fato", "cta"):
            if not isinstance(modelo.get(bloco), str) or not modelo[bloco].strip():
                problemas.append(f"{chave}.{bloco}: ausente ou vazio")
        consequencia = modelo.get("consequencia")
        if consequencia is not None and (not isinstance(consequencia, str) or not consequencia.strip()):
            problemas.append(f"{chave}.consequencia: deve ser texto não vazio ou null")
            consequencia = None
        cta = modelo.get("cta")
        excecoes = modelo.get("excecoes_validacao") or {}
        if isinstance(cta, str) and not excecoes.get("sem_pergunta_final") and not cta.strip().endswith("?"):
            problemas.append(f"{chave}.cta: não termina em '?'")
        if not config_afirmacao:
            continue
        for bloco in ("fato", "cta"):
            texto = modelo.get(bloco)
            if isinstance(texto, str) and afirmacao.afirmacoes_de_resultado(texto, config_afirmacao):
                problemas.append(f"{chave}.{bloco}: afirma resultado/causa não observado")
        if consequencia is not None:
            classe = afirmacao.classificar_texto(consequencia, config_afirmacao)
            if excecoes.get("consequencia_sem_marcador"):
                # texto aprovado sem os marcadores de implicação: continua
                # proibido afirmar resultado/causa (RESULTADO_NAO_SUSTENTADO)
                if classe == afirmacao.RESULTADO_NAO_SUSTENTADO:
                    problemas.append(f"{chave}.consequencia: classificada como {classe}")
            elif classe != afirmacao.IMPLICACAO_PLAUSIVEL:
                problemas.append(f"{chave}.consequencia: classificada como {classe}, não como IMPLICACAO_PLAUSIVEL")
    return problemas


def carregar_apresentacao(caminho: Path = CAMINHO_ABERTURAS_PADRAO) -> str:
    """Texto único da apresentação usada em toda mensagem do D12 (D12 Fase
    5.1, decisão do diretor, 29/09/2026 -- aposentadoria da abertura A/B: as
    duas variantes já tinham exatamente o mesmo texto desde a Fase 5, que
    retirou a especialização de setor e a menção a Google Business Profile;
    esta fase remove a maquinaria de alternância em si, que não representava
    mais nenhum experimento). Substitui `carregar_aberturas`/
    `DistribuidorVariante`, removidos nesta rodada. `apresentacao` (outra
    chave do mesmo arquivo) continua sendo só o texto do controle histórico,
    lido apenas por `templates_direta.py` (fora do fluxo) -- não usada
    aqui."""
    caminho = Path(caminho)
    try:
        config = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigApresentacaoInvalidaError(f"Config de apresentação ilegível em {caminho}: {e}") from e
    texto = config.get("apresentacao_atual")
    if not isinstance(texto, str) or not texto.strip():
        raise ConfigApresentacaoInvalidaError(
            f"Config de apresentação em {caminho} sem 'apresentacao_atual' utilizável"
        )
    return texto


def carregar_cidade_campanha() -> str:
    """Cidade da campanha ativa (`EQC/config/campanha_ativa.json`, lida por
    `campanha.py` -- a mesma do QUALIFICADOR). Substitui
    `config/cidade_da_busca.json`, aposentado na Etapa 2 (diretor, 04/10/2026).
    Campanha ausente ou inválida levanta `campanha.CampanhaInvalidaError` --
    falha alta, nunca uma cidade vazia em silêncio."""
    return campanha.cidade_da_campanha()


# --- preenchimento de placeholders ------------------------------------------


def _formatar_apresentacao(apresentacao: Optional[str]) -> str:
    """Abertura pronta para colar depois da saudação -- espaço na frente,
    ponto final se faltar (":" também encerra: abertura B). Vazio/`None`
    devolve string vazia (mensagem sai sem apresentação nenhuma)."""
    texto = (apresentacao or "").strip()
    if not texto:
        return ""
    if not texto.endswith((".", "!", "?", ":")):
        texto += "."
    return f" {texto}"


class MensagemComposta(str):
    """A mensagem pronta (é uma `str` comum) levando junto, em `.excecoes`, as
    `excecoes_validacao` do modelo que a gerou -- `validar_mensagem_angulo`
    as lê daqui, sem que quem chama precise saber qual modelo foi usado."""

    excecoes: dict = {}


def compor_mensagem(
    modelo: dict, saudacao: str, apresentacao: Optional[str], *, incluir_consequencia: bool = True, **valores,
) -> str:
    """SAUDAÇÃO + ABERTURA + FATO + CONSEQUÊNCIA + CTA. O fato começa em
    minúscula no modelo: segue assim depois de abertura terminada em ":",
    sobe a primeira letra nos demais casos. `incluir_consequencia=False`
    tira só a consequência -- fato e CTA ficam intactos (critério de
    aceitação da mudança 2). Um modelo com chave `apresentacao` usa a dele no
    lugar da global (01/10/2026: "Soy Douglas, hago webs aquí en Alicante.")."""
    abertura = _formatar_apresentacao(modelo.get("apresentacao", apresentacao))
    partes = [modelo["fato"].format(**valores)]
    if incluir_consequencia and modelo.get("consequencia"):
        partes.append(modelo["consequencia"].format(**valores))
    partes.append(modelo["cta"].format(**valores))
    corpo = " ".join(partes)
    if not abertura.endswith(":"):
        corpo = corpo[:1].upper() + corpo[1:]
    mensagem = MensagemComposta(f"{saudacao}{abertura} {corpo}")
    mensagem.excecoes = dict(modelo.get("excecoes_validacao") or {})
    return mensagem


def _formatar_nota(nota) -> str:
    return f"{float(nota):.1f}".replace(".", ",")


def _arredondar_para_baixo_estrito(valor: int) -> int:
    """Arredonda para a dezena (< 100) ou centena (>= 100) mais próxima por
    baixo, garantindo ESTRITAMENTE menor que `valor` -- para que "más de N"
    citado na mensagem seja sempre literalmente verdade, mesmo quando
    `valor` já é um múltiplo exato do passo (ex.: 40 -> 30, nunca 40)."""
    passo = 100 if valor >= 100 else 10
    piso = (valor // passo) * passo
    if piso >= valor:
        piso -= passo
    return max(piso, 0)


def _hostname(site_url: Optional[str]) -> Optional[str]:
    if not site_url:
        return None
    bruto = site_url if "://" in site_url else f"//{site_url}"
    host = urlsplit(bruto).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _nome_por_dominio(site_url: Optional[str], mapa_nomes: dict) -> str:
    """Nome legível a partir do domínio do site (`mapa_nomes` da config --
    `nomes_portal` para `portal`, `nomes_rede` para `rede_social`; ex.:
    `doctoralia.es` -> `Doctoralia`, `instagram.com` -> `Instagram`).
    Domínio desconhecido ou ausente: o próprio domínio, sem "www." (nunca
    inventa um nome bonito)."""
    host = _hostname(site_url)
    if not host:
        return ""
    if host in mapa_nomes:
        return mapa_nomes[host]
    for dominio, nome in mapa_nomes.items():
        if host.endswith("." + dominio):
            return nome
    return host


# --- ângulo "contato" --------------------------------------------------------


def _telefone_na_pagina_e_texto(lead) -> bool:
    campo = lead.get("analise_tecnica_site", {}).get("telefone_na_pagina")
    return bool(campo) and hasattr(campo, "presente") and campo.presente() and campo.valor_confirmado == "texto"


# --- ângulo "poucas_avaliacoes" ----------------------------------------------


def _nota_e_avaliacoes_confirmadas(lead) -> Optional[tuple]:
    reputacao = lead.get("reputacao") or {}
    nota = reputacao.get("nota_google")
    avaliacoes = reputacao.get("review_count")
    if not (nota and hasattr(nota, "presente") and nota.presente()):
        return None
    if not (avaliacoes and hasattr(avaliacoes, "presente") and avaliacoes.presente()):
        return None
    return nota.valor_confirmado, avaliacoes.valor_confirmado


def _nicho_e_avaliacoes_concorrente(lead_ou_descartado) -> tuple:
    """`(nicho, avaliacoes)` -- `avaliacoes` é `None` quando o lead não tem
    reputação confirmada (inclusive `descartado`, que nem tem o bloco no
    contrato)."""
    identidade = lead_ou_descartado.get("identidade") or {}
    nicho = identidade.get("nicho")
    reputacao = lead_ou_descartado.get("reputacao")
    avaliacoes = None
    if reputacao:
        review_count = reputacao.get("review_count")
        if review_count is not None and hasattr(review_count, "presente") and review_count.presente():
            avaliacoes = review_count.valor_confirmado
    return nicho, avaliacoes


def _concorrentes_qualificados(lead, leads_do_lote: list, multiplicador: float) -> list:
    """Avaliações de todo lead do MESMO nicho (place_id diferente) no lote
    inteiro (nata + candidatos_triagem + descartados) com
    avaliações >= multiplicador * avaliações deste lead."""
    _, avaliacoes_proprias = _nicho_e_avaliacoes_concorrente(lead)
    nicho_proprio = lead.get("identidade", {}).get("nicho")
    if not nicho_proprio or avaliacoes_proprias is None:
        return []
    place_id_proprio = lead.get("place_id")
    limiar = multiplicador * avaliacoes_proprias
    qualificados = []
    for outro in leads_do_lote:
        if outro.get("place_id") == place_id_proprio:
            continue
        nicho_outro, avaliacoes_outro = _nicho_e_avaliacoes_concorrente(outro)
        if nicho_outro == nicho_proprio and avaliacoes_outro is not None and avaliacoes_outro >= limiar:
            qualificados.append(avaliacoes_outro)
    return qualificados


def _elegivel_para_poucas_avaliacoes(nota, avaliacoes, regras_poucas_avaliacoes: dict) -> bool:
    return (
        nota >= regras_poucas_avaliacoes["nota_minima"]
        and regras_poucas_avaliacoes["avaliacoes_minimo"] <= avaliacoes <= regras_poucas_avaliacoes["avaliacoes_maximo"]
    )


# --- ângulo "lentidao" -------------------------------------------------------


def _lcp_ms_confirmado(lead) -> Optional[int]:
    psi = lead.get("psi")
    if isinstance(psi, dict) and psi.get("estado") == "CONFIRMADO_PRESENTE":
        lcp_ms = psi.get("lcp_ms")
        if isinstance(lcp_ms, (int, float)):
            return int(lcp_ms)
    return None


def _medicao_consistente_para_citar_numero(lead, rodadas_minimas: int) -> bool:
    """`True` só quando o PSI tem pelo menos `rodadas_minimas` rodadas
    medidas. O contrato só guarda o `lcp_ms` mais recente (não um histórico
    por rodada) -- não dá para checar "todas as rodadas >= 10000ms"
    literalmente; esta função usa `rodadas` como proxy de medição
    consistente, combinado com o `lcp_ms` disponível (ver limitação no
    RETORNO da tarefa)."""
    psi = lead.get("psi")
    if not isinstance(psi, dict):
        return False
    rodadas = psi.get("rodadas") or 0
    return isinstance(rodadas, (int, float)) and rodadas >= rodadas_minimas


# --- ângulo "defeito_visivel" (desligado até o diretor aprovar os padrões) ----


def _texto_do_site(lead) -> str:
    campo = (lead.get("analise_tecnica_site") or {}).get("texto_site")
    if isinstance(campo, dict):
        return campo.get("texto") or ""
    valor = getattr(campo, "valor_confirmado", None)
    if isinstance(valor, dict):
        return valor.get("texto") or ""
    return valor if isinstance(valor, str) else ""


def _texto_encontrado_defeito(lead, regras: dict) -> Optional[str]:
    """Primeiro trecho de modelo esquecido achado no e-mail confirmado do
    lead ou no texto do site (quando medido). `regras["defeito_visivel"]` =
    `{"ativo": bool, "padroes": [{"tipo": "email", "regex": "..."}]}`.
    Desligado (`ativo` falso/ausente) ou sem padrões: `None`. Só `tipo ==
    "email"` aciona o ângulo -- o texto aprovado diz "el correo no les llega",
    que só vale para e-mail; outros tipos esperam variação de texto aprovada
    pelo diretor. O trecho vem do dado, nunca é escrito aqui."""
    cfg = regras.get("defeito_visivel") or {}
    if not cfg.get("ativo"):
        return None
    fontes = []
    email = (lead.get("contato") or {}).get("email")
    if email is not None and hasattr(email, "presente") and email.presente() and isinstance(email.valor_confirmado, str):
        fontes.append(email.valor_confirmado)
    texto_site = _texto_do_site(lead)
    if texto_site:
        fontes.append(texto_site)
    for padrao in cfg.get("padroes", []):
        if padrao.get("tipo") != "email":
            continue
        regex = re.compile(padrao["regex"], re.IGNORECASE)
        for fonte in fontes:
            achado = regex.search(fonte)
            if achado:
                return achado.group(0)
    return None


def defeitos_nao_email(lead, regras: dict) -> list:
    """Trechos de modelo esquecido de tipo diferente de e-mail (lorem ipsum,
    nome de empresa de modelo, ...), como `["tipo: 'trecho'"]`. Só detecta: o
    texto aprovado do `defeito_visivel` é para e-mail, então estes viram nota
    no `Aviso` da linha, nunca mensagem (diretor, 01/10/2026). Desligado ->
    lista vazia."""
    cfg = regras.get("defeito_visivel") or {}
    if not cfg.get("ativo"):
        return []
    fontes = []
    email = (lead.get("contato") or {}).get("email")
    if email is not None and hasattr(email, "presente") and email.presente() and isinstance(email.valor_confirmado, str):
        fontes.append(email.valor_confirmado)
    texto_site = _texto_do_site(lead)
    if texto_site:
        fontes.append(texto_site)
    achados = []
    for padrao in cfg.get("padroes", []):
        if padrao.get("tipo") == "email":
            continue
        regex = re.compile(padrao["regex"], re.IGNORECASE)
        for fonte in fontes:
            achado = regex.search(fonte)
            if achado:
                achados.append(f"{padrao['tipo']}: {achado.group(0)!r}")
                break
    return achados


# --- nome curto e setor (revisão do operador) --------------------------------


def _sem_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c))


_CONECTORES_GENERICOS = {"en", "de", "del", "la", "el", "y", "e", "los", "las"}


def _sem_cidade_no_fim(nome: str, cidade: str) -> str:
    """Tira a cidade da campanha ativa do FIM do nome, com ou sem separador ("Alicante",
    "- Alicante", "| Alicante", "en Alicante"), sem diferenciar maiúsculas
    (decisão do diretor, 01/10/2026). Cidade no meio do nome não é tirada."""
    if not cidade:
        return nome
    padrao = rf"(?:\s*[-–—|·,]\s*|\s+en\s+|\s+)?{re.escape(cidade.strip())}\s*$"
    return re.sub(padrao, "", nome, flags=re.IGNORECASE).strip()


def _so_generico(nome: str, nicho: Optional[str], genericas: list) -> bool:
    palavras = set(_CONECTORES_GENERICOS)
    for frase in [*genericas, nicho or ""]:
        palavras.update(_sem_acentos(p).lower() for p in re.findall(r"\w+", frase))
    return all(_sem_acentos(p).lower() in palavras for p in re.findall(r"\w+", nome))


def nome_curto_seguro(nome: Optional[str], regras: dict, nicho: Optional[str] = None) -> str:
    """`{nombre}` da mensagem: o nome do Maps cortado no subtítulo
    (`nome_comercial_limpo`), SE o resultado for seguro -- senão
    `LinhaPedeRevisaoError`. Inseguro: vazio; reticências (nome truncado pelo
    Maps); separador sobrando; mais de `max_palavras`/`max_caracteres`;
    símbolo/emoji; só palavras genéricas (`nome_curto.palavras_genericas`,
    mais o nicho do lead) depois de tirar a cidade do fim; ou a cidade da
    campanha no MEIO do nome. A cidade no fim do nome é removida, não recusada
    (diretor, 01/10/2026). Limites em `regras["nome_curto"]`."""
    cfg = regras.get("nome_curto") or {}
    max_palavras = cfg.get("max_palavras", 6)
    max_caracteres = cfg.get("max_caracteres", 45)
    limpo = (nome_comercial_limpo(nome) or "").strip()
    cidade = carregar_cidade_campanha()  # campanha inválida: falha alta, nunca cidade vazia
    limpo = _sem_cidade_no_fim(limpo, cidade)
    motivos = []
    if not limpo:
        motivos.append("nome vazio")
    elif _so_generico(limpo, nicho, cfg.get("palavras_genericas", [])):
        motivos.append("só palavras genéricas, sem o nome próprio do negócio")
    else:
        if "…" in limpo or "..." in limpo:
            motivos.append("nome truncado pelo Maps")
        if re.search(r"[|·–—/]|\s-\s", limpo):
            motivos.append("separador sobrando no nome")
        if len(limpo.split()) > max_palavras or len(limpo) > max_caracteres:
            motivos.append("nome longo demais (palavras-chave do Maps)")
        if any(unicodedata.category(c) in ("So", "Sk", "Cs", "Co") for c in limpo):
            motivos.append("símbolo/emoji no nome")
        if cidade and re.search(rf"\b{re.escape(_sem_acentos(cidade).lower())}\b", _sem_acentos(limpo).lower()):
            motivos.append(f"cidade da campanha ({cidade}) no nome")
    if motivos:
        raise LinhaPedeRevisaoError(
            f"REVISAR NOME antes de enviar: {nome!r} não limpa com segurança ({'; '.join(motivos)})"
        )
    return limpo


def setor_e_saude(nicho: Optional[str], nome: Optional[str], regras: dict) -> bool:
    """`True` quando alguma palavra de `nicho` ou `nome` começa por um radical
    de `regras["setor_saude"]["radicais"]` (sem acento/maiúscula; ex.:
    "dent" casa "Dentista"/"Dental", não "residencia"). Sem a chave na
    config: levanta `ValueError` -- nunca assume saúde em silêncio. A pista
    Direta (CSV humano) não traz o nicho, então decide só pelo `nome`."""
    radicais = (regras.get("setor_saude") or {}).get("radicais")
    if not radicais:
        raise ValueError("regras sem 'setor_saude.radicais' -- o modelo exige setor de saúde")
    palavras = re.findall(r"\w+", _sem_acentos(f"{nicho or ''} {nome or ''}").lower())
    return any(p.startswith(_sem_acentos(r).lower()) for p in palavras for r in radicais)


def _conferir_setor(modelo: dict, nicho: Optional[str], nome: Optional[str], regras: dict) -> None:
    if modelo.get("exige_setor_saude") and not setor_e_saude(nicho, nome, regras):
        raise LinhaPedeRevisaoError(
            f"REVISAR SETOR antes de enviar: o texto fala de pacientes e o negócio não aparece como saúde "
            f"(nicho={nicho or 'não informado'!r}, nome={nome!r})"
        )


def _usa_nombre(modelo: dict) -> bool:
    return any("{nombre}" in (modelo.get(b) or "") for b in ("fato", "consequencia", "cta"))


# --- escolha do ângulo (nata + candidatos_triagem) --------------------------


def escolher_angulo_nata(lead, leads_do_lote: list, regras: dict) -> str:
    """`leads_do_lote` é a lista completa usada para o cruzamento de
    concorrente do ângulo `poucas_avaliacoes` (nata + candidatos_triagem +
    descartados) -- inclui o próprio `lead`, que é excluído por `place_id`
    dentro de `_concorrentes_qualificados`."""
    # defeito_visivel: prioridade total, antes de todos (diretor, 01/10/2026)
    if _texto_encontrado_defeito(lead, regras) is not None:
        return "defeito_visivel"

    if _telefone_na_pagina_e_texto(lead):
        return "contato"

    regras_poucas_avaliacoes = regras["poucas_avaliacoes"]
    confirmadas = _nota_e_avaliacoes_confirmadas(lead)
    if confirmadas is not None:
        nota, avaliacoes = confirmadas
        if _elegivel_para_poucas_avaliacoes(nota, avaliacoes, regras_poucas_avaliacoes):
            if _concorrentes_qualificados(lead, leads_do_lote, regras_poucas_avaliacoes["multiplicador_concorrente_minimo"]):
                return "poucas_avaliacoes"

    lcp_ms = _lcp_ms_confirmado(lead)
    if lcp_ms is not None and lcp_ms >= regras["lentidao"]["lcp_minimo_ms"]:
        return "lentidao"

    moderada = regras.get("lentidao_moderada")
    if (
        moderada and lcp_ms is not None and lcp_ms >= moderada["lcp_minimo_ms"]
        # o texto aprovado cita os segundos e não tem variante sem número:
        # só sai com medição consistente (mesma regra de `lentidao`)
        and _medicao_consistente_para_citar_numero(lead, regras["lentidao"]["rodadas_minimas_para_citar_numero"])
    ):
        return "lentidao_moderada"

    return SEM_ANGULO


# --- escolha do ângulo (pista Direta) ---------------------------------------


def escolher_angulo_direta(linha_csv: dict) -> str:
    """`linha_csv` é uma linha do CSV humano (`classe_site`). `portal`
    (sexta rodada, 24/09/2026) substitui o `doctoralia` específico -- vale
    para QUALQUER portal (o `{portal}` da mensagem é resolvido pelo domínio,
    não a escolha do ângulo). `rede_social` e `construtor` entraram na
    oitava rodada (25/09/2026, go-live) -- eram as duas classes que ainda
    ficavam `sem_angulo` na Direta. `superficie_google` (página gratuita do
    Google) reusa os modelos de `sem_site` -- mesmo texto, mesma checagem."""
    classe = linha_csv.get("classe_site")
    if classe in ("sem_site", "superficie_google"):
        return "sem_site"
    if classe == "portal":
        return "portal"
    if classe == "rede_social":
        return "rede_social"
    if classe == "construtor":
        return "construtor"
    return SEM_ANGULO


# --- montagem + validação da mensagem ---------------------------------------


def montar_mensagem_nata(
    angulo: str, lead, leads_do_lote: list, *, apresentacao: str, regras: dict, mensagens: dict,
    incluir_consequencia: bool = True,
) -> tuple:
    """Devolve `(mensagem, entrada_derivada)` para os ângulos `contato`,
    `poucas_avaliacoes` e `lentidao`. `apresentacao` é o texto único da
    apresentação (`carregar_apresentacao`); o corpo não depende dela.
    `entrada_derivada` é o dict mínimo com só os números que a mensagem pode
    citar -- usado por `validar_mensagem_angulo` (checagem 7, "número fora
    da entrada", reusada sem reimplementar). Ângulo sem os fatos necessários
    (ex.: `poucas_avaliacoes` chamado sem nota/avaliações confirmadas)
    levanta `ValueError` -- quem chama já garantiu isso ao escolher o ângulo
    com `escolher_angulo_nata`.

    `poucas_avaliacoes` (décima rodada, 27/09/2026): o concorrente do mesmo
    nicho com 10x as avaliações continua sendo a EVIDÊNCIA que escolhe o
    ângulo e decide singular/plural ("otra"/"otras"), mas a mensagem não
    cita mais categoria, cidade nem o número do concorrente -- só o fato do
    próprio lead e a consequência plausível ("puede encontrarse con otras
    que tienen muchas más reseñas")."""
    saudacao = mensagens["saudacao"]
    identidade = lead.get("identidade") or {}

    def compor(chave, **valores):
        modelo = mensagens[chave]
        _conferir_setor(modelo, identidade.get("nicho"), identidade.get("nome"), regras)
        if _usa_nombre(modelo):
            valores["nombre"] = nome_curto_seguro(identidade.get("nome"), regras, identidade.get("nicho"))
        return compor_mensagem(
            modelo, saudacao, apresentacao, incluir_consequencia=incluir_consequencia, **valores,
        )

    if angulo == "defeito_visivel":
        encontrado = _texto_encontrado_defeito(lead, regras)
        if encontrado is None:
            raise ValueError("ângulo 'defeito_visivel' sem texto de modelo encontrado")
        cliente_paciente = "paciente" if setor_e_saude(identidade.get("nicho"), identidade.get("nome"), regras) else "cliente"
        mensagem = compor("defeito_visivel", texto_encontrado=encontrado, cliente_paciente=cliente_paciente)
        return mensagem, {"texto_encontrado": encontrado, "nombre": identidade.get("nome") or ""}

    if angulo == "contato":
        return compor("contato"), {}

    if angulo == "poucas_avaliacoes":
        confirmadas = _nota_e_avaliacoes_confirmadas(lead)
        if confirmadas is None:
            raise ValueError("ângulo 'poucas_avaliacoes' sem nota/avaliações confirmadas")
        nota, avaliacoes = confirmadas
        concorrentes = _concorrentes_qualificados(
            lead, leads_do_lote, regras["poucas_avaliacoes"]["multiplicador_concorrente_minimo"]
        )
        if not concorrentes:
            raise ValueError("ângulo 'poucas_avaliacoes' sem concorrente qualificado no lote")
        nota_fmt = _formatar_nota(nota)
        sufixo = "_singular" if len(concorrentes) == 1 else ""
        if avaliacoes >= 5:
            mensagem = compor(f"poucas_avaliacoes_5_30{sufixo}", nota=nota_fmt, n=avaliacoes)
            return mensagem, {"nota_google": nota_fmt, "avaliacoes_google": avaliacoes}
        reseñas_palavra = "reseña" if avaliacoes == 1 else "reseñas"
        mensagem = compor(f"poucas_avaliacoes_1_4{sufixo}", n=avaliacoes, reseñas_palavra=reseñas_palavra)
        return mensagem, {"nota_google": nota_fmt, "avaliacoes_google": avaliacoes}

    if angulo == "lentidao":
        lcp_ms = _lcp_ms_confirmado(lead)
        if lcp_ms is None:
            raise ValueError("ângulo 'lentidao' sem LCP confirmado")
        rodadas_minimas = regras["lentidao"]["rodadas_minimas_para_citar_numero"]
        if _medicao_consistente_para_citar_numero(lead, rodadas_minimas):
            segundos = round(lcp_ms / 1000)
            mensagem = compor("lentidao", s=segundos, segundos=segundos)
            return mensagem, {"segundos": segundos, "nombre": identidade.get("nome") or ""}
        return compor("lentidao_sem_numero"), {}

    if angulo == "lentidao_moderada":
        lcp_ms = _lcp_ms_confirmado(lead)
        if lcp_ms is None:
            raise ValueError("ângulo 'lentidao_moderada' sem LCP confirmado")
        segundos = round(lcp_ms / 1000)
        mensagem = compor("lentidao_moderada", segundos=segundos)
        return mensagem, {"segundos": segundos, "nombre": identidade.get("nome") or ""}

    raise ValueError(f"ângulo sem modelo de mensagem: {angulo!r}")


def _nota_e_avaliacoes_csv(linha_csv: dict) -> tuple:
    """`(nota, avaliacoes)` a partir das colunas `nota`/`avaliacoes` do CSV
    humano, ou `(None, None)` quando alguma das duas não vem confirmada
    (célula vazia ou não numérica) -- nunca inventa."""
    try:
        nota = float(str(linha_csv.get("nota")).replace(",", "."))
        avaliacoes = int(float(str(linha_csv.get("avaliacoes")).replace(",", ".")))
    except (TypeError, ValueError):
        return None, None
    return nota, avaliacoes


def montar_mensagem_direta(
    angulo: str, linha_csv: dict, *, apresentacao: str, mensagens: dict, incluir_consequencia: bool = True,
    regras: Optional[dict] = None,
) -> tuple:
    """Devolve `(mensagem, entrada_derivada)` para `sem_site`/`portal`/
    `rede_social`/`construtor`. `apresentacao` é o texto único da
    apresentação. Quando nota/avaliações não estão confirmadas no CSV humano (colunas
    `nota`/`avaliacoes`) OU as avaliações são 0, usa a variante "sem
    reputação" (decisão do diretor, 24/09/2026, sétima rodada).
    `{portal}`/`{rede}`/`{constructor}` são o nome legível pelo domínio do
    site (`nomes_portal`/`nomes_rede`/`nomes_construtor` da config --
    domínio desconhecido usa o próprio host, sem "https://" nem "www.").
    `constructor` entra em `entrada_derivada` porque pode conter dígitos que
    a mensagem cita (checagem 7 do validador, "número fora da entrada").

    `construtor` só existe porque o QUALIFICADOR classifica pelo HOST da URL
    (`qualificador/prospeccao_ia/site_classificacao.py`: subdomínio de
    wordpress.com, wixsite.com, ...) -- "sin dominio propio" é fato
    observado no endereço, não inferência a partir da plataforma (decisão do
    diretor, 27/09/2026, item 4)."""
    if angulo not in ("sem_site", "portal", "rede_social", "construtor"):
        raise ValueError(f"ângulo sem modelo de mensagem direta: {angulo!r}")

    saudacao = mensagens["saudacao"]
    nota, avaliacoes = _nota_e_avaliacoes_csv(linha_csv)
    sem_reputacao = nota is None or avaliacoes is None or avaliacoes == 0
    regras = regras or {}
    elogio = regras.get("sem_site")
    if angulo == "sem_site" and elogio and not sem_reputacao:
        # o texto novo diz "se nota que sus pacientes están contentos": só com
        # nota e quantidade de avaliações que sustentem o elogio
        sem_reputacao = nota < elogio["nota_minima"] or avaliacoes < elogio["avaliacoes_minimo"]
    citar_nota = regras.get("citar_nota")
    if angulo in ("portal", "rede_social", "construtor") and citar_nota and not sem_reputacao:
        # nota baixa não é citada no 1º contato (diretor, 03/10/2026)
        sem_reputacao = nota < citar_nota["nota_minima"]
    chave = f"{angulo}_sem_reputacao" if sem_reputacao else angulo

    valores = {}
    entrada_derivada = {}
    if not sem_reputacao:
        nota_fmt = _formatar_nota(nota)
        valores.update(nota=nota_fmt, n=avaliacoes)
        entrada_derivada.update(nota_google=nota_fmt, avaliacoes_google=avaliacoes)
    if angulo == "portal":
        valores["portal"] = _nome_por_dominio(linha_csv.get("site"), mensagens.get("nomes_portal", {}))
    elif angulo == "rede_social":
        valores["rede"] = _nome_por_dominio(linha_csv.get("site"), mensagens.get("nomes_rede", {}))
    elif angulo == "construtor":
        constructor = _nome_por_dominio(linha_csv.get("site"), mensagens.get("nomes_construtor", {}))
        valores["constructor"] = constructor
        entrada_derivada["constructor"] = constructor

    modelo = mensagens[chave]
    _conferir_setor(modelo, linha_csv.get("nicho"), linha_csv.get("nome"), regras)
    if _usa_nombre(modelo):
        valores["nombre"] = entrada_derivada["nombre"] = nome_curto_seguro(
            linha_csv.get("nome"), regras, linha_csv.get("nicho"),
        )
    mensagem = compor_mensagem(
        modelo, saudacao, apresentacao, incluir_consequencia=incluir_consequencia, **valores,
    )
    return mensagem, entrada_derivada


def palavras_genericas_nome(*frases: Optional[str]) -> list:
    """Junta `frases` (nicho do lead, cidade da campanha, ...) numa lista de
    "palavras genéricas" para `validar_mensagem_angulo` -- um trecho do nome
    do lead formado SÓ por essas palavras (mais as conectoras fixas do
    validador) não é tratado como o nome do negócio vazando na mensagem
    (decisão do diretor, 25/09/2026, oitava rodada: "Psicólogo en Alicante"
    -- nicho + cidade da campanha -- é falso positivo quando o modelo de
    `poucas_avaliacoes` legitimamente diz "quien busca psicólogo en
    Alicante"). `None`/vazio é ignorado."""
    return [f for f in frases if f]


def validar_mensagem_angulo(
    mensagem: str, angulo: str, entrada_derivada: dict, *, nome_negocio=None, config_validacao=None,
    palavras_genericas_nome: Optional[list] = None,
):
    """Roda `mensagem` pelo MESMO `validador_mensagem.validar_mensagem` das
    Etapas anteriores -- saudação, sem preço, sem URL, usted, sem nome do
    negócio, termina em "?", limite de palavras, termos proibidos (inclusive
    a consequência genérica de "perder pacientes" e a inferência indevida de
    "todas las reseñas son de 5 estrellas", 24/09/2026) e todo número citado
    precisa existir em `entrada_derivada` (nunca um número inventado).
    `palavras_genericas_nome` (ver `angulo_mensagem.palavras_genericas_nome`)
    evita o falso positivo da checagem de nome contra nicho/cidade."""
    excecoes = getattr(mensagem, "excecoes", None)
    texto_resposta = json.dumps(
        {"estrategia": angulo, "canal_sugerido": "whatsapp", "mensagem_1": mensagem, "fato_usado": angulo},
        ensure_ascii=False,
    )
    return validador_mensagem.validar_mensagem(
        texto_resposta, entrada_derivada, config=config_validacao, nome_negocio=nome_negocio,
        palavras_genericas_nome=palavras_genericas_nome, excecoes=excecoes,
    )
