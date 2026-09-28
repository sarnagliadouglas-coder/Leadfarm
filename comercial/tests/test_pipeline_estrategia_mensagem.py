"""Testes de pipeline_estrategia_mensagem.py — NENHUM faz chamada real à
API: todo teste injeta um cliente simulado. Toda saída de arquivo vai para
tmp_path, nunca para comercial/_mensagens real (o guardião de pastas de
produção do conftest.py cobre essa pasta como rede extra)."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import llm_config
from contrato_loader import LeadQualificado
from pipeline_estrategia_mensagem import (
    PastaDaRodadaJaExisteError,
    criar_pasta_rodada,
    escrever_saida_rodada,
    processar_lead,
    processar_lote,
)
from registro_consumo import resumo_rodada

_TABELA_PRECOS = {
    "modelo_default": "modelo-de-teste",
    "precos_por_modelo": {"modelo-de-teste": {"entrada": 2.0, "saida": 10.0, "cache_escrita": 2.5, "cache_leitura": 0.2}},
}

_CONFIG_VALIDACAO = {
    "max_palavras_mensagem_1": 80,
    "simbolos_moeda": ["€"],
    "palavras_preco": ["precio", "tarifa"],
    "marcas_informais_es": ["tú", "tu", "te", "tienes", "puedes"],
}

_PROMPT_SISTEMA = "Você é um redator de teste. Devolva só o JSON pedido."


_LIMIARES_TESTE = {"nota_google_minima": 4.5, "avaliacoes_minimas": 15}


def _lead(place_id="abc123", avaliacoes=27, nota=4.5, problemas=None, texto_site=None):
    if problemas is None:
        problemas = [
            {
                "tipo": "lento_no_celular",
                "evidencia": "psi.lcp_ms=8076 > 4000",
                "medicao": "psi",
                "coletado_em": "2026-09-20T10:00:00Z",
            }
        ]
    return LeadQualificado(
        {
            "place_id": place_id,
            "identidade": {
                "nome": "Clínica Ejemplo",
                "nicho": "Fisioterapia",
                "cidade": None,
                "endereco": None,
                "google_maps_url": None,
            },
            "contato": {"whatsapp_apto": True},
            "reputacao": {
                "nota_google": {"valor": nota, "estado": "CONFIRMADO_PRESENTE"},
                "review_count": {"valor": avaliacoes, "estado": "CONFIRMADO_PRESENTE"},
            },
            "problema_vendavel": problemas,
            "psi": None,
            "texto_site": (
                {"estado": "CONFIRMADO_PRESENTE", "texto": texto_site, "chars_originais": len(texto_site),
                 "truncado": False, "dispositivo": "mobile", "coletado_em": "2026-09-20T10:00:00Z"}
                if texto_site else None
            ),
        }
    )


class _ContentBlock:
    def __init__(self, texto):
        self.type = "text"
        self.text = texto


class _UsageFalso:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _RespostaFalsa:
    def __init__(self, texto):
        self.content = [_ContentBlock(texto)]
        self.usage = _UsageFalso()


class _ClienteFalso:
    """Devolve as respostas de `roteiro`, uma por chamada, na ordem. Guarda
    cada `kwargs` recebido para os testes conferirem o que foi enviado."""

    def __init__(self, roteiro):
        self._roteiro = list(roteiro)
        self.chamadas = []

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            def create(self, **kwargs):
                self._outer.chamadas.append(kwargs)
                return self._outer._roteiro.pop(0)

        self.messages = _Messages(self)


def _resposta_valida_json(mensagem="Hola, buenas. Vi que su web tarda en el móvil. ¿Le envío lo que vi?", trecho_site=None):
    dados = {
        "estrategia": "Abrir con la lentitud móvil.",
        "canal_sugerido": "whatsapp",
        "mensagem_1": mensagem,
        "fato_usado": "lento_no_celular",
    }
    if trecho_site is not None:
        dados["trecho_site"] = trecho_site
    return json.dumps(dados)


@pytest.fixture(autouse=True)
def _chave_de_teste(monkeypatch, tmp_path):
    import env_loader

    monkeypatch.setattr(env_loader, "_ENV_PATH", tmp_path / "nao-existe.env")
    monkeypatch.setenv(llm_config.ENV_API_KEY, "chave-de-teste-fake")
    monkeypatch.delenv(llm_config.ENV_MODEL, raising=False)


def test_processar_lead_valido_na_primeira_tentativa(tmp_path):
    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json())])
    log = tmp_path / "consumo.jsonl"

    resultado = processar_lead(
        _lead(),
        lead_id="abc123",
        prompt_sistema=_PROMPT_SISTEMA,
        cliente=cliente,
        modelo="modelo-de-teste",
        tabela_precos=_TABELA_PRECOS,
        config_validacao=_CONFIG_VALIDACAO,
        caminho_log_consumo=log,
    )

    assert resultado.status == "ok"
    assert resultado.tentativas == 1
    assert resultado.mensagem_1 == "Hola, buenas. Vi que su web tarda en el móvil. ¿Le envío lo que vi?"
    assert resultado.motivo_rejeicao is None
    assert len(cliente.chamadas) == 1

    resumo = resumo_rodada(log)
    assert resumo["numero_chamadas"] == 1

    # com_elogio: nota 4,5 e 27 avaliações batem o limiar (4,5 / 15)
    assert resultado.com_elogio == "sim"
    # nenhum problema fora_do_ar no lead padrão
    assert resultado.conferir_antes_de_enviar == "não"


def test_processar_lead_propaga_trecho_site_ate_o_resultado(tmp_path):
    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json(trecho_site="fisioterapia deportiva"))])
    resultado = processar_lead(
        _lead(texto_site="Ofrecemos fisioterapia deportiva y rehabilitación en Sevilla."),
        lead_id="abc123",
        prompt_sistema=_PROMPT_SISTEMA,
        cliente=cliente,
        modelo="modelo-de-teste",
        tabela_precos=_TABELA_PRECOS,
        config_validacao=_CONFIG_VALIDACAO,
        caminho_log_consumo=tmp_path / "consumo.jsonl",
    )
    assert resultado.trecho_site == "fisioterapia deportiva"


def test_processar_lead_registra_o_modelo_efetivamente_usado(tmp_path):
    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json())])
    resultado = processar_lead(
        _lead(),
        lead_id="abc123",
        prompt_sistema=_PROMPT_SISTEMA,
        cliente=cliente,
        modelo="modelo-de-teste",
        tabela_precos=_TABELA_PRECOS,
        config_validacao=_CONFIG_VALIDACAO,
        caminho_log_consumo=tmp_path / "consumo.jsonl",
    )
    assert resultado.modelo == "modelo-de-teste"


def test_processar_lead_registra_modelo_mesmo_quando_rejeitado(tmp_path):
    invalida = _resposta_valida_json("Esto no termina en pregunta.")
    cliente = _ClienteFalso([_RespostaFalsa(invalida), _RespostaFalsa(invalida)])
    resultado = processar_lead(
        _lead(),
        lead_id="abc123",
        prompt_sistema=_PROMPT_SISTEMA,
        cliente=cliente,
        modelo="modelo-de-teste",
        tabela_precos=_TABELA_PRECOS,
        config_validacao=_CONFIG_VALIDACAO,
        caminho_log_consumo=tmp_path / "consumo.jsonl",
    )
    assert resultado.status == "rejeitado_validador"
    assert resultado.modelo == "modelo-de-teste"


# --- com_elogio e conferir_antes_de_enviar (decisões do diretor, 24/09/2026) --
#
# Os dois são decididos pelo PROGRAMA (nunca pelo modelo), calculados antes
# de qualquer chamada e presentes no resultado independente do desfecho.


def test_com_elogio_sim_quando_reputacao_bate_o_limiar(tmp_path):
    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json())])
    resultado = processar_lead(
        _lead(nota=4.5, avaliacoes=15),
        lead_id="x",
        prompt_sistema=_PROMPT_SISTEMA,
        cliente=cliente,
        modelo="modelo-de-teste",
        tabela_precos=_TABELA_PRECOS,
        config_validacao=_CONFIG_VALIDACAO,
        limiares_reputacao=_LIMIARES_TESTE,
        caminho_log_consumo=tmp_path / "consumo.jsonl",
    )
    assert resultado.com_elogio == "sim"


def test_com_elogio_nao_quando_reputacao_fica_abaixo_do_limiar(tmp_path):
    """Controle negativo: nota boa não basta se as avaliações não batem."""
    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json())])
    resultado = processar_lead(
        _lead(nota=5.0, avaliacoes=10),
        lead_id="x",
        prompt_sistema=_PROMPT_SISTEMA,
        cliente=cliente,
        modelo="modelo-de-teste",
        tabela_precos=_TABELA_PRECOS,
        config_validacao=_CONFIG_VALIDACAO,
        limiares_reputacao=_LIMIARES_TESTE,
        caminho_log_consumo=tmp_path / "consumo.jsonl",
    )
    assert resultado.com_elogio == "não"


def test_com_elogio_presente_mesmo_no_lead_rejeitado(tmp_path):
    """O campo é decidido ANTES de qualquer chamada -- continua presente
    mesmo quando o lead termina rejeitado_validador."""
    invalida = _resposta_valida_json("Esto no termina en pregunta.")
    cliente = _ClienteFalso([_RespostaFalsa(invalida), _RespostaFalsa(invalida)])
    resultado = processar_lead(
        _lead(nota=4.5, avaliacoes=15),
        lead_id="x",
        prompt_sistema=_PROMPT_SISTEMA,
        cliente=cliente,
        modelo="modelo-de-teste",
        tabela_precos=_TABELA_PRECOS,
        config_validacao=_CONFIG_VALIDACAO,
        limiares_reputacao=_LIMIARES_TESTE,
        caminho_log_consumo=tmp_path / "consumo.jsonl",
    )
    assert resultado.status == "rejeitado_validador"
    assert resultado.com_elogio == "sim"


def test_conferir_antes_de_enviar_sim_para_lead_com_fora_do_ar(tmp_path):
    problemas = [
        {"tipo": "fora_do_ar", "evidencia": "desktop: erro_tipo=timeout", "medicao": "site_renderizado", "coletado_em": None}
    ]
    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json())])
    resultado = processar_lead(
        _lead(problemas=problemas),
        lead_id="x",
        prompt_sistema=_PROMPT_SISTEMA,
        cliente=cliente,
        modelo="modelo-de-teste",
        tabela_precos=_TABELA_PRECOS,
        config_validacao=_CONFIG_VALIDACAO,
        limiares_reputacao=_LIMIARES_TESTE,
        caminho_log_consumo=tmp_path / "consumo.jsonl",
    )
    assert resultado.conferir_antes_de_enviar == "sim"


def test_conferir_antes_de_enviar_nao_para_lead_sem_fora_do_ar():
    """Controle negativo: lento_no_celular (o problema padrão) não ativa a
    coluna -- só fora_do_ar ativa."""
    from pipeline_estrategia_mensagem import _tem_problema_fora_do_ar

    assert _tem_problema_fora_do_ar(_lead()) is False


def test_conferir_antes_de_enviar_sim_mesmo_com_outros_problemas_junto():
    from pipeline_estrategia_mensagem import _tem_problema_fora_do_ar

    problemas = [
        {"tipo": "sem_contato_visivel", "evidencia": "x", "medicao": "site_renderizado", "coletado_em": None},
        {"tipo": "fora_do_ar", "evidencia": "y", "medicao": "site_renderizado", "coletado_em": None},
    ]
    assert _tem_problema_fora_do_ar(_lead(problemas=problemas)) is True


def test_processar_lead_falha_na_primeira_passa_na_segunda(tmp_path):
    invalida = _resposta_valida_json("Esto no termina en pregunta.")
    valida = _resposta_valida_json("¿Le envío lo que vi?")
    cliente = _ClienteFalso([_RespostaFalsa(invalida), _RespostaFalsa(valida)])
    log = tmp_path / "consumo.jsonl"

    resultado = processar_lead(
        _lead(),
        lead_id="abc123",
        prompt_sistema=_PROMPT_SISTEMA,
        cliente=cliente,
        modelo="modelo-de-teste",
        tabela_precos=_TABELA_PRECOS,
        config_validacao=_CONFIG_VALIDACAO,
        caminho_log_consumo=log,
    )

    assert resultado.status == "ok"
    assert resultado.tentativas == 2
    assert len(cliente.chamadas) == 2

    # a segunda chamada carrega o motivo da primeira falha de volta ao modelo
    segunda_mensagens = cliente.chamadas[1]["messages"]
    assert segunda_mensagens[1]["role"] == "assistant"
    assert segunda_mensagens[1]["content"] == invalida
    assert "não termina com" in segunda_mensagens[2]["content"]

    resumo = resumo_rodada(log)
    assert resumo["numero_chamadas"] == 2


def test_processar_lead_falha_nas_duas_tentativas_vira_rejeitado(tmp_path):
    invalida = _resposta_valida_json("Esto no termina en pregunta.")
    cliente = _ClienteFalso([_RespostaFalsa(invalida), _RespostaFalsa(invalida)])
    log = tmp_path / "consumo.jsonl"

    resultado = processar_lead(
        _lead(),
        lead_id="abc123",
        prompt_sistema=_PROMPT_SISTEMA,
        cliente=cliente,
        modelo="modelo-de-teste",
        tabela_precos=_TABELA_PRECOS,
        config_validacao=_CONFIG_VALIDACAO,
        caminho_log_consumo=log,
    )

    assert resultado.status == "rejeitado_validador"
    assert resultado.tentativas == 2
    assert "não termina com" in resultado.motivo_rejeicao
    assert resultado.mensagem_1 is None
    assert len(cliente.chamadas) == 2

    resumo = resumo_rodada(log)
    assert resumo["numero_chamadas"] == 2
    assert resumo["custo_total_usd"] > 0


def test_processar_lote_respeita_limite(tmp_path):
    leads = [_lead(place_id=f"lead-{i}") for i in range(5)]
    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json()) for _ in range(2)])
    log = tmp_path / "consumo.jsonl"

    resultados = processar_lote(
        leads,
        prompt_sistema=_PROMPT_SISTEMA,
        limite=2,
        cliente=cliente,
        modelo="modelo-de-teste",
        tabela_precos=_TABELA_PRECOS,
        config_validacao=_CONFIG_VALIDACAO,
        caminho_log_consumo=log,
    )

    assert len(resultados) == 2
    assert len(cliente.chamadas) == 2


def test_processar_lote_sem_limite_processa_todos(tmp_path):
    leads = [_lead(place_id=f"lead-{i}") for i in range(3)]
    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json()) for _ in range(3)])
    log = tmp_path / "consumo.jsonl"

    resultados = processar_lote(
        leads,
        prompt_sistema=_PROMPT_SISTEMA,
        cliente=cliente,
        modelo="modelo-de-teste",
        tabela_precos=_TABELA_PRECOS,
        config_validacao=_CONFIG_VALIDACAO,
        caminho_log_consumo=log,
    )

    assert len(resultados) == 3


def test_processar_lead_sem_place_id_usa_id_sintetico_no_log(tmp_path):
    from pipeline_estrategia_mensagem import _id_do_lead

    lead = _lead(place_id=None)
    assert _id_do_lead(lead, 3) == "sem-place-id-3"


def test_escrever_saida_rodada_grava_json_e_csv_com_bom(tmp_path):
    from pipeline_estrategia_mensagem import ResultadoLead

    resultados = [
        ResultadoLead(
            place_id="abc123",
            nome="Clínica Ejemplo",
            status="ok",
            tentativas=1,
            com_elogio="sim",
            conferir_antes_de_enviar="não",
            custo_total_usd=0.001,
            estrategia="e",
            canal_sugerido="whatsapp",
            mensagem_1="¿Le envío lo que vi?",
            fato_usado="lento_no_celular",
        ),
        ResultadoLead(
            place_id="def456",
            nome="Otro Negocio",
            status="rejeitado_validador",
            tentativas=2,
            com_elogio="não",
            conferir_antes_de_enviar="sim",
            motivo_rejeicao="mensagem_1 não termina com '?'",
        ),
    ]
    agora = datetime(2026, 9, 24, 10, 0, 0, tzinfo=timezone.utc)

    pasta = criar_pasta_rodada(tmp_path, agora)
    pasta_devolvida = escrever_saida_rodada(resultados, pasta=pasta)

    assert pasta_devolvida == pasta
    assert pasta.name == "rodada_20260924-100000"
    dados_json = json.loads((pasta / "resultados.json").read_text(encoding="utf-8"))
    assert len(dados_json) == 2
    assert dados_json[0]["status"] == "ok"
    assert dados_json[0]["com_elogio"] == "sim"
    assert dados_json[1]["conferir_antes_de_enviar"] == "sim"

    conteudo_bruto = (pasta / "resultados.csv").read_bytes()
    assert conteudo_bruto.startswith(b"\xef\xbb\xbf")  # BOM UTF-8, para o Excel

    with (pasta / "resultados.csv").open(encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f))
    assert len(linhas) == 2
    assert linhas[0]["com_elogio"] == "sim"
    assert linhas[1]["status"] == "rejeitado_validador"
    assert linhas[1]["motivo_rejeicao"] == "mensagem_1 não termina com '?'"
    assert linhas[1]["conferir_antes_de_enviar"] == "sim"


def test_criar_pasta_rodada_nunca_sobrescreve_rodada_anterior(tmp_path):
    """A checagem de "nunca sobrescrever" mora em `criar_pasta_rodada` --
    UMA vez, no início da rodada -- não em `escrever_saida_rodada` (defeito
    corrigido em 24/09/2026: antes, a pasta já existia quando essa checagem
    rodava, porque o log de consumo a criava implicitamente durante o
    processamento -- toda rodada real perdia os resultados)."""
    agora = datetime(2026, 9, 24, 10, 0, 0, tzinfo=timezone.utc)

    criar_pasta_rodada(tmp_path, agora)
    with pytest.raises(PastaDaRodadaJaExisteError):
        criar_pasta_rodada(tmp_path, agora)


def test_escrever_saida_rodada_grava_dentro_da_pasta_ja_criada_sem_checar_de_novo(tmp_path):
    """Prova direta do defeito corrigido: `escrever_saida_rodada` recebe uma
    pasta que JÁ existe (criada por `criar_pasta_rodada`, como o log de
    consumo já teria feito antes) e grava normalmente -- nunca levanta
    `PastaDaRodadaJaExisteError` por causa disso."""
    from pipeline_estrategia_mensagem import ResultadoLead

    agora = datetime(2026, 9, 24, 11, 0, 0, tzinfo=timezone.utc)
    pasta = criar_pasta_rodada(tmp_path, agora)
    # simula o log de consumo já tendo escrito algo na pasta antes da saída final
    (pasta / "consumo.jsonl").write_text('{"lead_id": "x"}\n', encoding="utf-8")

    resultados = [ResultadoLead(place_id="x", nome="X", status="ok", tentativas=1)]
    pasta_devolvida = escrever_saida_rodada(resultados, pasta=pasta)

    assert pasta_devolvida == pasta
    assert (pasta / "resultados.json").exists()
    assert (pasta / "resultados.csv").exists()
    assert (pasta / "consumo.jsonl").exists()


# --- main() de ponta a ponta ----------------------------------------------
#
# Nenhum teste acima chamava main() inteiro -- foi exatamente por isso que o
# defeito da pasta (achado no primeiro teste real, 24/09/2026) passou
# despercebido: cada peça isolada (processar_lote, escrever_saida_rodada)
# funcionava sozinha; só a composição das duas dentro de main() quebrava.
# Isola de rede e de chave real: `anthropic.Anthropic` é substituído por um
# construtor que devolve o cliente simulado, `contrato_loader.carregar_lote`
# por um lote fabricado em memória -- nenhuma leitura de disco fora de
# tmp_path, nenhuma chamada real.


def test_main_ponta_a_ponta_grava_json_csv_e_consumo_na_mesma_pasta(tmp_path, monkeypatch):
    import anthropic
    import contrato_loader
    import pipeline_estrategia_mensagem as pipeline_module

    lote_falso = SimpleNamespace(nata=[_lead(place_id="lead-e2e")])
    monkeypatch.setattr(contrato_loader, "carregar_lote", lambda **kwargs: lote_falso)

    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json())])
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: cliente)

    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(_PROMPT_SISTEMA, encoding="utf-8")
    saida_dir = tmp_path / "_mensagens"

    codigo = pipeline_module.main(
        ["--saida-dir", str(saida_dir), "--prompt", str(prompt_path)]
    )

    assert codigo == 0
    pastas = list(saida_dir.glob("rodada_*"))
    assert len(pastas) == 1, "defeito corrigido: a rodada tem que produzir UMA pasta, não estourar"
    pasta = pastas[0]

    # as três saídas -- é exatamente o que o defeito antigo impedia de
    # coexistir na mesma pasta (a exceção acontecia antes de gravar json/csv)
    assert (pasta / "resultados.json").is_file()
    assert (pasta / "resultados.csv").is_file()
    assert (pasta / "consumo.jsonl").is_file()

    dados = json.loads((pasta / "resultados.json").read_text(encoding="utf-8"))
    assert len(dados) == 1
    assert dados[0]["status"] == "ok"
    assert len(cliente.chamadas) == 1


def test_main_place_ids_processa_so_os_leads_selecionados(tmp_path, monkeypatch):
    import anthropic
    import contrato_loader
    import pipeline_estrategia_mensagem as pipeline_module

    lote_falso = SimpleNamespace(
        nata=[_lead(place_id="lead-1"), _lead(place_id="lead-2"), _lead(place_id="lead-3")]
    )
    monkeypatch.setattr(contrato_loader, "carregar_lote", lambda **kwargs: lote_falso)

    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json())])
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: cliente)

    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(_PROMPT_SISTEMA, encoding="utf-8")
    saida_dir = tmp_path / "_mensagens"

    codigo = pipeline_module.main(
        ["--saida-dir", str(saida_dir), "--prompt", str(prompt_path), "--place-ids", "lead-2"]
    )

    assert codigo == 0
    assert len(cliente.chamadas) == 1
    pasta = list(saida_dir.glob("rodada_*"))[0]
    dados = json.loads((pasta / "resultados.json").read_text(encoding="utf-8"))
    assert len(dados) == 1
    assert dados[0]["place_id"] == "lead-2"


def test_main_place_ids_com_varios_valores_separados_por_virgula(tmp_path, monkeypatch):
    import anthropic
    import contrato_loader
    import pipeline_estrategia_mensagem as pipeline_module

    lote_falso = SimpleNamespace(
        nata=[_lead(place_id="lead-1"), _lead(place_id="lead-2"), _lead(place_id="lead-3")]
    )
    monkeypatch.setattr(contrato_loader, "carregar_lote", lambda **kwargs: lote_falso)

    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json()) for _ in range(2)])
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: cliente)

    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(_PROMPT_SISTEMA, encoding="utf-8")
    saida_dir = tmp_path / "_mensagens"

    codigo = pipeline_module.main(
        ["--saida-dir", str(saida_dir), "--prompt", str(prompt_path), "--place-ids", "lead-1, lead-3"]
    )

    assert codigo == 0
    pasta = list(saida_dir.glob("rodada_*"))[0]
    dados = json.loads((pasta / "resultados.json").read_text(encoding="utf-8"))
    place_ids = {d["place_id"] for d in dados}
    assert place_ids == {"lead-1", "lead-3"}


def test_main_modelo_sobrescreve_o_resolvido_por_padrao(tmp_path, monkeypatch):
    """--modelo serve ao teste cego Sonnet x Opus: passa direto para
    processar_lote/chamar_llm, sem passar por llm_config.resolver_modelo()."""
    import anthropic
    import contrato_loader
    import pipeline_estrategia_mensagem as pipeline_module

    lote_falso = SimpleNamespace(nata=[_lead(place_id="lead-e2e")])
    monkeypatch.setattr(contrato_loader, "carregar_lote", lambda **kwargs: lote_falso)

    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json())])
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: cliente)

    def _resolver_modelo_nao_deveria_ser_chamado(tabela=None):
        raise AssertionError("--modelo explícito não deve consultar resolver_modelo()")

    monkeypatch.setattr(llm_config, "resolver_modelo", _resolver_modelo_nao_deveria_ser_chamado)

    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(_PROMPT_SISTEMA, encoding="utf-8")
    saida_dir = tmp_path / "_mensagens"

    codigo = pipeline_module.main(
        ["--saida-dir", str(saida_dir), "--prompt", str(prompt_path), "--modelo", "claude-opus-5"]
    )

    assert codigo == 0
    assert cliente.chamadas[0]["model"] == "claude-opus-5"


def test_main_com_comportamento_antigo_da_pasta_quebra_a_rodada(tmp_path, monkeypatch):
    """Mutação (relatada, não permanente): restaura o defeito -- a pasta só
    criada implicitamente pelo log de consumo, checagem de sobrescrita
    movida de volta para o fim -- e mostra que `main()` propaga
    `PastaDaRodadaJaExisteError` em vez de terminar a rodada. Prova que o
    teste acima teria pego o defeito antes dele chegar em produção."""
    import anthropic
    import contrato_loader
    import pipeline_estrategia_mensagem as pipeline_module

    lote_falso = SimpleNamespace(nata=[_lead(place_id="lead-e2e")])
    monkeypatch.setattr(contrato_loader, "carregar_lote", lambda **kwargs: lote_falso)
    cliente = _ClienteFalso([_RespostaFalsa(_resposta_valida_json())])
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: cliente)

    def _criar_pasta_rodada_comportamento_antigo(saida_dir, agora=None):
        # não cria a pasta aqui -- imita o código antigo, em que só o log de
        # consumo (mkdir com exist_ok=True) fazia isso, e a checagem de
        # sobrescrita só existia dentro de escrever_saida_rodada
        return pipeline_module._pasta_rodada(saida_dir, agora or datetime.now(timezone.utc))

    def _escrever_saida_rodada_comportamento_antigo(resultados, *, pasta):
        if pasta.exists():
            raise PastaDaRodadaJaExisteError(f"{pasta} já existe (comportamento antigo restaurado)")
        pasta.mkdir(parents=True)
        return pasta

    monkeypatch.setattr(pipeline_module, "criar_pasta_rodada", _criar_pasta_rodada_comportamento_antigo)
    monkeypatch.setattr(pipeline_module, "escrever_saida_rodada", _escrever_saida_rodada_comportamento_antigo)

    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(_PROMPT_SISTEMA, encoding="utf-8")
    saida_dir = tmp_path / "_mensagens"

    with pytest.raises(PastaDaRodadaJaExisteError):
        pipeline_module.main(["--saida-dir", str(saida_dir), "--prompt", str(prompt_path)])
