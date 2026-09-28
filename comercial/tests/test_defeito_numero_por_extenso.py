"""Reprodução do defeito achado pela supervisão em produção (24/09/2026,
contra o lote real de 23/09) e prova de que está corrigido.

Evidência real (formato copiado de
`EQC/pipeline/qualificador-output/leads_qualificados_20260923-160009_v2.0.0.json`,
nome de negócio fictício — nenhum dado de lead entra no repositório):
`"psi.lcp_ms=8076 > 4000"`. Nos 37 de 38 leads da nata desse lote que são
`lento_no_celular`, este era o formato universal.

Antes da correção:
- `"tarda unos 8 segundos"` -> REJEITADA (o "8" não batia com nenhum número
  da entrada, que só tinha "8076" e "4000" -- sendo verdade, o número certo).
- `"tarda 8076 ms"` -> aceita, mas citando texto de máquina.
- `"casi diez segundos"` -> ACEITA, sendo exagero (37% de erro sobre os 8
  segundos reais) -- número por extenso escapava da checagem de
  número-fora-da-entrada, que só contava dígito (`\\d+`).

Depois (este teste prova): a entrada carrega só `segundos_carga_celular: 8`
(nunca a string crua, nunca o corte 4000); o validador reconhece número por
extenso em espanhol."""

from contrato_loader import LeadQualificado
from entrada_estrategia import construir_entrada
from validador_mensagem import carregar_config, validar_mensagem

_EVIDENCIA_REAL = "psi.lcp_ms=8076 > 4000"  # formato real, lead fictício


def _lead_lento_no_celular():
    return LeadQualificado(
        {
            "place_id": "fixture-nao-e-lead-real",
            "identidade": {
                "nome": "Clínica Ejemplo",
                "nicho": "Fisioterapia",
                "cidade": None,
                "endereco": None,
                "google_maps_url": None,
            },
            "contato": {"whatsapp_apto": True},
            "reputacao": {
                "nota_google": {"valor": None, "estado": "NAO_VERIFICADO"},
                "review_count": {"valor": None, "estado": "NAO_VERIFICADO"},
            },
            "problema_vendavel": [
                {
                    "tipo": "lento_no_celular",
                    "evidencia": _EVIDENCIA_REAL,
                    "medicao": "psi",
                    "coletado_em": "2026-09-08T07:38:18+00:00",
                }
            ],
            "psi": None,  # força o caminho de regex-sobre-a-string (mesmo resultado que via psi confirmado)
        }
    )


def _resposta(mensagem: str) -> str:
    import json

    return json.dumps(
        {
            "estrategia": "Abrir con la lentitud móvil, ya confirmada.",
            "canal_sugerido": "whatsapp",
            "mensagem_1": mensagem,
            "fato_usado": "lento_no_celular",
        }
    )


def test_entrada_real_nunca_carrega_o_corte_nem_os_milissegundos():
    entrada = construir_entrada(_lead_lento_no_celular())
    item = entrada["problemas_vendaveis"][0]
    assert item == {"tipo": "lento_no_celular", "medicao": "psi", "segundos_carga_celular": 8}


def test_unos_8_segundos_passa_com_lcp_8076():
    """Antes do defeito corrigido, isto era rejeitado por engano -- o número
    verdadeiro (8) não batia com o que a entrada carregava (8076, 4000).
    Saudação "Hola, buenas" acrescentada em 24/09/2026 (decisão do diretor,
    segunda rodada) -- config real passou a exigi-la."""
    entrada = construir_entrada(_lead_lento_no_celular())
    resultado = validar_mensagem(
        _resposta("Hola, buenas. Vi que su web tarda unos 8 segundos en cargar en el móvil. ¿Le envío lo que vi?"),
        entrada,
        config=carregar_config(),
    )
    assert resultado.valido, resultado.motivos


def test_casi_diez_segundos_falha_numero_por_extenso_e_pego():
    """O exagero central do defeito: "diez" (10) não é "8" -- e agora o
    validador reconhece o número por extenso para fazer essa comparação."""
    entrada = construir_entrada(_lead_lento_no_celular())
    resultado = validar_mensagem(
        _resposta("Vi que su web tarda casi diez segundos en cargar en el móvil. ¿Le envío lo que vi?"),
        entrada,
        config=carregar_config(),
    )
    assert not resultado.valido
    assert any("número fora da entrada" in m for m in resultado.motivos)


def test_8076_ms_agora_falha_porque_o_numero_tecnico_nao_esta_mais_na_entrada():
    """Decisão desta correção: a entrada não carrega mais "8076" (só
    "segundos_carga_celular": 8) -- então citar "8076 ms" agora é citar um
    número que não está na entrada, e passa a ser rejeitado. Antes do
    defeito ser corrigido isso era aceito (a string crua vazava para a
    entrada); o ganho aqui é duplo: nunca mais nem o valor errado (extenso)
    nem o texto de máquina (ms) chegam à mensagem."""
    entrada = construir_entrada(_lead_lento_no_celular())
    resultado = validar_mensagem(
        _resposta("Vi que su web tarda 8076 ms en cargar en el móvil. ¿Le envío lo que vi?"),
        entrada,
        config=carregar_config(),
    )
    assert not resultado.valido
    assert any("número fora da entrada" in m for m in resultado.motivos)


def test_ocho_segundos_por_extenso_tambem_passa():
    """Controle simétrico: o número certo (8) por extenso também deve
    passar -- a checagem por extenso não é uma lista de bloqueio, é
    comparação de valor."""
    entrada = construir_entrada(_lead_lento_no_celular())
    resultado = validar_mensagem(
        _resposta("Hola, buenas. Vi que su web tarda ocho segundos en cargar en el móvil. ¿Le envío lo que vi?"),
        entrada,
        config=carregar_config(),
    )
    assert resultado.valido, resultado.motivos
