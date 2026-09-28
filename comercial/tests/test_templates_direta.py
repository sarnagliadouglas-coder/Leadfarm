"""Testes de templates_direta.py — nenhuma chamada de LLM, nenhum envio.
Mensagem sempre montada por template determinístico; o validador reusado é
o mesmo da Etapa E2 (validador_mensagem.validar_mensagem)."""

import json

import pytest

from templates_direta import (
    ConfigApresentacaoInvalidaError,
    ConfigTemplatesInvalidaError,
    carregar_apresentacao,
    carregar_templates_direta,
    montar_mensagem_direta,
    validar_mensagem_direta,
)

_LIMIARES = {"nota_google_minima": 4.5, "avaliacoes_minimas": 15}

_CONFIG_TEMPLATES = {
    "templates": {
        "sem_site": "Hola, buenas.{apresentacao} Vi su perfil en Google Maps{elogio}. Noté que no tiene página web propia. ¿Le interesa que le muestre cómo podría verse la suya?",
        "portal": "Hola, buenas.{apresentacao} Vi su perfil en Google Maps{elogio}. Noté que su presencia en internet es un perfil en {portal}, sin web propia. ¿Le interesa ver cómo sería tener la suya?",
        "rede_social": "Hola, buenas.{apresentacao} Vi su perfil en Google Maps{elogio}. Noté que su presencia en internet es su perfil de {rede}, sin web propia. ¿Le interesa ver cómo sería tener la suya?",
        "construtor": "Hola, buenas.{apresentacao} Vi su perfil en Google Maps{elogio}. Noté que su web usa una dirección gratuita ({dominio}). ¿Le interesa ver cómo quedaría con un dominio propio?",
    },
    "elogio_template": ", con {nota} estrellas y {avaliacoes} reseñas, enhorabuena",
    "nomes_dominio": {"doctoralia.es": "Doctoralia", "instagram.com": "Instagram"},
}

_CONFIG_VALIDACAO = {
    "max_palavras_mensagem_1": 80,
    "simbolos_moeda": ["€"],
    "palavras_preco": ["precio", "tarifa"],
    "marcas_informais_es": ["tú", "tu", "te", "tienes", "puedes"],
    "saudacao_fixa": "Hola, buenas",
    "termos_proibidos": ["está caída", "está caído", "no funciona"],
}


def _lead(**over):
    base = {
        "nome": "Clínica Ejemplo", "classe_site": "sem_site", "site": "",
        "nota": "4.8", "avaliacoes": "27", "telefone": "600000101",
    }
    base.update(over)
    return base


def test_sem_site_monta_mensagem_com_saudacao_e_pergunta():
    mensagem = montar_mensagem_direta(
        _lead(), config_templates=_CONFIG_TEMPLATES, apresentacao="", limiares_reputacao=_LIMIARES
    )
    assert mensagem.startswith("Hola, buenas.")
    assert mensagem.endswith("?")
    assert "perfil en Google Maps" in mensagem


# --- nome do negócio fora das mensagens (decisão do diretor, 24/09/2026, --
# quarta rodada): o template não recebe mais {nome} -- "Vi {nome} en Google
# Maps" virou "Vi su perfil en Google Maps". nome_comercial_limpo continua
# existindo só para a checagem do validador (validador_mensagem.py), não
# para compor mensagem nenhuma.


def test_mensagem_nunca_cita_o_nome_do_negocio_com_ou_sem_subtitulo_do_maps():
    for nome in ("Clínica Ejemplo", "Fisioficticia Salud - Fisioterapia en Alicante"):
        mensagem = montar_mensagem_direta(
            _lead(nome=nome), config_templates=_CONFIG_TEMPLATES, apresentacao="", limiares_reputacao=_LIMIARES,
        )
        assert "Clínica" not in mensagem and "Fisioficticia" not in mensagem, mensagem


def test_classe_sem_template_devolve_none():
    """Controle negativo: leads "proprio" (mensagem vem da Etapa E2, não
    daqui) não geram template nenhum."""
    mensagem = montar_mensagem_direta(
        _lead(classe_site="proprio"), config_templates=_CONFIG_TEMPLATES, apresentacao="",
        limiares_reputacao=_LIMIARES,
    )
    assert mensagem is None


# --- elogio respeita o limiar (reuso do limiar da Etapa E2) ----------------

def test_elogio_entra_quando_bate_o_limiar():
    mensagem = montar_mensagem_direta(
        _lead(nota="4.8", avaliacoes="27"), config_templates=_CONFIG_TEMPLATES, apresentacao="",
        limiares_reputacao=_LIMIARES,
    )
    assert "estrellas" in mensagem
    assert "4,8" in mensagem  # vírgula decimal, nunca ponto
    assert "27 reseñas" in mensagem


def test_elogio_nao_entra_quando_fica_abaixo_do_limiar():
    """Controle negativo central: nota abaixo do corte -- nada de elogio,
    mensagem vai direto ao problema."""
    mensagem = montar_mensagem_direta(
        _lead(nota="3.0", avaliacoes="27"), config_templates=_CONFIG_TEMPLATES, apresentacao="",
        limiares_reputacao=_LIMIARES,
    )
    assert "estrellas" not in mensagem
    assert "enhorabuena" not in mensagem


def test_elogio_nao_entra_quando_avaliacoes_fica_abaixo_mesmo_com_nota_boa():
    mensagem = montar_mensagem_direta(
        _lead(nota="5.0", avaliacoes="10"), config_templates=_CONFIG_TEMPLATES, apresentacao="",
        limiares_reputacao=_LIMIARES,
    )
    assert "estrellas" not in mensagem


def test_elogio_no_limiar_exato_entra():
    mensagem = montar_mensagem_direta(
        _lead(nota="4.5", avaliacoes="15"), config_templates=_CONFIG_TEMPLATES, apresentacao="",
        limiares_reputacao=_LIMIARES,
    )
    assert "estrellas" in mensagem
    assert "4,5" in mensagem


# --- apresentacao -----------------------------------------------------------

def test_apresentacao_vazia_nao_deixa_espaco_estranho():
    mensagem = montar_mensagem_direta(
        _lead(nota=None, avaliacoes=None), config_templates=_CONFIG_TEMPLATES, apresentacao="",
        limiares_reputacao=_LIMIARES,
    )
    assert mensagem.startswith("Hola, buenas. Vi ")


def test_apresentacao_preenchida_entra_logo_apos_a_saudacao():
    mensagem = montar_mensagem_direta(
        _lead(nota=None, avaliacoes=None), config_templates=_CONFIG_TEMPLATES,
        apresentacao=" Somos ByteConsult.", limiares_reputacao=_LIMIARES,
    )
    assert mensagem.startswith("Hola, buenas. Somos ByteConsult. Vi ")


# --- portal / rede_social / construtor --------------------------------------

def test_portal_usa_nome_mapeado_do_dominio():
    mensagem = montar_mensagem_direta(
        _lead(classe_site="portal", site="https://www.doctoralia.es/clinica-x", nota=None, avaliacoes=None),
        config_templates=_CONFIG_TEMPLATES, apresentacao="", limiares_reputacao=_LIMIARES,
    )
    assert "perfil en Doctoralia" in mensagem


def test_portal_sem_mapeamento_cai_no_rotulo_derivado_do_dominio():
    mensagem = montar_mensagem_direta(
        _lead(classe_site="portal", site="https://www.booksy.com/x", nota=None, avaliacoes=None),
        config_templates=_CONFIG_TEMPLATES, apresentacao="", limiares_reputacao=_LIMIARES,
    )
    assert "perfil en Booksy" in mensagem


def test_rede_social_usa_nome_mapeado():
    mensagem = montar_mensagem_direta(
        _lead(classe_site="rede_social", site="https://instagram.com/clinicax", nota=None, avaliacoes=None),
        config_templates=_CONFIG_TEMPLATES, apresentacao="", limiares_reputacao=_LIMIARES,
    )
    assert "perfil de Instagram" in mensagem


def test_construtor_usa_o_dominio_cru_nunca_um_nome_bonito():
    mensagem = montar_mensagem_direta(
        _lead(classe_site="construtor", site="https://clinicax.negocio.site", nota=None, avaliacoes=None),
        config_templates=_CONFIG_TEMPLATES, apresentacao="", limiares_reputacao=_LIMIARES,
    )
    assert "clinicax.negocio.site" in mensagem


def test_validar_mensagem_direta_pega_o_nome_do_negocio_se_vazar_por_outro_campo():
    """Rede de segurança: mesmo sem {nome} no template, valida se o nome do
    negócio vazou por algum outro caminho (config quebrada de propósito, com
    o nome hardcoded no texto do template)."""
    config_quebrada = {
        "templates": {"sem_site": "Hola, buenas. Vi Clínica Ejemplo en Google Maps. ¿Le interesa?"},
        "elogio_template": "",
        "nomes_dominio": {},
    }
    mensagem = montar_mensagem_direta(
        _lead(), config_templates=config_quebrada, apresentacao="", limiares_reputacao=_LIMIARES
    )
    resultado = validar_mensagem_direta(mensagem, _lead(), config_validacao=_CONFIG_VALIDACAO)
    assert not resultado.valido
    assert any("nome do negócio" in m for m in resultado.motivos)


# --- validar_mensagem_direta (reuso do validador da Etapa E2) --------------

def test_mensagem_de_template_valido_passa_no_validador():
    mensagem = montar_mensagem_direta(
        _lead(nota="4.8", avaliacoes="27"), config_templates=_CONFIG_TEMPLATES, apresentacao="",
        limiares_reputacao=_LIMIARES,
    )
    resultado = validar_mensagem_direta(mensagem, _lead(nota="4.8", avaliacoes="27"), config_validacao=_CONFIG_VALIDACAO)
    assert resultado.valido, resultado.motivos


def test_template_sem_saudacao_falha_no_validador():
    """Controle: se a config do template estiver quebrada (sem "Hola,
    buenas." no início), o MESMO validador da Etapa E2 pega."""
    resultado = validar_mensagem_direta("Vi su negocio, ¿le interesa?", _lead(), config_validacao=_CONFIG_VALIDACAO)
    assert not resultado.valido
    assert any("saudação" in m for m in resultado.motivos)


def test_numero_do_elogio_bate_com_a_entrada_no_validador():
    """O número citado pelo elogio (nota e avaliações) precisa bater com o
    que foi passado como entrada ao validador -- mesmo mecanismo da Etapa
    E2, aqui provado com o template determinístico."""
    lead = _lead(nota="4.8", avaliacoes="27")
    mensagem = montar_mensagem_direta(lead, config_templates=_CONFIG_TEMPLATES, apresentacao="", limiares_reputacao=_LIMIARES)
    resultado = validar_mensagem_direta(mensagem, lead, config_validacao=_CONFIG_VALIDACAO)
    assert resultado.valido, resultado.motivos


# --- config loaders ----------------------------------------------------------

def test_carregar_templates_direta_le_o_arquivo_real():
    config = carregar_templates_direta()
    assert "templates" in config and "elogio_template" in config
    for classe in ("sem_site", "superficie_google", "portal", "rede_social", "construtor"):
        assert classe in config["templates"]


def test_carregar_templates_direta_arquivo_ausente_levanta_erro_claro(tmp_path):
    with pytest.raises(ConfigTemplatesInvalidaError, match="não encontrada"):
        carregar_templates_direta(tmp_path / "nao-existe.json")


def test_carregar_templates_direta_sem_chaves_exigidas_levanta_erro(tmp_path):
    caminho = tmp_path / "t.json"
    caminho.write_text(json.dumps({"algo": 1}), encoding="utf-8")
    with pytest.raises(ConfigTemplatesInvalidaError):
        carregar_templates_direta(caminho)


def test_carregar_apresentacao_le_o_arquivo_real_devolve_string():
    """Controle: o arquivo real é legível e devolve string -- sem assumir um
    valor específico (item 7, decisão do diretor, 24/09/2026: o arquivo real
    passou a ter conteúdo; o valor em si é config, não comportamento a
    travar em teste)."""
    assert isinstance(carregar_apresentacao(), str)


def test_carregar_apresentacao_vazia_devolve_vazia(tmp_path):
    """A regra que o teste anterior travava (vazio -> vazio) continua
    provada, agora contra `tmp_path`, não o arquivo real."""
    caminho = tmp_path / "a.json"
    caminho.write_text(json.dumps({"apresentacao": ""}), encoding="utf-8")
    assert carregar_apresentacao(caminho) == ""


def test_carregar_apresentacao_arquivo_ausente_levanta_erro_claro(tmp_path):
    with pytest.raises(ConfigApresentacaoInvalidaError, match="não encontrada"):
        carregar_apresentacao(tmp_path / "nao-existe.json")


def test_carregar_apresentacao_preenchida(tmp_path):
    caminho = tmp_path / "a.json"
    caminho.write_text(json.dumps({"apresentacao": " Somos X."}), encoding="utf-8")
    assert carregar_apresentacao(caminho) == " Somos X."
