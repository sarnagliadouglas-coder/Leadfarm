"""nome_comercial.py — nome comercial limpo (decisão do diretor, 24/09/2026):
o Google Maps costuma trazer nome + subtítulo grudados
("Fisioficticia Salud - Fisioterapia en Alicante"). A mensagem cita só
a primeira parte; a planilha continua mostrando o nome completo (coluna
"nome" nunca passa por aqui).

Função única, usada tanto por `templates_direta.montar_mensagem_direta`
(pista Direta) quanto por `entrada_estrategia.construir_entrada` (entrada da
nata) — nunca duas implementações do mesmo corte.
"""

from __future__ import annotations

from typing import Optional

_SEPARADORES = (" - ", " | ", " – ", " · ")
_MINIMO_CARACTERES_APOS_CORTE = 3


def nome_comercial_limpo(nome: Optional[str]) -> Optional[str]:
    """Corta `nome` no primeiro separador (" - ", " | ", " – ", " · ") entre
    os que aparecem, e tira os espaços das pontas. Se o corte deixar menos de
    `_MINIMO_CARACTERES_APOS_CORTE` caracteres, mantém o nome original —
    corte curto demais é sinal de falso positivo (ex.: nome que começa com
    hífen), não de subtítulo."""
    if not nome:
        return nome

    primeiro_indice = None
    for separador in _SEPARADORES:
        indice = nome.find(separador)
        if indice != -1 and (primeiro_indice is None or indice < primeiro_indice):
            primeiro_indice = indice

    if primeiro_indice is None:
        return nome.strip()

    cortado = nome[:primeiro_indice].strip()
    return cortado if len(cortado) >= _MINIMO_CARACTERES_APOS_CORTE else nome.strip()
