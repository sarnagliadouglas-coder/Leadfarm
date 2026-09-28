"""Testes de validador_mensagem.py — nenhuma chamada de LLM. Cada regra do
desenho aprovado (RUMO-COMERCIAL-2026-09.md, "DESENHO APROVADO PELO DIRETOR
EM 23/09") ganha um caso que passa, um que falha, e onde fizer sentido um
controle negativo adicional."""

import json

import pytest

from validador_mensagem import (
    CAMPOS_OBRIGATORIOS,
    ConfigValidacaoInvalidaError,
    carregar_config,
    validar_mensagem,
)

_ENTRADA = {
    "nome": "Clínica Ejemplo",
    "problemas_vendaveis": [
        {"tipo": "lento_no_celular", "evidencia": "LCP de 5200ms", "medicao": "psi"}
    ],
    "avaliacoes_google": 27,
    "tem_whatsapp": True,
}

_CONFIG = {
    "max_palavras_mensagem_1": 80,
    "simbolos_moeda": ["€", "$"],
    "palavras_preco": ["precio", "coste", "tarifa", "euro"],
    "marcas_informais_es": ["tú", "tu", "te", "tienes", "puedes"],
}


def _resposta_valida(mensagem="Vi que su web tarda en cargar en el móvil. ¿Le envío lo que vi?", trecho_site=None):
    dados = {
        "estrategia": "Abrir con la lentitud móvil, que ya está confirmada.",
        "canal_sugerido": "whatsapp",
        "mensagem_1": mensagem,
        "fato_usado": "lento_no_celular",
    }
    if trecho_site is not None:
        dados["trecho_site"] = trecho_site
    return json.dumps(dados)


def test_resposta_valida_passa_sem_motivos():
    mensagem = "Vi que su web tarda en cargar en el móvil. ¿Le envío lo que vi?"
    resultado = validar_mensagem(_resposta_valida(mensagem), _ENTRADA, config=_CONFIG)
    assert resultado.valido
    assert resultado.motivos == []
    assert resultado.dados["mensagem_1"] == mensagem


def test_json_mal_formado_falha_com_motivo_claro():
    resultado = validar_mensagem("isso não é json{{{", _ENTRADA, config=_CONFIG)
    assert not resultado.valido
    assert resultado.dados is None
    assert "JSON" in resultado.motivos[0]


def test_extrai_json_de_dentro_de_cercas_de_codigo():
    bruto = "```json\n" + _resposta_valida() + "\n```"
    resultado = validar_mensagem(bruto, _ENTRADA, config=_CONFIG)
    assert resultado.valido


def test_json_que_nao_e_objeto_falha():
    resultado = validar_mensagem("[1, 2, 3]", _ENTRADA, config=_CONFIG)
    assert not resultado.valido
    assert "objeto" in resultado.motivos[0]


@pytest.mark.parametrize("campo", CAMPOS_OBRIGATORIOS)
def test_campo_obrigatorio_ausente_falha(campo):
    dados = json.loads(_resposta_valida())
    del dados[campo]
    resultado = validar_mensagem(json.dumps(dados), _ENTRADA, config=_CONFIG)
    assert not resultado.valido
    assert campo in resultado.motivos[0] or "ausentes" in resultado.motivos[0]


def test_campo_obrigatorio_vazio_falha():
    dados = json.loads(_resposta_valida())
    dados["fato_usado"] = "   "
    resultado = validar_mensagem(json.dumps(dados), _ENTRADA, config=_CONFIG)
    assert not resultado.valido


def test_mensagem_dentro_do_limite_de_palavras_passa():
    resultado = validar_mensagem(_resposta_valida(), _ENTRADA, config=_CONFIG)
    assert resultado.valido


def test_mensagem_acima_do_limite_de_palavras_falha():
    mensagem_longa = " ".join(["palabra"] * 81) + "?"
    resultado = validar_mensagem(_resposta_valida(mensagem_longa), _ENTRADA, config=_CONFIG)
    assert not resultado.valido
    assert any("palavras" in m for m in resultado.motivos)


def test_mensagem_terminando_em_pergunta_passa():
    resultado = validar_mensagem(_resposta_valida("¿Le interesa que se lo muestre?"), _ENTRADA, config=_CONFIG)
    assert resultado.valido


def test_mensagem_sem_interrogacao_final_falha():
    resultado = validar_mensagem(_resposta_valida("Vi algo interesante en su web."), _ENTRADA, config=_CONFIG)
    assert not resultado.valido
    assert any("'?'" in m for m in resultado.motivos)


def test_mensagem_sem_url_passa():
    resultado = validar_mensagem(_resposta_valida("¿Le envío lo que vi?"), _ENTRADA, config=_CONFIG)
    assert resultado.valido


def test_mensagem_com_url_falha():
    resultado = validar_mensagem(
        _resposta_valida("Mire su web en www.ejemplo.com, ¿le interesa?"), _ENTRADA, config=_CONFIG
    )
    assert not resultado.valido
    assert any("URL" in m for m in resultado.motivos)


def test_mensagem_sem_simbolo_de_moeda_nem_palavra_de_preco_passa():
    resultado = validar_mensagem(_resposta_valida(), _ENTRADA, config=_CONFIG)
    assert resultado.valido


def test_mensagem_com_simbolo_de_moeda_falha():
    resultado = validar_mensagem(_resposta_valida("Esto cuesta 50€, ¿le interesa?"), _ENTRADA, config=_CONFIG)
    assert not resultado.valido
    assert any("moeda" in m for m in resultado.motivos)


def test_mensagem_com_palavra_de_preco_falha():
    resultado = validar_mensagem(
        _resposta_valida("Tenemos una tarifa especial, ¿le interesa?"), _ENTRADA, config=_CONFIG
    )
    assert not resultado.valido
    assert any("preço" in m for m in resultado.motivos)


def test_mensagem_formal_sem_marca_informal_passa():
    resultado = validar_mensagem(_resposta_valida("¿Le interesa que se lo muestre?"), _ENTRADA, config=_CONFIG)
    assert resultado.valido


def test_mensagem_com_tratamento_informal_falha():
    resultado = validar_mensagem(
        _resposta_valida("Vi que tu web tarda en cargar, ¿puedes revisarlo?"), _ENTRADA, config=_CONFIG
    )
    assert not resultado.valido
    assert any("informal" in m for m in resultado.motivos)


def test_numero_presente_na_entrada_passa():
    resultado = validar_mensagem(
        _resposta_valida("Vi que tiene 27 reseñas en Google, ¿le envío lo que vi?"), _ENTRADA, config=_CONFIG
    )
    assert resultado.valido


def test_numero_fora_da_entrada_falha():
    """Controle negativo central da regra 7: um número que o modelo inventou
    -- não está em nenhum lugar da entrada daquele lead."""
    resultado = validar_mensagem(
        _resposta_valida("Le puedo ahorrar 500 euros al mes, ¿le interesa?"), _ENTRADA, config=_CONFIG
    )
    assert not resultado.valido
    assert any("número fora da entrada" in m for m in resultado.motivos)


# --- Bordas do número por extenso: compostos e "dezena y unidade" -------
# Achado 24/09/2026 (rodada seguinte ao teste real): "veintidós" (composto
# de uma palavra) não era reconhecido, e "treinta y dos" virava dois números
# soltos (30 e 2), nenhum dos quais bate com o 32 real -- rejeição indevida.

_ENTRADA_32 = {"nome": "Clínica Ejemplo", "avaliacoes_google": 32, "tem_whatsapp": True}
_ENTRADA_22 = {"nome": "Clínica Ejemplo", "avaliacoes_google": 22, "tem_whatsapp": True}

_CONFIG_COM_EXTENSO = {
    **_CONFIG,
    "numeros_por_extenso_es": {
        "uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5",
        "seis": "6", "siete": "7", "ocho": "8", "nueve": "9", "diez": "10",
        "veinte": "20", "veintidós": "22", "veintinueve": "29",
        "treinta": "30", "cuarenta": "40", "cincuenta": "50",
        "sesenta": "60", "setenta": "70", "ochenta": "80", "noventa": "90",
    },
}


def test_composto_de_uma_palavra_veintidos_passa_quando_bate_com_a_entrada():
    resultado = validar_mensagem(
        _resposta_valida("Vi que tiene veintidós reseñas en Google, ¿le envío lo que vi?"),
        _ENTRADA_22,
        config=_CONFIG_COM_EXTENSO,
    )
    assert resultado.valido, resultado.motivos


def test_composto_de_uma_palavra_veintidos_falha_quando_nao_bate():
    resultado = validar_mensagem(
        _resposta_valida("Vi que tiene veintidós reseñas en Google, ¿le envío lo que vi?"),
        _ENTRADA_32,  # entrada tem 32, não 22
        config=_CONFIG_COM_EXTENSO,
    )
    assert not resultado.valido
    assert any("número fora da entrada" in m for m in resultado.motivos)


def test_composto_dezena_y_unidade_treinta_y_dos_passa_quando_bate_com_32():
    """O caso central do defeito: "treinta y dos" tem que valer 32, não
    rejeitar por causa de um "30" ou "2" que não existem soltos na entrada."""
    resultado = validar_mensagem(
        _resposta_valida("Vi que tiene treinta y dos reseñas en Google, ¿le envío lo que vi?"),
        _ENTRADA_32,
        config=_CONFIG_COM_EXTENSO,
    )
    assert resultado.valido, resultado.motivos


def test_composto_dezena_y_unidade_nao_deixa_sobrar_30_nem_2_soltos():
    """Controle direto do defeito: uma entrada que só tem 32 (não 30, não 2)
    -- se "treinta"/"dos" ainda contassem como números soltos, isto falharia
    mesmo com "treinta y dos" citado corretamente."""
    entrada_so_32 = {"nome": "X", "avaliacoes_google": 32, "tem_whatsapp": True}
    resultado = validar_mensagem(
        _resposta_valida("Tiene treinta y dos reseñas, ¿le interesa?"),
        entrada_so_32,
        config=_CONFIG_COM_EXTENSO,
    )
    assert resultado.valido, resultado.motivos


def test_composto_dezena_y_unidade_falha_quando_a_soma_nao_bate():
    """Controle negativo: "treinta y dos" (32) citado quando a entrada só
    tem 22 -- tem que continuar rejeitando exagero/erro, exatamente como
    "casi diez" era rejeitado quando o real era 8."""
    resultado = validar_mensagem(
        _resposta_valida("Vi que tiene treinta y dos reseñas en Google, ¿le envío lo que vi?"),
        _ENTRADA_22,
        config=_CONFIG_COM_EXTENSO,
    )
    assert not resultado.valido
    assert any("número fora da entrada" in m for m in resultado.motivos)


def test_dezena_solta_sem_y_continua_funcionando_normalmente():
    """Regressão: a máscara do composto não deve atrapalhar o caso comum de
    uma dezena sozinha, sem "y" nenhum."""
    entrada_30 = {"nome": "X", "avaliacoes_google": 30, "tem_whatsapp": True}
    resultado = validar_mensagem(
        _resposta_valida("Vi que tiene treinta reseñas en Google, ¿le envío lo que vi?"),
        entrada_30,
        config=_CONFIG_COM_EXTENSO,
    )
    assert resultado.valido, resultado.motivos


def test_carregar_config_arquivo_ausente_levanta_erro_claro(tmp_path):
    with pytest.raises(ConfigValidacaoInvalidaError, match="não encontrada"):
        carregar_config(tmp_path / "nao-existe.json")


def test_carregar_config_json_invalido_levanta_erro_claro(tmp_path):
    caminho = tmp_path / "config.json"
    caminho.write_text("{ nao e json", encoding="utf-8")
    with pytest.raises(ConfigValidacaoInvalidaError, match="JSON válido"):
        carregar_config(caminho)


def test_carregar_config_sem_chaves_exigidas_levanta_erro_claro(tmp_path):
    caminho = tmp_path / "config.json"
    caminho.write_text(json.dumps({"algo": 1}), encoding="utf-8")
    with pytest.raises(ConfigValidacaoInvalidaError):
        carregar_config(caminho)


def test_carregar_config_le_o_arquivo_real():
    """Controle: o arquivo real de configuração tem o formato exigido."""
    config = carregar_config()
    for chave in (
        "max_palavras_mensagem_1",
        "simbolos_moeda",
        "palavras_preco",
        "marcas_informais_es",
        "saudacao_fixa",
        "termos_proibidos",
    ):
        assert chave in config


# --- Saudação fixa e termos proibidos (decisões do diretor, 24/09/2026) ---

_CONFIG_COM_SAUDACAO = {
    **_CONFIG,
    "saudacao_fixa": "Hola, buenas",
    "termos_proibidos": ["está caído", "está caída", "caído", "caída", "no funciona", "está roto", "celular"],
}


def test_saudacao_fixa_no_inicio_passa():
    resultado = validar_mensagem(
        _resposta_valida("Hola, buenas. Vi algo interesante en su web. ¿Le envío lo que vi?"),
        _ENTRADA,
        config=_CONFIG_COM_SAUDACAO,
    )
    assert resultado.valido, resultado.motivos


def test_saudacao_ausente_falha():
    resultado = validar_mensagem(
        _resposta_valida("Vi algo interesante en su web. ¿Le envío lo que vi?"),
        _ENTRADA,
        config=_CONFIG_COM_SAUDACAO,
    )
    assert not resultado.valido
    assert any("saudação fixa" in m for m in resultado.motivos)


def test_saudacao_no_meio_da_frase_nao_conta_tem_que_ser_no_inicio():
    """Controle negativo: a saudação precisa abrir a mensagem, não aparecer
    em qualquer lugar."""
    resultado = validar_mensagem(
        _resposta_valida("Vi algo interesante en su web, hola, buenas. ¿Le envío lo que vi?"),
        _ENTRADA,
        config=_CONFIG_COM_SAUDACAO,
    )
    assert not resultado.valido
    assert any("saudação fixa" in m for m in resultado.motivos)


def test_saudacao_fixa_ausente_da_config_nao_aplica_a_regra():
    """Uma unidade que testa outra regra (ex.: preço, informalidade) não
    precisa satisfazer a saudação também -- checagem opcional pela ausência
    da chave, não um valor default escondido no código."""
    resultado = validar_mensagem(
        _resposta_valida("Vi algo interesante en su web. ¿Le envío lo que vi?"), _ENTRADA, config=_CONFIG
    )
    assert resultado.valido, resultado.motivos


def test_termo_proibido_esta_caido_falha():
    resultado = validar_mensagem(
        _resposta_valida("Hola, buenas. Vi que su web está caída. ¿Le envío lo que vi?"),
        _ENTRADA,
        config=_CONFIG_COM_SAUDACAO,
    )
    assert not resultado.valido
    assert any("termo proibido" in m for m in resultado.motivos)


def test_frase_alternativa_no_me_cargo_passa():
    """A frase que a decisão do diretor recomenda no lugar de "está caída"."""
    resultado = validar_mensagem(
        _resposta_valida("Hola, buenas. No me cargó cuando intenté entrar a su web. ¿Le envío lo que vi?"),
        _ENTRADA,
        config=_CONFIG_COM_SAUDACAO,
    )
    assert resultado.valido, resultado.motivos


def test_termo_proibido_no_funciona_falha():
    resultado = validar_mensagem(
        _resposta_valida("Hola, buenas. Vi que su web no funciona. ¿Le envío lo que vi?"),
        _ENTRADA,
        config=_CONFIG_COM_SAUDACAO,
    )
    assert not resultado.valido
    assert any("termo proibido" in m for m in resultado.motivos)


def test_termos_proibidos_ausente_da_config_nao_aplica_a_regra():
    resultado = validar_mensagem(
        _resposta_valida("Vi que su web está caída. ¿Le envío lo que vi?"), _ENTRADA, config=_CONFIG
    )
    assert resultado.valido, resultado.motivos


def test_termo_proibido_celular_falha_espanhol_da_espanha_diz_movil():
    resultado = validar_mensagem(
        _resposta_valida("Hola, buenas. Vi que su web tarda en el celular. ¿Le envío lo que vi?"),
        _ENTRADA, config=_CONFIG_COM_SAUDACAO,
    )
    assert not resultado.valido
    assert any("termo proibido" in m for m in resultado.motivos)


def test_movil_passa_no_lugar_de_celular():
    resultado = validar_mensagem(
        _resposta_valida("Hola, buenas. Vi que su web tarda en el móvil. ¿Le envío lo que vi?"),
        _ENTRADA, config=_CONFIG_COM_SAUDACAO,
    )
    assert resultado.valido, resultado.motivos


# --- trecho_site (v3 do prompt, 24/09/2026; regra endurecida na v4, mesma data) --

_ENTRADA_COM_TEXTO_SITE = {**_ENTRADA, "texto_site": "Ofrecemos fisioterapia deportiva y rehabilitación en Sevilla."}


def test_trecho_site_null_sem_texto_site_na_entrada_nao_aplica_a_regra():
    """Sem texto_site na entrada, trecho_site null é o esperado -- nada a
    citar, nenhuma regra a violar."""
    resultado = validar_mensagem(_resposta_valida(trecho_site=None), _ENTRADA, config=_CONFIG)
    assert resultado.valido, resultado.motivos


def test_trecho_site_presente_literalmente_no_texto_passa():
    resultado = validar_mensagem(
        _resposta_valida(trecho_site="fisioterapia deportiva"), _ENTRADA_COM_TEXTO_SITE, config=_CONFIG
    )
    assert resultado.valido, resultado.motivos


def test_trecho_site_inventado_falha():
    """Controle negativo central: um trecho que o modelo inventou -- não
    existe no texto real do site -- é tratado como fato inventado."""
    resultado = validar_mensagem(
        _resposta_valida(trecho_site="cirugía estética"), _ENTRADA_COM_TEXTO_SITE, config=_CONFIG
    )
    assert not resultado.valido
    assert any("trecho_site" in m for m in resultado.motivos)


def test_trecho_site_bate_ignorando_espacos_e_maiusculas():
    """Comparação normalizada, não byte a byte -- o modelo pode ter copiado
    com quebra de linha ou maiúscula diferente."""
    resultado = validar_mensagem(
        _resposta_valida(trecho_site="FISIOTERAPIA   DEPORTIVA"), _ENTRADA_COM_TEXTO_SITE, config=_CONFIG
    )
    assert resultado.valido, resultado.motivos


def test_trecho_site_sem_texto_site_na_entrada_falha():
    """Controle: se a entrada não tem texto_site nenhum, nenhum trecho pode
    ser citado como vindo dele."""
    resultado = validar_mensagem(_resposta_valida(trecho_site="fisioterapia"), _ENTRADA, config=_CONFIG)
    assert not resultado.valido


# --- v4: trecho_site obrigatório quando há texto_site (decisão do diretor, --
# 24/09/2026 -- rodada real com prompt v3 mostrou 37 de 37 leads com
# trecho_site nulo mesmo tendo texto_site: a citação era opcional demais).


def test_trecho_site_nulo_com_texto_site_na_entrada_falha():
    """Prova central da v4: texto_site presente e trecho_site null --
    rejeitado, mensagem sem detalhe do site."""
    resultado = validar_mensagem(_resposta_valida(trecho_site=None), _ENTRADA_COM_TEXTO_SITE, config=_CONFIG)
    assert not resultado.valido
    assert any("detalhe do site" in m for m in resultado.motivos)


def test_trecho_site_presente_com_texto_site_na_entrada_continua_passando():
    """Controle: com texto_site na entrada e trecho_site válido citado, a
    regra da v4 não rejeita à toa."""
    resultado = validar_mensagem(
        _resposta_valida(trecho_site="fisioterapia deportiva"), _ENTRADA_COM_TEXTO_SITE, config=_CONFIG
    )
    assert resultado.valido, resultado.motivos


# --- nome do negócio fora das mensagens (decisão do diretor, 24/09/2026, --
# quarta rodada): entrada não carrega mais "nome" -- nome_negocio é passado
# à parte, e a checagem é opcional (omitido, não roda).


def test_mensagem_com_o_nome_original_do_negocio_falha():
    resultado = validar_mensagem(
        _resposta_valida("Vi que Clínica Ejemplo tarda en cargar en el móvil. ¿Le envío lo que vi?"),
        _ENTRADA, config=_CONFIG, nome_negocio="Clínica Ejemplo",
    )
    assert not resultado.valido
    assert any("nome do negócio" in m for m in resultado.motivos)


def test_mensagem_com_o_nome_comercial_limpo_tambem_falha():
    """O corte de nome_comercial_limpo também é checado -- não só o nome
    bruto do lead."""
    resultado = validar_mensagem(
        _resposta_valida("Vi que Fisioficticia Salud tarda en cargar. ¿Le envío lo que vi?"),
        _ENTRADA, config=_CONFIG, nome_negocio="Fisioficticia Salud - Fisioterapia en Alicante",
    )
    assert not resultado.valido
    assert any("nome do negócio" in m for m in resultado.motivos)


def test_mensagem_sem_o_nome_do_negocio_passa():
    resultado = validar_mensagem(_resposta_valida(), _ENTRADA, config=_CONFIG, nome_negocio="Clínica Ejemplo")
    assert resultado.valido, resultado.motivos


def test_nome_do_negocio_omitido_nao_aplica_a_regra():
    """Controle: uma unidade que testa outra regra não precisa fornecer
    nome_negocio -- mesmo princípio das checagens 8 e 9 (chave ausente não
    aplica a regra)."""
    resultado = validar_mensagem(
        _resposta_valida("Vi que Clínica Ejemplo tarda en cargar. ¿Le envío lo que vi?"), _ENTRADA, config=_CONFIG,
    )
    assert resultado.valido, resultado.motivos


def test_nome_do_negocio_ignora_maiuscula_e_acento():
    resultado = validar_mensagem(
        _resposta_valida("Vi que CLINICA EJEMPLO tarda en cargar. ¿Le envío lo que vi?"),
        _ENTRADA, config=_CONFIG, nome_negocio="Clínica Ejemplo",
    )
    assert not resultado.valido
    assert any("nome do negócio" in m for m in resultado.motivos)


# --- falso positivo: nome genérico (decisão do diretor, 25/09/2026) --------
#
# Caso real: lead "Psicólogo en Alicante - Pedro Ficticio" -- nome limpo
# "Psicólogo en Alicante", só palavras genéricas (nicho + cidade da busca +
# conectoras). O modelo de poucas_avaliacoes diz legitimamente "quien busca
# psicólogo en Alicante", e a mensagem era rejeitada por engano.


def test_nome_generico_formado_so_por_nicho_e_cidade_passa():
    resultado = validar_mensagem(
        _resposta_valida("Vi que quien busca psicólogo en Alicante compara antes. ¿Le envío lo que vi?"),
        _ENTRADA, config=_CONFIG, nome_negocio="Psicólogo en Alicante - Pedro Ficticio",
        palavras_genericas_nome=["Psicólogo", "Alicante"],
    )
    assert resultado.valido, resultado.motivos


def test_nome_com_palavra_propria_continua_rejeitando_mesmo_com_genericas():
    """Controle central: "Clínica Ficticia Nueve" tem uma palavra própria ("Nueve") --
    mesmo fornecendo nicho/cidade genéricos, a checagem continua rejeitando."""
    resultado = validar_mensagem(
        _resposta_valida("Vi que Clínica Ficticia Nueve tarda en cargar. ¿Le envío lo que vi?"),
        _ENTRADA, config=_CONFIG, nome_negocio="Clínica Ficticia Nueve",
        palavras_genericas_nome=["Fisioterapia", "Alicante"],
    )
    assert not resultado.valido
    assert any("nome do negócio" in m for m in resultado.motivos)


def test_nome_generico_sem_palavras_genericas_fornecidas_continua_rejeitando():
    """Controle: sem o contexto de nicho/cidade (palavras_genericas_nome
    omitido), só as conectoras fixas são genéricas -- "psicólogo" e
    "alicante" não bastam sozinhas para isentar a checagem."""
    resultado = validar_mensagem(
        _resposta_valida("Vi que quien busca psicólogo en Alicante compara antes. ¿Le envío lo que vi?"),
        _ENTRADA, config=_CONFIG, nome_negocio="Psicólogo en Alicante - Pedro Ficticio",
    )
    assert not resultado.valido
    assert any("nome do negócio" in m for m in resultado.motivos)


def test_nome_generico_ignora_maiuscula_e_acento_nas_palavras_genericas():
    resultado = validar_mensagem(
        _resposta_valida("Vi que quien busca PSICOLOGO EN ALICANTE compara antes. ¿Le envío lo que vi?"),
        _ENTRADA, config=_CONFIG, nome_negocio="Psicólogo en Alicante",
        palavras_genericas_nome=["psicólogo", "ALICANTE"],
    )
    assert resultado.valido, resultado.motivos


# --- detalhe pessoal proibido em trecho_site (decisão do diretor, --------
# 24/09/2026, quarta rodada: "Vi en su web que está diplomada en
# Fisioterapia en la Escuela Universitaria Ficticia" -- trecho_site só pode
# ser serviço, especialidade, tratamento ou público atendido.)

_CONFIG_COM_TERMOS_PESSOAIS = {
    **_CONFIG,
    "termos_proibidos_trecho_site": [
        "diplomad", "licenciad", "graduad", "formó", "formación", "máster",
        "universidad", "universitaria", "doctorado", "colegiad", "años de experiencia", "premio",
    ],
}


def test_trecho_site_com_detalhe_pessoal_diploma_falha():
    entrada = {**_ENTRADA, "texto_site": "Está diplomada en Fisioterapia en la Escuela Universitaria Ficticia."}
    resultado = validar_mensagem(
        _resposta_valida(trecho_site="diplomada en Fisioterapia en la Escuela Universitaria Ficticia"),
        entrada, config=_CONFIG_COM_TERMOS_PESSOAIS,
    )
    assert not resultado.valido
    assert any("detalhe pessoal" in m for m in resultado.motivos)


def test_trecho_site_com_servico_sem_detalhe_pessoal_passa():
    entrada = {**_ENTRADA, "texto_site": "Ofrecemos fisioterapia deportiva y rehabilitación."}
    resultado = validar_mensagem(
        _resposta_valida(trecho_site="fisioterapia deportiva"), entrada, config=_CONFIG_COM_TERMOS_PESSOAIS,
    )
    assert resultado.valido, resultado.motivos


def test_termos_proibidos_trecho_site_ignora_maiuscula_e_acento():
    """A config lista "máster" (com acento); o termo tem que ser pego mesmo
    quando o trecho citado vem sem acento e em maiúsculas."""
    entrada = {**_ENTRADA, "texto_site": "Tiene MASTER en fisioterapia deportiva."}
    resultado = validar_mensagem(
        _resposta_valida(trecho_site="MASTER en fisioterapia deportiva"), entrada, config=_CONFIG_COM_TERMOS_PESSOAIS,
    )
    assert not resultado.valido
    assert any("detalhe pessoal" in m for m in resultado.motivos)


def test_termos_proibidos_trecho_site_ausente_da_config_nao_aplica_a_regra():
    """Controle: config sem a chave não rejeita -- mesmo princípio das
    checagens 8 e 9."""
    entrada = {**_ENTRADA, "texto_site": "Está diplomada en Fisioterapia en la Escuela Universitaria Ficticia."}
    resultado = validar_mensagem(
        _resposta_valida(trecho_site="diplomada en Fisioterapia en la Escuela Universitaria Ficticia"),
        entrada, config=_CONFIG,
    )
    assert resultado.valido, resultado.motivos


def test_carregar_config_le_a_lista_de_termos_pessoais_do_arquivo_real():
    """Controle: o arquivo real de configuração tem a lista nova (v4/quarta
    rodada)."""
    config = carregar_config()
    assert "termos_proibidos_trecho_site" in config
    assert "universidad" in config["termos_proibidos_trecho_site"]


def test_carregar_config_le_as_frases_de_inferencia_indevida_do_arquivo_real():
    """Controle: o arquivo real tem as frases novas da sexta rodada
    (24/09/2026, MVP de mensagem por modelo fixo) -- o Google arredonda a
    nota, então a mensagem nunca pode inferir "todas"/"quase todas" as
    avaliações a partir da média."""
    config = carregar_config()
    assert "todas las reseñas son de 5 estrellas" in config["termos_proibidos"]
    assert "casi todas" in config["termos_proibidos"]
