"""afirmacao.py — classifica cada frase de uma mensagem em FATO,
IMPLICACAO_PLAUSIVEL ou RESULTADO_NAO_SUSTENTADO (decisão do diretor,
27/09/2026, mudança 2: o COMERCIAL pode transformar um fato numa
consequência plausível, desde que não a apresente como resultado
observado). Determinístico, sem LLM; listas em
`config/validacao_mensagem.json` (chave `afirmacao`), nunca no código.

Regra (por frase):
- tem marcador de resultado (radical: "pierd", "provoc", "abandon", ...) E
  nenhum modal ("puede", "podría", "quizá", ...) -> RESULTADO_NAO_SUSTENTADO;
- tem marcador de resultado atenuado por modal, OU tem marcador de
  implicação ("para alguien que", "si alguien", "fricción", ...) ->
  IMPLICACAO_PLAUSIVEL;
- senão -> FATO.

A palavra sozinha NÃO basta para rejeitar (ajuste do diretor à decisão 5):
"puede hacer que alguien abandone la web" é implicação, "hace que los
pacientes abandonen la web" é resultado afirmado. Só o modal neutraliza um
marcador de resultado -- "si alguien"/"cuando alguien" não, porque "cuando
alguien entra, abandona" continua sendo afirmação. Limite conhecido e
aceito: é conservador -- "a causa de la espera", sem modal, também é
barrada (o radical "caus" não distingue o substantivo do verbo).

"se puede"/"no se puede" (impessoal: "el teléfono no se puede pulsar") é
capacidade observada, não hipótese -- `falsos_modais` da config são
retirados da frase antes de procurar modal, para não transformar um fato
em implicação.
"""

from __future__ import annotations

import re
import unicodedata

FATO = "FATO"
IMPLICACAO_PLAUSIVEL = "IMPLICACAO_PLAUSIVEL"
RESULTADO_NAO_SUSTENTADO = "RESULTADO_NAO_SUSTENTADO"

CHAVES_CONFIG = ("marcadores_resultado", "modais", "marcadores_implicacao")


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.lower().split())


def _tem_radical(texto_normalizado: str, radicais) -> bool:
    """Radical casa no INÍCIO de palavra (`\\bpierd` casa "pierde",
    "pierden"; não casa "despierda")."""
    return any(re.search(rf"\b{re.escape(_normalizar(r))}", texto_normalizado) for r in radicais)


def _tem_expressao(texto_normalizado: str, expressoes) -> bool:
    return any(re.search(rf"\b{re.escape(_normalizar(e))}\b", texto_normalizado) for e in expressoes)


def frases(texto: str) -> list:
    """Quebra em frases por ".", "?" ou "!" seguidos de espaço."""
    return [f for f in re.split(r"(?<=[.?!])\s+", texto.strip()) if f]


def classificar_frase(frase: str, config_afirmacao: dict) -> str:
    n = _normalizar(frase)
    for falso in config_afirmacao.get("falsos_modais", []):
        n = re.sub(rf"\b{re.escape(_normalizar(falso))}\b", " ", n)
    tem_resultado = _tem_radical(n, config_afirmacao["marcadores_resultado"])
    tem_modal = _tem_expressao(n, config_afirmacao["modais"])
    if tem_resultado and not tem_modal:
        return RESULTADO_NAO_SUSTENTADO
    if tem_resultado or tem_modal or _tem_expressao(n, config_afirmacao["marcadores_implicacao"]):
        return IMPLICACAO_PLAUSIVEL
    return FATO


def classificar_texto(texto: str, config_afirmacao: dict) -> str:
    """Classe de um BLOCO inteiro (várias frases): RESULTADO se qualquer
    frase for resultado; IMPLICACAO se alguma for implicação; senão FATO."""
    classes = [classificar_frase(f, config_afirmacao) for f in frases(texto)]
    if RESULTADO_NAO_SUSTENTADO in classes:
        return RESULTADO_NAO_SUSTENTADO
    if IMPLICACAO_PLAUSIVEL in classes:
        return IMPLICACAO_PLAUSIVEL
    return FATO


def afirmacoes_de_resultado(texto: str, config_afirmacao: dict) -> list:
    """As frases de `texto` classificadas como RESULTADO_NAO_SUSTENTADO."""
    return [f for f in frases(texto) if classificar_frase(f, config_afirmacao) == RESULTADO_NAO_SUSTENTADO]
