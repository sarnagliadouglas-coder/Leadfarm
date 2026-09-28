"""Testes das 4 mudanças conceituais (decisão do diretor, 27/09/2026):
classificador FATO / IMPLICACAO_PLAUSIVEL / RESULTADO_NAO_SUSTENTADO
(`afirmacao.py` + checagem 13 do validador), estrutura fato -> consequência
-> CTA dos modelos, aberturas A/B e distribuição da variante.

Prova nas duas pontas (~/.claude/CLAUDE.md §4): o que deve passar passa, o
que deve falhar falha, e cada regra tem controle negativo -- inclusive o
ajuste do diretor à decisão 5: a palavra sozinha NÃO basta para rejeitar."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

import afirmacao
import angulo_mensagem as am
import validador_mensagem

_CONFIG_VALIDACAO = validador_mensagem.carregar_config()
_AFIRMACAO = _CONFIG_VALIDACAO["afirmacao"]
_MENSAGENS_REAIS = am.carregar_mensagens_angulo()
_ABERTURAS_REAIS = am.carregar_aberturas()

_VALORES = dict(nota="4,8", n=8, reseñas_palavra="reseñas", s=11, portal="Top Doctors", rede="Instagram",
                constructor="WordPress")
_ENTRADA = {"nota_google": "4,8", "avaliacoes_google": 8, "segundos": 11}


# --- classificador --------------------------------------------------------------


@pytest.mark.parametrize("frase", [
    "Esto hace que los pacientes abandonen la web.",
    "Está perdiendo consultas porque su web es lenta.",
    "Su web lenta le cuesta pacientes.",
    "La falta de reseñas reduce sus citas.",
    "El site lento está perjudicando sus ventas.",
    "Cuando alguien entra desde el móvil, abandona la web.",  # "cuando alguien" NÃO atenua
    "Si alguien ve esto, se van a otra consulta.",  # "si alguien" NÃO atenua
])
def test_resultado_afirmado_sem_modal_e_resultado_nao_sustentado(frase):
    assert afirmacao.classificar_frase(frase, _AFIRMACAO) == afirmacao.RESULTADO_NAO_SUSTENTADO


@pytest.mark.parametrize("frase", [
    "Para alguien que entra desde el móvil, esa espera puede hacer que abandone la web.",
    "Esa espera podría provocar que alguien deje la página.",
    "Para alguien que entra desde el móvil para ver los servicios, esa espera puede resultar una fricción.",
    "Es un paso pequeño, pero añade una fricción justo cuando alguien quiere contactar.",
    "Si alguien quiere ampliar información, hoy tiene que hacerlo por otros canales.",
])
def test_consequencia_condicional_e_implicacao_plausivel(frase):
    """Controle do ajuste do diretor à decisão 5: a mesma palavra de
    resultado ("abandone", "provocar") com modal passa -- a palavra sozinha
    não basta."""
    assert afirmacao.classificar_frase(frase, _AFIRMACAO) == afirmacao.IMPLICACAO_PLAUSIVEL


@pytest.mark.parametrize("frase", [
    "Abrí su web desde el móvil y tardó 10 segundos en cargar.",
    "Vi su ficha de Google, un 5,0 de media, pero con solo 8 reseñas.",
    "El teléfono aparece, pero no se puede pulsar para llamar.",
])
def test_observacao_pura_e_fato(frase):
    assert afirmacao.classificar_frase(frase, _AFIRMACAO) == afirmacao.FATO


def test_radical_so_casa_no_inicio_da_palavra():
    """Controle negativo do casamento: "despierta" contém "pier" mas não
    começa com "pierd" -- não é marcador de resultado."""
    assert afirmacao.classificar_frase("La web despierta interés.", _AFIRMACAO) == afirmacao.FATO


def test_checagem_13_rejeita_resultado_afirmado_na_mensagem():
    mensagem = "Hola, buenas. Abrí su web desde el móvil. Esto hace que los pacientes abandonen la web. ¿Se lo envío?"
    resultado = am.validar_mensagem_angulo(mensagem, "lentidao", {}, config_validacao=_CONFIG_VALIDACAO)
    assert not resultado.valido
    assert any("afirma resultado" in m for m in resultado.motivos)


def test_checagem_13_aceita_a_mesma_palavra_com_modal():
    mensagem = "Hola, buenas. Abrí su web desde el móvil. Esa espera puede hacer que alguien abandone la web. ¿Se lo envío?"
    resultado = am.validar_mensagem_angulo(mensagem, "lentidao", {}, config_validacao=_CONFIG_VALIDACAO)
    assert resultado.valido, resultado.motivos


def test_checagem_13_desligada_sem_a_chave_afirmacao():
    """Checagem opcional pela ausência da chave (mesmo princípio de 8/9)."""
    config = copy.deepcopy(_CONFIG_VALIDACAO)
    del config["afirmacao"]
    mensagem = "Hola, buenas. Esto hace que los pacientes abandonen la web. ¿Se lo envío?"
    resultado = am.validar_mensagem_angulo(mensagem, "lentidao", {}, config_validacao=config)
    assert not any("afirma resultado" in m for m in resultado.motivos)


# --- estrutura dos modelos ----------------------------------------------------------


def test_config_real_cumpre_a_estrutura():
    assert am.problemas_de_estrutura(_MENSAGENS_REAIS, _AFIRMACAO) == []


def _com(chave, **blocos):
    mensagens = copy.deepcopy(_MENSAGENS_REAIS)
    mensagens[chave].update(blocos)
    return mensagens


def test_estrutura_rejeita_consequencia_afirmada_como_resultado():
    mensagens = _com("lentidao", consequencia="Esa espera hace que los pacientes abandonen la web.")
    assert any("lentidao.consequencia" in p for p in am.problemas_de_estrutura(mensagens, _AFIRMACAO))


def test_estrutura_rejeita_consequencia_que_e_so_fato():
    """A consequência precisa ser implicação -- um fato cru no lugar dela
    não é consequência plausível."""
    mensagens = _com("contato", consequencia="El teléfono está en la cabecera.")
    assert any("contato.consequencia" in p for p in am.problemas_de_estrutura(mensagens, _AFIRMACAO))


def test_estrutura_rejeita_fato_que_afirma_resultado():
    mensagens = _com("sem_site", fato="está perdiendo pacientes porque no tiene web.")
    assert any("sem_site.fato" in p for p in am.problemas_de_estrutura(mensagens, _AFIRMACAO))


def test_estrutura_rejeita_cta_sem_pergunta():
    mensagens = _com("portal", cta="Le escribo otro día.")
    assert any("portal.cta" in p for p in am.problemas_de_estrutura(mensagens, _AFIRMACAO))


def test_estrutura_rejeita_modelo_no_formato_antigo_de_texto_unico():
    mensagens = copy.deepcopy(_MENSAGENS_REAIS)
    mensagens["contato"] = "Hola, buenas.{apresentacao} Entré en su web. ¿Se la envío?"
    assert any("contato:" in p for p in am.problemas_de_estrutura(mensagens, _AFIRMACAO))


def test_carga_derruba_config_fora_da_estrutura(tmp_path):
    ruim = _com("lentidao", consequencia="Esa espera hace que los pacientes abandonen la web.")
    caminho = tmp_path / "mensagens.json"
    caminho.write_text(json.dumps(ruim, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(am.ConfigMensagensAnguloInvalidaError, match="fato -> consequência -> CTA"):
        am.carregar_mensagens_angulo(caminho)


def test_consequencia_null_e_aceita():
    """`portal` não tem consequência na especificação -- null é válido."""
    assert _MENSAGENS_REAIS["portal"]["consequencia"] is None


# --- mensagens reais: A e B, com e sem consequência -----------------------------------


@pytest.mark.parametrize("variante", am.VARIANTES)
@pytest.mark.parametrize("chave", am.MODELOS)
def test_todo_modelo_real_passa_no_validador_nas_duas_variantes(chave, variante):
    mensagem = am.compor_mensagem(
        _MENSAGENS_REAIS[chave], _MENSAGENS_REAIS["saudacao"], _ABERTURAS_REAIS[variante]["texto"], **_VALORES,
    )
    resultado = am.validar_mensagem_angulo(mensagem, chave, _ENTRADA, config_validacao=_CONFIG_VALIDACAO)
    assert resultado.valido, (mensagem, resultado.motivos)


@pytest.mark.parametrize("chave", am.MODELOS)
def test_tirar_a_consequencia_nao_invalida_o_fato(chave):
    """Critério de aceitação da mudança 2: a consequência pode ser removida
    sem invalidar o fato original."""
    modelo = _MENSAGENS_REAIS[chave]
    com = am.compor_mensagem(modelo, "Hola, buenas.", _ABERTURAS_REAIS["B"]["texto"], **_VALORES)
    sem = am.compor_mensagem(
        modelo, "Hola, buenas.", _ABERTURAS_REAIS["B"]["texto"], incluir_consequencia=False, **_VALORES,
    )
    fato = modelo["fato"].format(**_VALORES)
    assert fato in com and fato in sem
    if modelo["consequencia"]:
        assert modelo["consequencia"].format(**_VALORES) not in sem
    resultado = am.validar_mensagem_angulo(sem, chave, _ENTRADA, config_validacao=_CONFIG_VALIDACAO)
    assert resultado.valido, resultado.motivos


@pytest.mark.parametrize("chave", am.MODELOS)
def test_corpo_e_identico_entre_a_e_b(chave):
    """O A/B isola SÓ a abertura (decisão 6)."""
    modelo = _MENSAGENS_REAIS[chave]
    a = am.compor_mensagem(modelo, "Hola, buenas.", _ABERTURAS_REAIS["A"]["texto"], **_VALORES)
    b = am.compor_mensagem(modelo, "Hola, buenas.", _ABERTURAS_REAIS["B"]["texto"], **_VALORES)
    corpo_a = a.split(_ABERTURAS_REAIS["A"]["texto"], 1)[1].strip()
    corpo_b = b.split(_ABERTURAS_REAIS["B"]["texto"], 1)[1].strip()
    assert corpo_a.lower() == corpo_b.lower()
    assert corpo_a[0].isupper() and corpo_b[0].islower()


def test_poucas_avaliacoes_nao_conta_mais_a_historia_causal():
    """Mudança 2: a causa das poucas avaliações não foi verificada."""
    for chave in am.MODELOS:
        texto = json.dumps(_MENSAGENS_REAIS[chave], ensure_ascii=False)
        assert "nadie le pide" not in texto
        assert "sale contento" not in texto


# --- aberturas ----------------------------------------------------------------------


def test_abertura_b_explica_o_motivo_antes_e_resolve_o_segmento():
    b = _ABERTURAS_REAIS["B"]["texto"]
    assert "{segment_positioning}" not in b
    assert "profesionales" in b
    assert b.endswith(":")
    assert _ABERTURAS_REAIS["A"]["nome"] == "service_first"
    assert _ABERTURAS_REAIS["B"]["nome"] == "problem_first"


def test_trocar_o_segmento_muda_so_a_abertura(tmp_path):
    config = json.loads(am.CAMINHO_ABERTURAS_PADRAO.read_text(encoding="utf-8"))
    config["segment_positioning"] = "psicólogos"
    caminho = tmp_path / "aberturas.json"
    caminho.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    aberturas = am.carregar_aberturas(caminho)
    assert "trabajo con webs para psicólogos." in aberturas["B"]["texto"]
    assert aberturas["A"] == _ABERTURAS_REAIS["A"]


def test_segmento_vazio_com_placeholder_levanta_erro(tmp_path):
    config = json.loads(am.CAMINHO_ABERTURAS_PADRAO.read_text(encoding="utf-8"))
    config["segment_positioning"] = "  "
    caminho = tmp_path / "aberturas.json"
    caminho.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(am.ConfigAberturasInvalidaError):
        am.carregar_aberturas(caminho)


def test_variante_ausente_levanta_erro(tmp_path):
    config = json.loads(am.CAMINHO_ABERTURAS_PADRAO.read_text(encoding="utf-8"))
    del config["variantes_abertura"]["B"]
    caminho = tmp_path / "aberturas.json"
    caminho.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(am.ConfigAberturasInvalidaError, match="'B'"):
        am.carregar_aberturas(caminho)


# --- distribuição A/B ---------------------------------------------------------------


def test_distribuidor_alterna_dentro_do_estrato():
    d = am.DistribuidorVariante()
    vistos = []
    for _ in range(4):
        v = d.proxima("lentidao", "whatsapp")
        vistos.append(v)
        d.confirmar("lentidao", "whatsapp")
    assert vistos == ["A", "B", "A", "B"]


def test_distribuidor_estrato_novo_comeca_pela_variante_em_falta():
    """Decisão do diretor, 28/09/2026: estrato novo começa pela variante que
    está em falta no total -- não sempre em A."""
    d = am.DistribuidorVariante()
    d.confirmar("lentidao", "whatsapp")          # A (empate -> A)
    assert d.proxima("lentidao", "whatsapp") == "B"   # alternância dentro do estrato
    assert d.proxima("lentidao", "email") == "B"      # estrato novo: falta B
    assert d.proxima("contato", "whatsapp") == "B"


def test_distribuidor_estratos_de_um_lead_so_ficam_equilibrados():
    """Controle do defeito de 27/09 (37 A x 30 B): muitos estratos de um lead
    só -- antes todos saíam A."""
    d = am.DistribuidorVariante()
    saidas = []
    for i in range(6):
        estrato = (f"angulo{i}", "email")
        saidas.append(d.proxima(*estrato))
        d.confirmar(*estrato)
    assert saidas == ["A", "B", "A", "B", "A", "B"]
    assert d.totais() == {"A": 3, "B": 3}


def test_distribuidor_estrato_ja_iniciado_mantem_a_propria_alternancia():
    d = am.DistribuidorVariante()
    d.confirmar("x", "email")                     # A
    d.confirmar("y", "email")                     # B (em falta)
    d.confirmar("y", "email")                     # A (alterna dentro de y)
    assert d.proxima("y", "email") == "B"
    assert d.proxima("x", "email") == "B"


def test_distribuidor_sem_confirmar_nao_avanca():
    """Mensagem rejeitada pelo validador não é confirmada -- não
    desequilibra o estrato."""
    d = am.DistribuidorVariante()
    assert d.proxima("contato", "whatsapp") == "A"
    assert d.proxima("contato", "whatsapp") == "A"


# --- guarda do construtor (decisão 4) ------------------------------------------------


def _site_classificacao():
    """Módulo do QUALIFICADOR, carregado só para LEITURA -- o ângulo
    `construtor` do COMERCIAL afirma "sin dominio propio", e isso só é fato
    porque o QUALIFICADOR classifica pelo HOST da URL. Se a classificação um
    dia passar a ser pela plataforma (WordPress num domínio próprio), estes
    testes quebram antes de a mensagem mentir."""
    raiz = Path(__file__).resolve().parents[2]
    caminho = raiz / "qualificador" / "prospeccao_ia" / "site_classificacao.py"
    if not caminho.is_file():
        pytest.skip("QUALIFICADOR não está nesta árvore")
    spec = importlib.util.spec_from_file_location("_site_classificacao_qualificador", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.mark.parametrize("url", [
    "https://clinica-ejemplo.wordpress.com",
    "https://clinica.wixsite.com/fisio",
    "https://site247.negocio.site",
])
def test_construtor_so_quando_o_host_e_do_construtor(url):
    sc = _site_classificacao()
    assert sc.classificar_site(url) == sc.CONSTRUTOR
    assert am.escolher_angulo_direta({"classe_site": sc.classificar_site(url), "site": url}) == "construtor"


@pytest.mark.parametrize("url", [
    "https://www.clinica-ejemplo.es",  # pode ser WordPress/Wix por dentro -- domínio é próprio
    "https://wordpress-clinica.es",
    "https://clinica.es/wordpress.com",
])
def test_site_em_dominio_proprio_nunca_vira_construtor(url):
    """Controle negativo: domínio próprio nunca recebe "sin dominio propio"."""
    sc = _site_classificacao()
    classe = sc.classificar_site(url)
    assert classe != sc.CONSTRUTOR
    assert am.escolher_angulo_direta({"classe_site": classe, "site": url}) != "construtor"
