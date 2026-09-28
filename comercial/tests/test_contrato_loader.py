"""
Testes do contrato_loader.

Diferente da primeira versão destes testes, o schema usado aqui NÃO é
inventado: é uma cópia vendorizada de `EQC\\contracts\\leads_qualificados.schema.json`
(contrato 2.0.0 — separa `nata` e `candidatos_triagem`, ver Etapa D, passo
D3/D4), guardada em `tests/fixtures/leads_qualificados.schema.json` para os
testes não dependerem do caminho pessoal de uma máquina específica. Se o
contrato mudar de versão, essa cópia precisa ser atualizada junto —
`test_fixture_do_schema_bate_com_o_contrato_instalado` avisa quando as duas
divergem, sempre que o caminho real (`EQC\\contracts\\...`) existir na
máquina rodando os testes.

Há também um teste de integração (`test_integracao_arquivo_real_do_qualificador`)
que roda o loader contra o schema E o lote reais publicados em
`EQC\\pipeline\\qualificador-output\\`. Ele pula (`skip`), não falha, quando
esses caminhos não existem — mantém a suíte portátil para outra máquina ou
CI, mas ainda verifica a integração de ponta a ponta nesta.
"""

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

FERRAMENTAS_DIR = Path(__file__).resolve().parent.parent / "ferramentas"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SCHEMA_FIXTURE_PATH = FIXTURES_DIR / "leads_qualificados.schema.json"

sys.path.insert(0, str(FERRAMENTAS_DIR))

import contrato_loader as cl  # noqa: E402


# --- Fixtures: documento válido no formato real do contrato 2.0.0 -------


def _campo(valor: object, estado: str) -> dict:
    return {"valor": valor, "estado": estado}


def _lead_minimo() -> dict:
    """Um lead COMPLETO_SEM_SITE, com todas as chaves exigidas pelo schema real."""
    return {
        "place_id": "ChIJFicticioLead00000000001",
        "estagio_analise": "COMPLETO_SEM_SITE",
        "classe_site": "sem_site",
        "problema_vendavel": [],
        "identidade": {
            "nome": "Fisioficticia Salud",
            "nicho": "Clínica de Fisioterapia",
            "cidade": "Alicante",
            "endereco": "1 Calle Ficticia",
            "google_maps_url": "https://www.google.com/maps?cid=1000000000000000001",
        },
        "contato": {
            "telefone": _campo("600000101", cl.ESTADO_CONFIRMADO_PRESENTE),
            "email": _campo(None, cl.ESTADO_CONFIRMADO_AUSENTE),
            "instagram": _campo(None, cl.ESTADO_CONFIRMADO_AUSENTE),
            "facebook": _campo(None, cl.ESTADO_CONFIRMADO_AUSENTE),
            "linkedin": _campo(None, cl.ESTADO_NAO_VERIFICADO),
            "whatsapp_apto": True,
        },
        "reputacao": {
            "nota_google": _campo(5.0, cl.ESTADO_CONFIRMADO_PRESENTE),
            "review_count": _campo(107, cl.ESTADO_CONFIRMADO_PRESENTE),
            "reputation_signal": "strong",
        },
        "presenca_digital": {
            "tem_site_proprio": _campo(False, cl.ESTADO_CONFIRMADO_AUSENTE),
            "website_url": _campo(None, cl.ESTADO_CONFIRMADO_AUSENTE),
            "site_via_rede_social": _campo(None, cl.ESTADO_CONFIRMADO_AUSENTE),
        },
        "gbp_diagnostico": {
            "score_completude": 40,
            "detail_scraped": True,
            "sinais": {
                "ficha_reivindicada": {"estado": cl.ESTADO_CONFIRMADO_PRESENTE},
                "tem_horario": {"estado": cl.ESTADO_NAO_VERIFICADO},
            },
            "lacunas": ["sem horário confirmado"],
        },
        "gbp_campos_crus": {
            "ficha_reivindicada": _campo("YES", cl.ESTADO_CONFIRMADO_PRESENTE),
            "tem_horario": _campo(None, cl.ESTADO_NAO_VERIFICADO),
            "tem_foto_destaque": _campo(None, cl.ESTADO_NAO_VERIFICADO),
            "tem_descricao": _campo(None, cl.ESTADO_NAO_VERIFICADO),
            "tem_faixa_preco": _campo(None, cl.ESTADO_NAO_VERIFICADO),
            "tem_plus_code": _campo(None, cl.ESTADO_NAO_VERIFICADO),
            "tem_dono_listado": _campo(None, cl.ESTADO_NAO_VERIFICADO),
            "detail_scraped": True,
        },
        "evidencias_qualificador": {
            "fatos": ["107 avaliações no Google"],
            "sinais_site": None,
        },
        "priorizacao": {
            "autoritativo": False,
            "commercial_fit_score": 60,
            "priority": "alta",
            "contactability": "media",
            "risks": ["cidade não confirmada"],
            "reasons": ["reputação: sinal 'strong' (+35)", "telefone disponível"],
            "website_opportunity_score": None,
            "priority_score": None,
            "priority_label": None,
            "lacunas_interpretadas": None,
        },
        "analise_tecnica_site": {
            "status": None,
            "error_type": None,
            "avaliado_em": None,
            "telefone_na_pagina": _campo_telefone_na_pagina(None, cl.ESTADO_NAO_VERIFICADO),
        },
        "psi": None,
    }


def _campo_telefone_na_pagina(valor: "str | None", estado: str) -> dict:
    return {"valor": valor, "estado": estado}


def _lead_candidato_triagem(place_id: str = "OUTRO_PLACE_ID_CANDIDATO") -> dict:
    """Um lead com `candidato_triagem_visual` -- exigido pelo schema para
    todo item de `candidatos_triagem` (allOf, schema.json), mas ausente por
    padrão em `_lead_minimo()` (nem todo lead é candidato à triagem)."""
    lead = _lead_minimo()
    lead["place_id"] = place_id
    lead["candidato_triagem_visual"] = {
        "captura_ref": f"capturas_site/{place_id}.png",
        "coletado_em": "2026-09-22T10:00:00Z",
    }
    return lead


def _documento_valido(nata: list = None, candidatos_triagem: list = None) -> dict:
    if nata is None:
        nata = [_lead_minimo()]
    if candidatos_triagem is None:
        candidatos_triagem = []
    total = len(nata) + len(candidatos_triagem)
    return {
        "contract_version": cl.VERSAO_CONTRATO_SUPORTADA,
        "schema_version": "2.0",
        "generated_at": "2026-09-06T20:10:42Z",
        "origem_csv": "extrator_20260906-021834_v1.csv",
        "stats": {
            "nata": len(nata),
            "candidatos_triagem": len(candidatos_triagem),
            "leads_total": total,
            "sem_site": total,
            "com_site": 0,
            "descartados": 0,
        },
        "nata": nata,
        "candidatos_triagem": candidatos_triagem,
        "descartados": [],
    }


@pytest.fixture
def schema_path():
    return SCHEMA_FIXTURE_PATH


@pytest.fixture
def entrada(tmp_path):
    d = tmp_path / "qualificador-output"
    d.mkdir()
    return d


def _escrever(diretorio: Path, nome: str, documento) -> Path:
    caminho = diretorio / nome
    caminho.write_text(json.dumps(documento, ensure_ascii=False), encoding="utf-8")
    return caminho


# --- Arquivo válido carrega corretamente ---------------------------------


def test_arquivo_valido_carrega(entrada, schema_path):
    origem = _escrever(
        entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido()
    )

    lote = cl.carregar_lote(caminho=origem, schema=schema_path)

    assert len(lote) == 1
    assert lote.origem == origem
    assert lote.schema_usado == schema_path
    assert lote.contract_version == cl.VERSAO_CONTRATO_SUPORTADA
    assert len(lote.nata) == 1
    assert len(lote.candidatos_triagem) == 0
    lead = lote.leads[0]
    assert lead["identidade"]["nome"] == "Fisioficticia Salud"
    assert lead["estagio_analise"] == "COMPLETO_SEM_SITE"


def test_carrega_multiplos_leads_e_expoe_stats_e_descartados(entrada, schema_path):
    doc = _documento_valido(nata=[_lead_minimo(), _lead_minimo()])
    doc["descartados"] = [
        {
            "place_id": "ChIJFicticioLead00000000002",
            "identidade": {"nome": "Descartado Teste", "nicho": None, "cidade": None},
            "motivo": "sem_canal_de_contato",
            "campos_do_corte": {},
        }
    ]
    doc["stats"]["descartados"] = 1
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", doc)

    lote = cl.carregar_lote(caminho=origem, schema=schema_path)

    assert len(lote) == 2
    assert len(lote.nata) == 2
    assert lote.stats["nata"] == 2
    assert len(lote.descartados) == 1
    assert lote.descartados[0]["motivo"] == "sem_canal_de_contato"


# --- Arquivo inválido falha alto -----------------------------------------


def test_campo_obrigatorio_ausente_falha_alto(entrada, schema_path):
    doc = _documento_valido()
    del doc["nata"][0]["identidade"]["nome"]
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", doc)

    with pytest.raises(cl.ContratoInvalidoError) as exc:
        cl.carregar_lote(caminho=origem, schema=schema_path)

    assert "nome" in str(exc.value)
    assert "nata/0/identidade" in str(exc.value)
    assert str(origem) in str(exc.value)


def test_tipo_errado_falha_alto(entrada, schema_path):
    doc = _documento_valido()
    doc["nata"][0]["place_id"] = 12345  # deveria ser string ou null
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", doc)

    with pytest.raises(cl.ContratoInvalidoError):
        cl.carregar_lote(caminho=origem, schema=schema_path)


def test_estado_evidencia_invalido_falha_alto(entrada, schema_path):
    """Um estado fora do enum (typo, versão antiga) reprova na validação."""
    doc = _documento_valido()
    doc["nata"][0]["contato"]["telefone"] = {"valor": "600000000", "estado": "PRESENTE"}
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", doc)

    with pytest.raises(cl.ContratoInvalidoError):
        cl.carregar_lote(caminho=origem, schema=schema_path)


def test_additional_property_falha_alto(entrada, schema_path):
    """additionalProperties: false no schema real -- campo extra deve reprovar."""
    doc = _documento_valido()
    doc["nata"][0]["campo_que_nao_existe"] = "valor"
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", doc)

    with pytest.raises(cl.ContratoInvalidoError):
        cl.carregar_lote(caminho=origem, schema=schema_path)


def test_candidato_triagem_sem_o_bloco_visual_falha_alto(entrada, schema_path):
    """candidatos_triagem exige candidato_triagem_visual (allOf, schema.json) --
    um lead igual ao da nata, sem esse bloco, reprova quando entra na lista
    errada."""
    doc = _documento_valido(nata=[], candidatos_triagem=[_lead_minimo()])
    origem = _escrever(entrada, "leads_qualificados_20260922-100000_v2.0.0.json", doc)

    with pytest.raises(cl.ContratoInvalidoError):
        cl.carregar_lote(caminho=origem, schema=schema_path)


def test_nata_e_candidatos_triagem_ficam_em_listas_separadas(entrada, schema_path):
    doc = _documento_valido(
        nata=[_lead_minimo()], candidatos_triagem=[_lead_candidato_triagem()]
    )
    origem = _escrever(entrada, "leads_qualificados_20260922-100000_v2.0.0.json", doc)

    lote = cl.carregar_lote(caminho=origem, schema=schema_path)

    assert len(lote.nata) == 1
    assert len(lote.candidatos_triagem) == 1
    assert lote.nata[0]["place_id"] == "ChIJFicticioLead00000000001"
    assert lote.candidatos_triagem[0]["place_id"] == "OUTRO_PLACE_ID_CANDIDATO"
    assert lote.candidatos_triagem[0]["candidato_triagem_visual"]["captura_ref"] == (
        "capturas_site/OUTRO_PLACE_ID_CANDIDATO.png"
    )


def test_leads_e_nata_mais_candidatos_nessa_ordem(entrada, schema_path):
    """`.leads` é conveniência de leitura (nata + candidatos_triagem, nessa
    ordem) -- não é um campo do contrato. Ver docstring de contrato_loader.Lote."""
    doc = _documento_valido(
        nata=[_lead_minimo()], candidatos_triagem=[_lead_candidato_triagem()]
    )
    origem = _escrever(entrada, "leads_qualificados_20260922-100000_v2.0.0.json", doc)

    lote = cl.carregar_lote(caminho=origem, schema=schema_path)

    assert len(lote) == 2
    assert [lead["place_id"] for lead in lote.leads] == [
        "ChIJFicticioLead00000000001",
        "OUTRO_PLACE_ID_CANDIDATO",
    ]
    assert list(lote) == lote.leads


def test_json_malformado_falha_alto(entrada, schema_path):
    origem = entrada / "leads_qualificados_20260906-201042_v2.0.0.json"
    origem.write_text('{"leads": [', encoding="utf-8")

    with pytest.raises(cl.ContratoInvalidoError, match="não é JSON válido"):
        cl.carregar_lote(caminho=origem, schema=schema_path)


def test_schema_ausente_falha_alto(entrada, tmp_path):
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())

    with pytest.raises(cl.SchemaIndisponivelError, match="não encontrado"):
        cl.carregar_lote(caminho=origem, schema=tmp_path / "nao_existe.schema.json")


def test_schema_invalido_falha_alto(entrada, tmp_path):
    ruim = tmp_path / "ruim.schema.json"
    ruim.write_text(json.dumps({"type": "objeto-que-nao-existe"}), encoding="utf-8")
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())

    with pytest.raises(cl.SchemaIndisponivelError, match="próprio schema"):
        cl.carregar_lote(caminho=origem, schema=ruim)


# --- Versão do contrato ---------------------------------------------------


def test_contract_version_diferente_falha_alto_mesmo_com_schema_permissivo(entrada, tmp_path):
    """A trava de versão é independente do schema carregado -- ver docstring
    do módulo, "Trava de versão". Um schema frouxo que aceitaria qualquer
    contract_version ainda assim não deve passar pelo loader."""
    schema_frouxo = tmp_path / "frouxo.schema.json"
    schema_frouxo.write_text(
        json.dumps({"type": "object", "required": ["contract_version", "nata"]}),
        encoding="utf-8",
    )
    doc = _documento_valido()
    doc["contract_version"] = "9.9.9"  # qualquer versão != cl.VERSAO_CONTRATO_SUPORTADA
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v9.9.9.json", doc)

    with pytest.raises(cl.VersaoContratoNaoSuportadaError, match="9.9.9"):
        cl.carregar_lote(caminho=origem, schema=schema_frouxo)


def test_versao_nao_suportada_e_subclasse_de_contrato_invalido(entrada, tmp_path):
    """Quem só sabe tratar ContratoInvalidoError ainda pega este erro."""
    schema_frouxo = tmp_path / "frouxo.schema.json"
    schema_frouxo.write_text(json.dumps({"type": "object"}), encoding="utf-8")
    doc = _documento_valido()
    doc["contract_version"] = "0.9.0"
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v0.9.0.json", doc)

    with pytest.raises(cl.ContratoInvalidoError):
        cl.carregar_lote(caminho=origem, schema=schema_frouxo)


def test_contract_version_real_e_a_esperada(schema_path):
    """Documenta a trava: a versão que o loader suporta é a do contrato vigente."""
    assert cl.VERSAO_CONTRATO_SUPORTADA == "2.1.0"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["properties"]["contract_version"]["const"] == cl.VERSAO_CONTRATO_SUPORTADA


# --- Formato do documento: fixo, sem tolerância a formato alternativo ----


def test_documento_sem_chave_nata_falha_alto(entrada, tmp_path):
    """O formato é conhecido agora -- não há tolerância a lista solta no
    topo, nem à antiga chave única 'leads' do contrato 1.x (substituída por
    'nata' + 'candidatos_triagem' no contrato 2.0.0)."""
    schema_permissivo = tmp_path / "permissivo.schema.json"
    schema_permissivo.write_text(
        json.dumps({"type": "object", "required": ["contract_version"]}), encoding="utf-8"
    )
    doc = _documento_valido()
    doc["leads"] = doc.pop("nata")  # chave antiga do contrato 1.x, não mais aceita
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", doc)

    with pytest.raises(cl.ContratoInvalidoError, match="nata"):
        cl.carregar_lote(caminho=origem, schema=schema_permissivo)


def test_documento_sem_chave_candidatos_triagem_falha_alto(entrada, tmp_path):
    schema_permissivo = tmp_path / "permissivo.schema.json"
    schema_permissivo.write_text(
        json.dumps({"type": "object", "required": ["contract_version"]}), encoding="utf-8"
    )
    doc = _documento_valido()
    del doc["candidatos_triagem"]
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", doc)

    with pytest.raises(cl.ContratoInvalidoError, match="candidatos_triagem"):
        cl.carregar_lote(caminho=origem, schema=schema_permissivo)


def test_lista_solta_no_topo_nao_e_mais_aceita(entrada, tmp_path):
    schema_permissivo = tmp_path / "permissivo.schema.json"
    schema_permissivo.write_text(json.dumps({"type": "array"}), encoding="utf-8")
    origem = _escrever(
        entrada, "leads_qualificados_20260906-201042_v2.0.0.json", [_lead_minimo()]
    )

    with pytest.raises(cl.ContratoInvalidoError):
        cl.carregar_lote(caminho=origem, schema=schema_permissivo)


# --- Seleção do mais recente ---------------------------------------------


def test_seleciona_mais_recente_entre_varios(entrada, schema_path):
    _escrever(entrada, "leads_qualificados_20260901-090000_v2.0.0.json", _documento_valido())
    _escrever(entrada, "leads_qualificados_20260906-011856_v2.0.0.json", _documento_valido())
    esperado = _escrever(
        entrada, "leads_qualificados_20260906-235959_v2.0.0.json", _documento_valido()
    )
    _escrever(entrada, "leads_qualificados_20260903-120000_v2.0.0.json", _documento_valido())

    assert cl.localizar_mais_recente(entrada) == esperado

    lote = cl.carregar_lote(diretorio=entrada, schema=schema_path)
    assert lote.origem == esperado


def test_ordem_e_por_timestamp_nao_por_mtime(entrada):
    """O arquivo mais novo no disco não é necessariamente o mais recente do
    lote — copiar um arquivo antigo atualiza o mtime e escolheria errado."""
    novo = _escrever(
        entrada, "leads_qualificados_20260906-235959_v2.0.0.json", _documento_valido()
    )
    antigo = _escrever(
        entrada, "leads_qualificados_20260101-000000_v2.0.0.json", _documento_valido()
    )
    # `antigo` foi escrito por último, logo tem mtime maior que `novo`.
    assert antigo.stat().st_mtime >= novo.stat().st_mtime

    assert cl.localizar_mais_recente(entrada) == novo


def test_ignora_arquivo_meta(entrada):
    esperado = _escrever(
        entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido()
    )
    _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.meta.json", {"linhas_totais": 21})

    assert cl.listar_arquivos(entrada) == [esperado]
    assert cl.localizar_mais_recente(entrada) == esperado


def test_ignora_arquivo_sem_timestamp(entrada):
    esperado = _escrever(
        entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido()
    )
    _escrever(entrada, "leads_qualificados_rascunho.json", _documento_valido())

    assert cl.listar_arquivos(entrada) == [esperado]


def test_diretorio_vazio_falha_alto(entrada):
    with pytest.raises(cl.ArquivoDeEntradaError, match="Nenhum arquivo"):
        cl.localizar_mais_recente(entrada)


def test_diretorio_inexistente_falha_alto(tmp_path):
    with pytest.raises(cl.ArquivoDeEntradaError, match="não existe"):
        cl.localizar_mais_recente(tmp_path / "nao_existe")


def test_env_define_diretorio_de_entrada(entrada, schema_path, monkeypatch):
    esperado = _escrever(
        entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido()
    )
    monkeypatch.setenv(cl.ENV_DIRETORIO_ENTRADA, str(entrada))
    monkeypatch.setenv(cl.ENV_SCHEMA, str(schema_path))

    lote = cl.carregar_lote()

    assert lote.origem == esperado


# --- Proteção do bloco priorizacao ---------------------------------------


def test_priorizacao_acessivel_pelo_nome_que_avisa(entrada, schema_path):
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    bloco = lead.priorizacao_nao_autoritativa

    assert bloco["commercial_fit_score"] == 60
    assert bloco["autoritativo"] is False


def test_priorizacao_por_atributo_simples_e_bloqueada(entrada, schema_path):
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    with pytest.raises(cl.BlocoNaoAutoritativoError, match="NÃO AUTORITATIVO"):
        lead.priorizacao


def test_priorizacao_por_indice_e_bloqueada(entrada, schema_path):
    """O caminho que alguém escreve por reflexo ao tratar o lead como dict."""
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    with pytest.raises(cl.BlocoNaoAutoritativoError):
        lead["priorizacao"]


def test_priorizacao_fora_da_iteracao(entrada, schema_path):
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    assert "priorizacao" not in list(lead)
    assert "priorizacao" not in dict(lead)
    assert "identidade" in dict(lead)


def test_bloco_e_somente_leitura(entrada, schema_path):
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    bloco = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0].priorizacao_nao_autoritativa

    with pytest.raises(TypeError):
        bloco["commercial_fit_score"] = 1


def test_repr_do_bloco_carrega_o_aviso(entrada, schema_path):
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    bloco = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0].priorizacao_nao_autoritativa

    assert "NAO_AUTORITATIVO" in repr(bloco)


def test_bruto_e_a_escotilha_explicita(entrada, schema_path):
    """Contornar a proteção é possível, mas exige uma chamada com nome
    próprio — localizável num grep por `.bruto()`."""
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    assert lead.bruto()["priorizacao"]["commercial_fit_score"] == 60


def test_atributo_desconhecido_da_erro_claro(entrada, schema_path):
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    with pytest.raises(AttributeError, match="lead\\['identidade'\\]"):
        lead.identidade


# --- Proteção dos campos de evidência ({valor, estado}) ------------------


def test_campo_confirmado_presente_devolve_valor(entrada, schema_path):
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    telefone = lead["contato"]["telefone"]

    assert isinstance(telefone, cl.CampoEvidencia)
    assert telefone.presente() is True
    assert telefone.confirmado_ausente() is False
    assert telefone.nao_verificado() is False
    assert telefone.valor_confirmado == "600000101"
    assert telefone.estado == "CONFIRMADO_PRESENTE"


def test_campo_confirmado_ausente_bloqueia_valor_confirmado(entrada, schema_path):
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    email = lead["contato"]["email"]

    assert email.confirmado_ausente() is True
    assert email.presente() is False
    with pytest.raises(cl.EvidenciaNaoConfirmadaError, match="CONFIRMADO_AUSENTE"):
        email.valor_confirmado


def test_campo_nao_verificado_bloqueia_valor_confirmado(entrada, schema_path):
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    linkedin = lead["contato"]["linkedin"]

    assert linkedin.nao_verificado() is True
    with pytest.raises(cl.EvidenciaNaoConfirmadaError, match="NAO_VERIFICADO"):
        linkedin.valor_confirmado


def test_confirmado_ausente_e_nao_verificado_nao_sao_o_mesmo_estado(entrada, schema_path):
    """O ponto central do CONTRACT.md: os dois estados nunca colapsam num
    só, mesmo quando o `valor` bruto é `None` nos dois casos."""
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    email = lead["contato"]["email"]  # CONFIRMADO_AUSENTE
    linkedin = lead["contato"]["linkedin"]  # NAO_VERIFICADO

    assert email.bruto()["valor"] is None
    assert linkedin.bruto()["valor"] is None
    assert email.estado != linkedin.estado
    assert email.confirmado_ausente() and not email.nao_verificado()
    assert linkedin.nao_verificado() and not linkedin.confirmado_ausente()


def test_campo_de_evidencia_aninhado_em_gbp_diagnostico_tambem_e_envolvido(entrada, schema_path):
    """gbp_diagnostico.sinais.* só tem 'estado', sem 'valor' -- ainda assim
    vira CampoEvidencia (valor cru ausente vira None)."""
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    sinal = lead["gbp_diagnostico"]["sinais"]["tem_horario"]

    assert isinstance(sinal, cl.CampoEvidencia)
    assert sinal.nao_verificado() is True


def test_campo_bruto_devolve_dict_puro(entrada, schema_path):
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    assert lead["contato"]["telefone"].bruto() == {
        "valor": "600000101",
        "estado": "CONFIRMADO_PRESENTE",
    }


def test_lead_bruto_nao_envolve_nada(entrada, schema_path):
    """`.bruto()` do lead é o dict cru original -- sem CampoEvidencia, com priorizacao."""
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    bruto = lead.bruto()
    assert isinstance(bruto["contato"]["telefone"], dict)
    assert "priorizacao" in bruto


def test_repr_de_campo_evidencia_nao_estoura(entrada, schema_path):
    origem = _escrever(entrada, "leads_qualificados_20260906-201042_v2.0.0.json", _documento_valido())
    lead = cl.carregar_lote(caminho=origem, schema=schema_path).leads[0]

    assert "CONFIRMADO_PRESENTE" in repr(lead["contato"]["telefone"])


# --- Fidelidade da fixture ao contrato instalado (quando disponível) ------


import eqc  # noqa: E402  -- resolvedor oficial do EQC no COMERCIAL (ferramentas/eqc.py)

# Resolvidos em runtime pelo MESMO mecanismo que o contrato_loader usa em
# produção (env COMERCIAL_EQC_ROOT / LEADFARM_ROOT / descoberta subindo a
# árvore a partir da raiz do projeto). Sem caminho de máquina fixo e sem
# reimplementar a descoberta aqui. Podem apontar para um lugar que não
# existe noutra máquina/CI -- os testes abaixo pulam nesse caso, nunca aqui.
REAL_SCHEMA_PATH = eqc.caminho_schema_contrato()
REAL_INPUT_DIR = eqc.diretorio_lotes_entrada()


def _versao_do_lote_real_mais_recente() -> "str | None":
    """Lê só o campo `contract_version` do lote real mais recente, sem
    passar por `carregar_lote` -- que já lançaria em vez de permitir o skip.
    `None` se não houver lote, ou se o campo não existir/for ilegível.

    Existe porque `EQC\\pipeline\\qualificador-output\\` pode conter um lote
    publicado por uma versão de contrato anterior à que este módulo suporta
    agora (ex.: o histórico 1.1.0 nesta máquina em 22/09/2026, antes do
    QUALIFICADOR publicar um lote 2.0.0 de verdade -- Etapa D, passo D3/D4).
    Isso não é defeito do loader nem do teste: é o estado real do disco
    nesta máquina, e os testes de integração abaixo pulam nesse caso em vez
    de reprovar por um artefato desatualizado que não fui autorizado a
    regenerar (PROIBIDO tocar em qualificador/ ou rodar o pipeline)."""
    arquivos = cl.listar_arquivos(REAL_INPUT_DIR) if REAL_INPUT_DIR.is_dir() else []
    if not arquivos:
        return None
    try:
        doc = json.loads(arquivos[-1].read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None
    return doc.get("contract_version") if isinstance(doc, dict) else None


def test_fixture_do_schema_bate_com_o_contrato_instalado():
    if not REAL_SCHEMA_PATH.is_file():
        pytest.skip("EQC\\contracts\\leads_qualificados.schema.json não existe nesta máquina")

    fixture = json.loads(SCHEMA_FIXTURE_PATH.read_text(encoding="utf-8"))
    real = json.loads(REAL_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert fixture == real, (
        "tests/fixtures/leads_qualificados.schema.json está desatualizada em "
        "relação a EQC\\contracts\\leads_qualificados.schema.json -- copie de novo."
    )


def test_integracao_arquivo_real_do_qualificador():
    """Ponta a ponta contra os artefatos publicados pelo QUALIFICADOR nesta
    máquina. Pula em outra máquina/CI onde EQC não existe, e também quando o
    lote real em disco ainda é de uma versão de contrato anterior à que este
    módulo suporta (ver `_versao_do_lote_real_mais_recente`) -- não é um
    teste portátil, é uma verificação de integração local."""
    if not REAL_SCHEMA_PATH.is_file() or not REAL_INPUT_DIR.is_dir():
        pytest.skip("EQC\\contracts ou EQC\\pipeline\\qualificador-output ausentes nesta máquina")
    versao_real = _versao_do_lote_real_mais_recente()
    if versao_real != cl.VERSAO_CONTRATO_SUPORTADA:
        pytest.skip(
            f"Lote real mais recente declara contract_version={versao_real!r}, "
            f"não {cl.VERSAO_CONTRATO_SUPORTADA!r} -- nenhum lote real nesta "
            f"versão publicado ainda nesta máquina."
        )

    lote = cl.carregar_lote(diretorio=REAL_INPUT_DIR, schema=REAL_SCHEMA_PATH)

    assert lote.contract_version == cl.VERSAO_CONTRATO_SUPORTADA
    assert len(lote) == lote.stats["nata"] + lote.stats["candidatos_triagem"]
    for lead in lote.leads:
        assert lead["estagio_analise"] in ("COMPLETO_SEM_SITE", "COMPLETO_COM_SITE")
        # priorizacao nunca acessível pelo nome cru, mesmo em dado real
        with pytest.raises(cl.BlocoNaoAutoritativoError):
            lead["priorizacao"]


def test_selecao_mais_recente_entre_lotes_reais(tmp_path):
    """O diretório real (`EQC\\pipeline\\qualificador-output\\`) hoje contém
    só o lote mais recente publicado pelo QUALIFICADOR -- lotes anteriores não
    ficam retidos ali. Para verificar a seleção "mais recente entre vários"
    com conteúdo real (não só a fixture sintética já coberta em
    `test_seleciona_mais_recente_entre_varios`), duplicamos o conteúdo do
    lote real sob dois nomes de timestamp diferentes."""
    if not REAL_SCHEMA_PATH.is_file() or not REAL_INPUT_DIR.is_dir():
        pytest.skip("EQC\\contracts ou EQC\\pipeline\\qualificador-output ausentes nesta máquina")

    arquivos_reais = cl.listar_arquivos(REAL_INPUT_DIR)
    if not arquivos_reais:
        pytest.skip("Nenhum lote real disponível para duplicar neste teste")
    conteudo = arquivos_reais[-1].read_bytes()

    mais_antigo = tmp_path / "leads_qualificados_20260906-201042_v1.1.0.json"
    mais_novo = tmp_path / "leads_qualificados_20260908-074342_v1.1.0.json"
    mais_antigo.write_bytes(conteudo)
    mais_novo.write_bytes(conteudo)

    assert cl.localizar_mais_recente(tmp_path) == mais_novo


def test_integracao_psi_dois_estados_reais_lote_real():
    """`psi` chega, em `nata`/`candidatos_triagem` do contrato 2.0.0, em duas
    formas reais -- `NAO_VERIFICADO`, `CONFIRMADO_PRESENTE` -- e NUNCA como
    `CampoEvidencia`, mesmo tendo uma chave "estado". `contrato_loader._parece_campo_evidencia`
    só envolve um dict cujas chaves sejam EXATAMENTE `valor`+`estado`; o objeto
    de medição completa tem chaves adicionais (`performance_score`, `lcp_ms`,
    `estrategia`, `origem`, `tentativas`, `rodadas`, `falha_transiente`...) e
    nenhuma chave `valor`; o objeto `NAO_VERIFICADO` tem `motivo`/`medido_em`
    além de `estado`. Ver agents/01_investigacao/agent.md e
    referencias/insumos_sistema_qualificacao.md, seção "psi", para a
    divergência documentada a partir deste teste.

    O QUE MUDOU (23/09/2026, adaptação ao contrato 2.0.0): CONTRACT.md §
    "Princípios do contrato" fechou o terceiro estado -- "leads sem site
    próprio... ficam fora do JSON" -- então `psi=None` (`PSI_SEM_SITE`) não
    ocorre mais em `nata`/`candidatos_triagem` de um lote real (confirmado
    no lote de 23/09: `stats.sem_site == 0`, `stats.com_site == 47`). O nome
    do teste e a asserção de `null` foram ajustados para essa realidade; o
    que o teste prova -- psi nunca vira `CampoEvidencia`, mesmo tendo
    "estado" -- continua o mesmo. O terceiro estado (`psi=None`,
    `PSI_SEM_SITE`) continua coberto por unidade sintética em
    `test_psi_estado_sem_site` (não depende de lote real, então não quebra
    quando o contrato para de produzi-lo em produção)."""
    if not REAL_SCHEMA_PATH.is_file() or not REAL_INPUT_DIR.is_dir():
        pytest.skip("EQC\\contracts ou EQC\\pipeline\\qualificador-output ausentes nesta máquina")
    versao_real = _versao_do_lote_real_mais_recente()
    if versao_real != cl.VERSAO_CONTRATO_SUPORTADA:
        pytest.skip(
            f"Lote real mais recente declara contract_version={versao_real!r}, "
            f"não {cl.VERSAO_CONTRATO_SUPORTADA!r} -- nenhum lote real nesta "
            f"versão publicado ainda nesta máquina."
        )

    lote = cl.carregar_lote(diretorio=REAL_INPUT_DIR, schema=REAL_SCHEMA_PATH)

    contagem = Counter()
    exemplo_medido = None
    for lead in lote.leads:
        psi = lead["psi"]
        if psi is None:
            contagem["null"] += 1
            continue

        # nunca CampoEvidencia, sempre dict cru -- mesmo tendo "estado"
        assert isinstance(psi, dict), f"esperava dict cru, veio {type(psi)!r}"
        assert not isinstance(psi, cl.CampoEvidencia)
        assert "estado" in psi
        contagem[psi["estado"]] += 1
        if psi["estado"] == "CONFIRMADO_PRESENTE":
            exemplo_medido = psi

    if contagem.get("CONFIRMADO_PRESENTE", 0) == 0:
        pytest.skip(
            "Lote atual não tem nenhum lead com psi medido (CONFIRMADO_PRESENTE) "
            "-- reexecutar contra um lote em que o QUALIFICADOR já mediu."
        )

    # Contrato 2.0.0: nata/candidatos_triagem nunca contêm lead sem site --
    # "null" (PSI_SEM_SITE) não deveria mais ocorrer aqui (ver docstring,
    # "O QUE MUDOU"). Os dois estados observados em produção em 23/09/2026
    # (4 NAO_VERIFICADO / 43 CONFIRMADO_PRESENTE) -- aqui só exigimos
    # presença de cada um, não a contagem exata, para não prender o teste a
    # um lote específico.
    assert contagem["null"] == 0
    assert contagem["NAO_VERIFICADO"] >= 1
    assert contagem["CONFIRMADO_PRESENTE"] >= 1

    # o exemplo medido confirma o shape que causou a divergência: sem "valor",
    # sem os métodos de CampoEvidencia
    assert "valor" not in exemplo_medido
    assert "performance_score" in exemplo_medido
    assert not hasattr(exemplo_medido, "presente")
    assert not hasattr(exemplo_medido, "valor_confirmado")


# --- psi_estado() ---------------------------------------------------------
#
# Testes unitários, direto sobre LeadQualificado(dict) -- não precisam
# passar pela validação de schema completa, só exercitar a leitura de
# `psi` nos três casos (mais o caso de forma inesperada).


def test_psi_estado_sem_site():
    lead = cl.LeadQualificado({**_lead_minimo(), "psi": None})
    assert cl.psi_estado(lead) == cl.PSI_SEM_SITE


def test_psi_estado_nao_verificado():
    lead = cl.LeadQualificado(
        {**_lead_minimo(), "psi": {"estado": "NAO_VERIFICADO", "motivo": "ainda não medido", "medido_em": None}}
    )
    assert cl.psi_estado(lead) == cl.ESTADO_NAO_VERIFICADO


def test_psi_estado_confirmado_presente():
    lead = cl.LeadQualificado(
        {
            **_lead_minimo(),
            "psi": {
                "estado": "CONFIRMADO_PRESENTE",
                "performance_score": 100,
                "lcp_ms": 620,
                "cls": 0.01,
                "tbt_ms": 20,
                "estrategia": "mobile",
                "origem": "psi_api",
                "tentativas": 1,
                "rodadas": 1,
                "falha_transiente": False,
                "medido_em": "2026-09-08T07:00:00Z",
            },
        }
    )
    assert cl.psi_estado(lead) == cl.ESTADO_CONFIRMADO_PRESENTE


def test_psi_estado_nunca_levanta_typeerror_sobre_none():
    """A razão de existir: `lead["psi"]["estado"]` direto sobre `None`
    levanta TypeError -- erro real do piloto do A1. psi_estado() nunca
    levanta isso, só ContratoError em forma verdadeiramente inesperada."""
    lead = cl.LeadQualificado({**_lead_minimo(), "psi": None})
    try:
        cl.psi_estado(lead)
    except TypeError:
        pytest.fail("psi_estado() não deveria levantar TypeError para psi=None")


def test_psi_estado_forma_inesperada_levanta_contrato_error():
    lead = cl.LeadQualificado({**_lead_minimo(), "psi": {"estado": "ALGO_NOVO"}})
    with pytest.raises(cl.ContratoError, match="forma inesperada"):
        cl.psi_estado(lead)
