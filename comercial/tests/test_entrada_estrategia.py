"""Testes de entrada_estrategia.py — só fato medido entra na entrada da
chamada de LLM (Etapa E2). Cada teste isola UM campo condicional para provar
a regra de inclusão/omissão isoladamente."""

import json

import pytest

import templates_direta
from contrato_loader import LeadQualificado
from entrada_estrategia import construir_entrada as _construir_entrada_real

# Limiares fixos aqui (nao dependem do config/entrada_estrategia.json real) --
# assim um ajuste futuro no arquivo real nao muda o resultado destes testes,
# que testam a REGRA de corte, nao o valor vigente do limiar.
_LIMIARES = {"nota_google_minima": 4.5, "avaliacoes_minimas": 15}


def construir_entrada(lead, **kwargs):
    kwargs.setdefault("limiares_reputacao", _LIMIARES)
    return _construir_entrada_real(lead, **kwargs)


def _lead(*, nicho="Fisioterapia", cidade="Madrid", nota_estado="CONFIRMADO_PRESENTE",
          nota_valor=4.5, avaliacoes_estado="CONFIRMADO_PRESENTE", avaliacoes_valor=27,
          whatsapp=True, problemas=None, psi=None, texto_site=None, com_chave_texto_site=True):
    if problemas is None:
        problemas = [
            {
                "tipo": "sem_contato_visivel",
                "evidencia": "nenhum telefone visível em nenhum dos dois dispositivos",
                "medicao": "site_renderizado",
                "coletado_em": "2026-09-20T10:00:00Z",
            }
        ]
    dados = {
        "place_id": "abc123",
        "identidade": {
            "nome": "Clínica Ejemplo",
            "nicho": nicho,
            "cidade": cidade,
            "endereco": None,
            "google_maps_url": None,
        },
        "contato": {"whatsapp_apto": whatsapp},
        "reputacao": {
            "nota_google": {"valor": nota_valor, "estado": nota_estado},
            "review_count": {"valor": avaliacoes_valor, "estado": avaliacoes_estado},
        },
        "problema_vendavel": problemas,
        "psi": psi,
    }
    if com_chave_texto_site:
        dados["texto_site"] = texto_site
    return LeadQualificado(dados)


def test_entrada_completa_traz_todos_os_campos():
    """`apresentacao=""` explícito -- não depende do conteúdo atual de
    config/remetente_apresentacao.json (item 7, decisão do diretor,
    24/09/2026: o arquivo real passou a ter conteúdo)."""
    entrada = construir_entrada(_lead(), apresentacao="")
    assert entrada == {
        "nicho": "Fisioterapia",
        "cidade": "Madrid",
        "problemas_vendaveis": [
            {
                "tipo": "sem_contato_visivel",
                "evidencia": "nenhum telefone visível em nenhum dos dois dispositivos",
                "medicao": "site_renderizado",
            }
        ],
        "nota_google": 4.5,
        "avaliacoes_google": 27,
        "tem_whatsapp": True,
    }


# --- nome do negócio fora da entrada (decisão do diretor, 24/09/2026, -----
# quarta rodada): removidos os testes que provavam o corte de
# nome_comercial_limpo DENTRO da entrada (test_nome_com_subtitulo_do_google_
# maps_entra_cortado, test_nome_sem_subtitulo_entra_igual) -- o campo "nome"
# não entra mais na entrada nenhuma, com ou sem subtítulo do Maps.
# nome_comercial_limpo continua existindo, mas só para a checagem do
# validador (validador_mensagem.py) -- testada lá, não aqui.


def test_nome_nunca_entra_na_entrada_com_ou_sem_subtitulo_do_maps():
    for nome in ("Clínica Ejemplo", "Fisioficticia Salud - Fisioterapia en Alicante"):
        dados = {
            "place_id": "abc123",
            "identidade": {
                "nome": nome, "nicho": None, "cidade": None, "endereco": None, "google_maps_url": None,
            },
            "contato": {"whatsapp_apto": True},
            "reputacao": {
                "nota_google": {"valor": None, "estado": "NAO_VERIFICADO"},
                "review_count": {"valor": None, "estado": "NAO_VERIFICADO"},
            },
            "problema_vendavel": [],
            "psi": None,
            "texto_site": None,
        }
        entrada = construir_entrada(LeadQualificado(dados))
        assert "nome" not in entrada


def test_coletado_em_nunca_entra_na_entrada():
    entrada = construir_entrada(_lead())
    assert "coletado_em" not in entrada["problemas_vendaveis"][0]


def test_nicho_ausente_e_omitido_nunca_vira_null():
    entrada = construir_entrada(_lead(nicho=None))
    assert "nicho" not in entrada


def test_cidade_ausente_e_omitida_cenario_dp12():
    """DP-12: cidade costuma vir vazia na base real. Regra aprovada: nesse
    caso ela NÃO entra na entrada."""
    entrada = construir_entrada(_lead(cidade=None))
    assert "cidade" not in entrada


def test_nota_google_nao_verificado_e_omitida():
    """Controle negativo: NAO_VERIFICADO não é 'há uma nota' -- nunca inventa
    um valor para um fato não confirmado."""
    entrada = construir_entrada(_lead(nota_estado="NAO_VERIFICADO", nota_valor=None))
    assert "nota_google" not in entrada


def test_nota_google_confirmado_ausente_e_omitida():
    entrada = construir_entrada(_lead(nota_estado="CONFIRMADO_AUSENTE", nota_valor=None))
    assert "nota_google" not in entrada


def test_avaliacoes_google_nao_verificado_e_omitida():
    entrada = construir_entrada(_lead(avaliacoes_estado="NAO_VERIFICADO", avaliacoes_valor=None))
    assert "avaliacoes_google" not in entrada


# --- Limiar do elogio (decisão do diretor, 24/09/2026) --------------------
#
# nota_google/avaliacoes_google só entram JUNTOS, e só quando os dois batem
# o limiar -- nunca um sem o outro, nunca abaixo do corte.


def test_elogio_liberado_quando_os_dois_batem_o_limiar():
    entrada = construir_entrada(_lead(nota_valor=4.5, avaliacoes_valor=15))
    assert entrada["nota_google"] == 4.5
    assert entrada["avaliacoes_google"] == 15


def test_elogio_omite_os_dois_quando_nota_fica_abaixo_do_limiar():
    entrada = construir_entrada(_lead(nota_valor=4.4, avaliacoes_valor=27))
    assert "nota_google" not in entrada
    assert "avaliacoes_google" not in entrada


def test_elogio_omite_os_dois_quando_avaliacoes_fica_abaixo_do_limiar():
    """Nota ótima não basta -- os dois têm que bater, ou nenhum entra."""
    entrada = construir_entrada(_lead(nota_valor=5.0, avaliacoes_valor=14))
    assert "nota_google" not in entrada
    assert "avaliacoes_google" not in entrada


def test_elogio_no_limiar_exato_e_liberado():
    """Controle de borda: `>=`, não `>` -- exatamente no corte já libera."""
    entrada = construir_entrada(_lead(nota_valor=4.5, avaliacoes_valor=15))
    assert "nota_google" in entrada
    assert "avaliacoes_google" in entrada


def test_elogio_um_ponto_abaixo_do_limiar_ja_omite():
    entrada = construir_entrada(_lead(nota_valor=4.49, avaliacoes_valor=15))
    assert "nota_google" not in entrada


def test_tem_elogio_reputacao_funcao_usada_pelo_pipeline():
    from entrada_estrategia import tem_elogio_reputacao

    assert tem_elogio_reputacao(_lead(nota_valor=4.8, avaliacoes_valor=30), _LIMIARES) is True
    assert tem_elogio_reputacao(_lead(nota_valor=3.0, avaliacoes_valor=30), _LIMIARES) is False
    assert (
        tem_elogio_reputacao(
            _lead(nota_estado="NAO_VERIFICADO", nota_valor=None, avaliacoes_valor=30), _LIMIARES
        )
        is False
    )


def test_carregar_limiares_reputacao_le_o_arquivo_real():
    """Controle: o arquivo real de configuração tem o formato exigido."""
    from entrada_estrategia import carregar_limiares_reputacao

    limiares = carregar_limiares_reputacao()
    assert "nota_google_minima" in limiares
    assert "avaliacoes_minimas" in limiares


def test_carregar_limiares_reputacao_arquivo_ausente_levanta_erro_claro(tmp_path):
    from entrada_estrategia import ConfigEntradaInvalidaError, carregar_limiares_reputacao

    with pytest.raises(ConfigEntradaInvalidaError, match="não encontrada"):
        carregar_limiares_reputacao(tmp_path / "nao-existe.json")


def test_carregar_limiares_reputacao_sem_chaves_exigidas_levanta_erro_claro(tmp_path):
    from entrada_estrategia import ConfigEntradaInvalidaError, carregar_limiares_reputacao

    caminho = tmp_path / "limiares.json"
    caminho.write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigEntradaInvalidaError):
        carregar_limiares_reputacao(caminho)


def test_tem_whatsapp_sempre_presente_mesmo_falso():
    """Controle: tem_whatsapp é bool simples (não CampoEvidencia) -- sempre
    presente, inclusive quando False (diferente dos campos condicionais)."""
    entrada = construir_entrada(_lead(whatsapp=False))
    assert entrada["tem_whatsapp"] is False


def test_varios_problemas_vendaveis_preservam_ordem_e_conteudo():
    problemas = [
        {"tipo": "fora_do_ar", "evidencia": "erro 503", "medicao": "site_renderizado", "coletado_em": None},
        {"tipo": "sem_contato_visivel", "evidencia": "nenhum telefone visível", "medicao": "site_renderizado", "coletado_em": None},
    ]
    entrada = construir_entrada(_lead(problemas=problemas))
    assert entrada["problemas_vendaveis"] == [
        {"tipo": "fora_do_ar", "evidencia": "erro 503", "medicao": "site_renderizado"},
        {"tipo": "sem_contato_visivel", "evidencia": "nenhum telefone visível", "medicao": "site_renderizado"},
    ]


# --- lento_no_celular: defeito achado em produção 24/09/2026 -------------
#
# A evidência real (formato copiado do lote de 23/09,
# EQC/pipeline/qualificador-output/, nome fictício) é texto de máquina:
# "psi.lcp_ms=8076 > 4000". Ela carrega o corte técnico (4000) e o valor em
# milissegundos -- nenhum dos dois é o que a mensagem deve citar. A entrada
# passa a carregar só `segundos_carga_celular` (derivado por programa) para
# esse tipo, nunca a string crua.

_PROBLEMA_LENTO = [
    {
        "tipo": "lento_no_celular",
        "evidencia": "psi.lcp_ms=8076 > 4000",
        "medicao": "psi",
        "coletado_em": "2026-09-08T07:38:18+00:00",
    }
]

_PSI_MEDIDO = {
    "estado": "CONFIRMADO_PRESENTE",
    "motivo": None,
    "medido_em": "2026-09-08T07:38:18+00:00",
    "estrategia": "mobile",
    "performance_score": 63,
    "lcp_ms": 8076,
    "cls": 0,
    "tbt_ms": 36,
    "origem": "lab",
    "falha_transiente": False,
    "tentativas": 1,
    "rodadas": 1,
}


def test_lento_no_celular_nunca_manda_a_string_crua():
    """A string "psi.lcp_ms=8076 > 4000" nunca atravessa para a entrada --
    nem o corte 4000, nem os milissegundos."""
    entrada = construir_entrada(_lead(problemas=_PROBLEMA_LENTO, psi=_PSI_MEDIDO))
    item = entrada["problemas_vendaveis"][0]
    assert "evidencia" not in item
    assert "4000" not in str(item)
    assert "8076" not in str(item)


def test_lento_no_celular_deriva_segundos_da_medicao_psi_quando_disponivel():
    """Fonte preferida: lead['psi']['lcp_ms'], quando confirmada -- não a
    string de evidência."""
    entrada = construir_entrada(_lead(problemas=_PROBLEMA_LENTO, psi=_PSI_MEDIDO))
    item = entrada["problemas_vendaveis"][0]
    assert item["segundos_carga_celular"] == 8  # round(8076 / 1000)
    assert item["tipo"] == "lento_no_celular"
    assert item["medicao"] == "psi"


def test_lento_no_celular_psi_confirmado_vence_a_string_quando_divergem():
    """Prova real de preferência (não só coincidência de número igual nos
    dois lugares): quando `lead['psi']['lcp_ms']` diverge do que está na
    string de evidência (ex.: string desatualizada de uma medição anterior),
    a medição confirmada é quem decide -- nunca a string."""
    psi_diferente = {**_PSI_MEDIDO, "lcp_ms": 12000}
    entrada = construir_entrada(_lead(problemas=_PROBLEMA_LENTO, psi=psi_diferente))
    item = entrada["problemas_vendaveis"][0]
    assert item["segundos_carga_celular"] == 12  # da medição (12000), não dos 8076 da string


def test_lento_no_celular_cai_para_regex_na_string_quando_psi_nao_disponivel():
    """Controle: sem lead['psi'] confirmado (None, ou NAO_VERIFICADO), a
    função ainda deriva o número, mas da string de evidência via regex --
    nunca inventa e nunca deixa a string crua passar."""
    entrada = construir_entrada(_lead(problemas=_PROBLEMA_LENTO, psi=None))
    item = entrada["problemas_vendaveis"][0]
    assert item["segundos_carga_celular"] == 8
    assert "evidencia" not in item


def test_lento_no_celular_psi_nao_verificado_tambem_cai_para_regex():
    psi_nao_verificado = {"estado": "NAO_VERIFICADO", "motivo": "ainda não medido", "medido_em": None}
    entrada = construir_entrada(_lead(problemas=_PROBLEMA_LENTO, psi=psi_nao_verificado))
    item = entrada["problemas_vendaveis"][0]
    assert item["segundos_carga_celular"] == 8


def test_lento_no_celular_sem_nenhuma_fonte_de_numero_nao_inventa():
    """Controle negativo: nem psi confirmado, nem número na string --
    segundos_carga_celular simplesmente não aparece, nunca um valor
    inventado."""
    problema_sem_numero = [
        {"tipo": "lento_no_celular", "evidencia": "medição indisponível", "medicao": "psi", "coletado_em": None}
    ]
    entrada = construir_entrada(_lead(problemas=problema_sem_numero, psi=None))
    item = entrada["problemas_vendaveis"][0]
    assert "segundos_carga_celular" not in item
    assert "evidencia" not in item


def test_lento_no_celular_arredonda_para_o_inteiro_mais_proximo():
    problema = [{"tipo": "lento_no_celular", "evidencia": "psi.lcp_ms=7500 > 4000", "medicao": "psi", "coletado_em": None}]
    entrada = construir_entrada(_lead(problemas=problema, psi=None))
    assert entrada["problemas_vendaveis"][0]["segundos_carga_celular"] == round(7500 / 1000)


# --- apresentacao (prompt v3, remetente_apresentacao.json) ----------------

def test_apresentacao_carregada_vazia_de_arquivo_e_omitida(tmp_path):
    """Controle: uma config de apresentação vazia (não a real -- item 7,
    24/09/2026: o arquivo real passou a ter conteúdo) não inclui a chave.
    Usa `tmp_path`, não o arquivo real, para não depender do que está nele
    hoje."""
    caminho = tmp_path / "apresentacao_vazia.json"
    caminho.write_text(json.dumps({"apresentacao": ""}), encoding="utf-8")
    entrada = construir_entrada(_lead(), apresentacao=templates_direta.carregar_apresentacao(caminho))
    assert "apresentacao" not in entrada


def test_apresentacao_explicita_entra_na_entrada():
    entrada = construir_entrada(_lead(), apresentacao=" Somos ByteConsult.")
    assert entrada["apresentacao"] == " Somos ByteConsult."


def test_apresentacao_string_vazia_explicita_e_omitida():
    entrada = construir_entrada(_lead(), apresentacao="")
    assert "apresentacao" not in entrada


# --- texto_site (contrato 2.1.0) -------------------------------------------

def test_texto_site_confirmado_presente_entra_na_entrada():
    entrada = construir_entrada(_lead(texto_site={"estado": "CONFIRMADO_PRESENTE", "texto": "Somos una clínica de fisioterapia en Madrid.", "chars_originais": 45, "truncado": False, "dispositivo": "mobile", "coletado_em": "2026-09-24T10:00:00Z"}))
    assert entrada["texto_site"] == "Somos una clínica de fisioterapia en Madrid."


def test_texto_site_nao_verificado_e_omitido():
    """Controle negativo: NAO_VERIFICADO não é 'há texto', é 'não sabemos' --
    mesmo princípio de nota_google/avaliacoes_google."""
    entrada = construir_entrada(_lead(texto_site={"estado": "NAO_VERIFICADO", "motivo": "x", "medido_em": None}))
    assert "texto_site" not in entrada


def test_texto_site_estado_diferente_de_confirmado_presente_e_omitido_mesmo_com_texto():
    """Prova de não-vacuidade da checagem de estado: um dict com "texto"
    preenchido mas estado != CONFIRMADO_PRESENTE (forma que não deveria
    existir de verdade, mas prova que o código checa o estado, não só a
    presença da chave "texto")."""
    entrada = construir_entrada(_lead(texto_site={"estado": "NAO_VERIFICADO", "texto": "não deveria vazar"}))
    assert "texto_site" not in entrada


def test_texto_site_null_e_omitido():
    entrada = construir_entrada(_lead(texto_site=None))
    assert "texto_site" not in entrada


def test_texto_site_chave_ausente_lote_anterior_a_2_1_0_e_omitido_sem_quebrar():
    """Controle: lote 2.0.0 nem tem a chave -- não pode levantar KeyError."""
    entrada = construir_entrada(_lead(com_chave_texto_site=False))
    assert "texto_site" not in entrada


def test_outros_tipos_de_problema_continuam_com_evidencia_normalmente():
    """O defeito e o tratamento especial são só de lento_no_celular -- os
    demais tipos não mudam."""
    problemas = [
        {"tipo": "fora_do_ar", "evidencia": "desktop: erro_tipo=timeout", "medicao": "site_renderizado", "coletado_em": None}
    ]
    entrada = construir_entrada(_lead(problemas=problemas, psi=None))
    assert entrada["problemas_vendaveis"][0] == {
        "tipo": "fora_do_ar",
        "evidencia": "desktop: erro_tipo=timeout",
        "medicao": "site_renderizado",
    }
