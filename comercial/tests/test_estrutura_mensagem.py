"""Testes das 4 mudanças conceituais (decisão do diretor, 27/09/2026):
classificador FATO / IMPLICACAO_PLAUSIVEL / RESULTADO_NAO_SUSTENTADO
(`afirmacao.py` + checagem 13 do validador) e estrutura fato -> consequência
-> CTA dos modelos. A abertura A/B (mudança 4, mesma data) foi aposentada em
29/09/2026 (D12 Fase 5.1) -- as duas variantes já tinham o mesmo texto desde
a Fase 5, sem nenhum experimento por trás; os testes de alternância/
distribuição foram removidos com o código que testavam
(`DistribuidorVariante`, `carregar_aberturas`), não afrouxados.

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
_APRESENTACAO_REAL = am.carregar_apresentacao()

_VALORES = dict(nota="4,8", n=8, reseñas_palavra="reseñas", s=11, portal="Top Doctors", rede="Instagram",
                constructor="WordPress", nombre="Clínica Sol", segundos=11, texto_encontrado="info@website.com",
                cliente_paciente="paciente")
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


# --- mensagens reais, com e sem consequência -----------------------------------


@pytest.mark.parametrize("chave", am.MODELOS)
def test_todo_modelo_real_passa_no_validador(chave):
    mensagem = am.compor_mensagem(
        _MENSAGENS_REAIS[chave], _MENSAGENS_REAIS["saudacao"], _APRESENTACAO_REAL, **_VALORES,
    )
    resultado = am.validar_mensagem_angulo(mensagem, chave, _ENTRADA, config_validacao=_CONFIG_VALIDACAO)
    assert resultado.valido, (mensagem, resultado.motivos)


@pytest.mark.parametrize("chave", am.MODELOS)
def test_tirar_a_consequencia_nao_invalida_o_fato(chave):
    """Critério de aceitação da mudança 2: a consequência pode ser removida
    sem invalidar o fato original. Comparação sem diferenciar maiúscula --
    a apresentação atual não termina em ':', então a mensagem final
    capitaliza a primeira letra do fato; o teste continua provando o
    CONTEÚDO do fato, não a capitalização, que é regra de
    `compor_mensagem`, não deste caso."""
    modelo = _MENSAGENS_REAIS[chave]
    com = am.compor_mensagem(modelo, "Hola, buenas.", _APRESENTACAO_REAL, **_VALORES)
    sem = am.compor_mensagem(
        modelo, "Hola, buenas.", _APRESENTACAO_REAL, incluir_consequencia=False, **_VALORES,
    )
    fato = modelo["fato"].format(**_VALORES)
    assert fato.lower() in com.lower() and fato.lower() in sem.lower()
    if modelo["consequencia"]:
        assert modelo["consequencia"].format(**_VALORES).lower() not in sem.lower()
    resultado = am.validar_mensagem_angulo(sem, chave, _ENTRADA, config_validacao=_CONFIG_VALIDACAO)
    assert resultado.valido, resultado.motivos


def test_poucas_avaliacoes_nao_conta_mais_a_historia_causal():
    """Mudança 2: a causa das poucas avaliações não foi verificada."""
    for chave in am.MODELOS:
        texto = json.dumps(_MENSAGENS_REAIS[chave], ensure_ascii=False)
        assert "nadie le pide" not in texto
        assert "sale contento" not in texto


# --- apresentação (D12 Fase 5.1, aposentadoria da abertura A/B, 29/09/2026) ----------


def test_apresentacao_real_e_universal():
    """`carregar_apresentacao` devolve um texto único, sem especialização de
    setor nem menção a Google Business Profile (D12 Fases 1-3). Substitui os
    testes antigos de A/B (`carregar_aberturas`, variantes, segmento) --
    removidos com o mecanismo que testavam, não afrouxados."""
    assert _APRESENTACAO_REAL == "Soy Douglas, hago webs aquí en Alicante."  # unificada em 03/10/2026 (diretor)
    for termo in ("salud", "consultas", "pacientes", "psicólog", "médic", "ficha de Google", "{segment_positioning}"):
        assert termo not in _APRESENTACAO_REAL


def test_carregar_apresentacao_arquivo_sem_chave_levanta_erro(tmp_path):
    caminho = tmp_path / "apresentacao.json"
    caminho.write_text(json.dumps({}), encoding="utf-8")
    with pytest.raises(am.ConfigApresentacaoInvalidaError):
        am.carregar_apresentacao(caminho)


def test_carregar_apresentacao_arquivo_ilegivel_levanta_erro(tmp_path):
    with pytest.raises(am.ConfigApresentacaoInvalidaError):
        am.carregar_apresentacao(tmp_path / "nao-existe.json")


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
