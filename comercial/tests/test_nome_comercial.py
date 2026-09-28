"""Testes de nome_comercial.py — função única de corte do nome comercial
(decisão do diretor, 24/09/2026)."""

from nome_comercial import nome_comercial_limpo


def test_corta_no_primeiro_hifen_com_espacos():
    assert (
        nome_comercial_limpo("Fisioficticia Salud - Fisioterapia en Alicante")
        == "Fisioficticia Salud"
    )


def test_corta_na_barra_vertical():
    assert nome_comercial_limpo("Clínica Ejemplo | Fisioterapia") == "Clínica Ejemplo"


def test_corta_no_travessao():
    assert nome_comercial_limpo("Clínica Ejemplo – Fisioterapia") == "Clínica Ejemplo"


def test_corta_no_ponto_medio():
    assert nome_comercial_limpo("Clínica Ejemplo · Fisioterapia") == "Clínica Ejemplo"


def test_nome_sem_separador_fica_igual():
    assert nome_comercial_limpo("Clínica Ejemplo") == "Clínica Ejemplo"


def test_usa_o_separador_que_aparece_primeiro():
    assert nome_comercial_limpo("ABC - DEF | GHI") == "ABC"


def test_corte_curto_demais_mantem_o_nome_original():
    """Controle negativo central: se o corte deixar menos de 3 caracteres
    (ex.: nome que começa com um hífen isolado), mantém o nome original --
    corte curto demais é sinal de falso positivo, não de subtítulo."""
    assert nome_comercial_limpo("Al - Andalus Fisioterapia") == "Al - Andalus Fisioterapia"


def test_nome_none_devolve_none():
    assert nome_comercial_limpo(None) is None


def test_nome_vazio_devolve_vazio():
    assert nome_comercial_limpo("") == ""


def test_tira_espacos_das_pontas_do_nome_original_sem_separador():
    assert nome_comercial_limpo("  Clínica Ejemplo  ") == "Clínica Ejemplo"
