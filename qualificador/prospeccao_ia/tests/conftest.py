import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import contrato
import main as main_mod
import saida_humana
import _guardiao_producao as guardiao


@pytest.fixture(scope="session", autouse=True)
def _schema_do_contrato_disponivel():
    """O schema do contrato é a fonte de verdade e vive FORA do repo
    (QUALIFICADOR_CONTRACT_SCHEMA, default em contrato.CONTRACT_SCHEMA_DEFAULT). A validação
    de fase_saida depende dele -- se não estiver no lugar, a suíte para com mensagem clara
    em vez de dezenas de FileNotFoundError."""
    caminho = contrato.contract_schema_path()
    if not os.path.exists(caminho):
        pytest.fail(
            f"Schema do contrato ausente: {caminho}\n"
            f"Defina QUALIFICADOR_CONTRACT_SCHEMA ou coloque o arquivo no default "
            f"(EQC/contracts/leads_qualificados.schema.json).",
            pytrace=False,
        )


def _pastas_producao():
    """Resolvidas UMA vez por sessão, contra o ambiente REAL (nenhum monkeypatch de teste
    ainda rodou quando o fixture session-scoped abaixo tira a 1ª fotografia). Mínimo exigido
    pela rodada que criou este guardião (Etapa D, fechamento — passo D8): EQC/pipeline/
    inteira, qualificador/prospeccao_ia/data/, EQC/contracts/."""
    raiz_modulo = Path(__file__).resolve().parent.parent  # tests -> prospeccao_ia
    eqc_root = contrato.eqc_root()
    return [
        ("EQC/pipeline", eqc_root / "pipeline"),
        ("qualificador/prospeccao_ia/data", raiz_modulo / "data"),
        ("EQC/contracts", eqc_root / "contracts"),
    ]


@pytest.fixture(scope="session", autouse=True)
def _guardiao_pastas_producao():
    """Rede de segurança ESTRUTURAL, complementar a `_isolar_persistencia_de_dados`: aquele
    fixture isola por ENUMERAÇÃO (precisa que alguém lembre de somar cada saída nova à
    lista); este aqui não depende de lembrete nenhum -- fotografa nome+tamanho das pastas de
    produção antes da suíte inteira e de novo depois, e falha nomeando qualquer arquivo
    criado, apagado ou alterado. Roda mesmo se algum teste tiver falhado antes (teardown de
    fixture de sessão sempre roda ao final da sessão)."""
    pastas = _pastas_producao()
    antes = guardiao.fotografar(pastas)
    yield
    depois = guardiao.fotografar(pastas)
    linhas = guardiao.diferencas(antes, depois)
    if linhas:
        pytest.fail(guardiao.mensagem_de_falha(linhas), pytrace=False)


@pytest.fixture(autouse=True)
def _isolar_persistencia_de_dados(tmp_path, monkeypatch):
    """Rede de segurança estrutural pra suíte inteira: NENHUM teste pode escrever em data/
    real, mesmo que esqueça de isolar os caminhos manualmente. autouse=True aplica isto a
    TODO teste, sem exceção -- redireciona os PATH_* de main.py pra um tmp_path novo a cada
    teste, antes de qualquer coisa do teste rodar.

    Um teste que faz seu próprio monkeypatch.setattr(main_mod, "PATH_X", ...) simplesmente
    sobrescreve isto por cima (LIFO do monkeypatch) -- fica isolado em dobro, nunca em menos.
    Testes que não usam main.py (ex.: test_website_analyzer.py) não são afetados: isto só
    seta atributos de módulo, não executa nada.

    Isolamento por CÓDIGO, não por disciplina de cada teste -- é o que garante a propriedade
    mesmo pra testes futuros que esqueçam de isolar."""
    monkeypatch.setattr(main_mod, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main_mod, "PATH_COLETADOS", str(tmp_path / "leads_coletados.json"))
    monkeypatch.setattr(main_mod, "PATH_QUALIFICADOS", str(tmp_path / "leads_qualificados.json"))
    monkeypatch.setattr(main_mod, "PATH_REPROVADOS", str(tmp_path / "leads_reprovados.json"))
    monkeypatch.setattr(main_mod, "PATH_COM_SITE", str(tmp_path / "leads_com_site.json"))
    monkeypatch.setattr(main_mod, "PATH_IMPORT_META", str(tmp_path / "_import_meta.json"))
    # A saída não tem mais path fixo -- vai para contrato.output_dir() (env). Isola aqui.
    monkeypatch.setenv("QUALIFICADOR_OUTPUT_DIR", str(tmp_path / "_saida"))
    # Idem pra saída humana (D6b): sem isto, fase_saida() grava CSVs de ensaio na pasta
    # oficial real (EQC/pipeline/saidas-humanas/) -- achado da supervisão, 23/09/2026,
    # reproduzido rodando só esta suíte com a pasta vazia antes e dois CSVs depois. A
    # ausência deste item era exatamente o "nono esquecido" que o D6 introduziu: a suíte
    # passava igual, só que sujando a pasta real. O guardião de _isolamento_producao.py
    # (abaixo) é a rede que pega a PRÓXIMA saída nova que alguém esquecer de somar aqui.
    monkeypatch.setenv(saida_humana.ENV_OUTPUT_DIR, str(tmp_path / "_saida_humana"))
    # A fase de renderizacao (navegador, ~1 min por site) e DESLIGADA por padrao. Um RENDER_ENABLED
    # esquecido no shell de quem roda a suite nao pode ligar navegador dentro de um teste.
    monkeypatch.delenv("RENDER_ENABLED", raising=False)


def _lead(**overrides):
    base = {
        "place_id": "place_1",
        "nome": "Clínica Ejemplo",
        "cidade": "Sevilla",
        "endereco": "Calle Falsa 123",
        "nota_google": 4.8,
        "review_count": 180,
        "reputation_signal": "strong",
        "website": None,
        "website_status": "not_listed_google_maps",
        "telefone": "612345678",
        "email": "contacto@ejemplo.es",
        "instagram": "@ejemplo",
        "facebook": None,
        "nicho": "Fisioterapeuta",
        "google_maps_url": "https://maps.google.com/?cid=1",
    }
    base.update(overrides)
    return base


@pytest.fixture
def lead_excelente_sem_site():
    return _lead(place_id="p1", nome="Fisio Excelente", nota_google=4.9, review_count=250, instagram="@fisio")


@pytest.fixture
def lead_ruim_sem_site():
    return _lead(place_id="p2", nome="Fisio Fraca", nota_google=3.1, review_count=3, instagram=None)


@pytest.fixture
def lead_com_site():
    return _lead(place_id="p3", nome="Fisio Com Site", website="https://fisiocomsite.es", website_status="listed")


@pytest.fixture
def lead_dados_ausentes():
    return _lead(place_id="p4", nome="Empresa Desconhecida", nota_google=None, review_count=None,
                 telefone="612000000", email=None, instagram=None, reputation_signal="unknown")


@pytest.fixture
def lead_sem_contato_nem_sinal():
    return _lead(place_id="p5", nome="Sem Sinal Nenhum", nota_google=None, review_count=None,
                 telefone=None, email=None, instagram=None, reputation_signal="unknown")


@pytest.fixture
def copy_output_valido():
    return {
        "whatsapp": "Hola! Vi que tenéis muy buena reputación en Sevilla. ¿Tenéis página web propia?",
        "email_subject": "Sobre vuestra presencia online",
        "email": "Hola, vi vuestra ficha en Google Maps y me llamó la atención la buena reputación que tenéis. ¿Contáis con página web propia?",
    }


# --- Navegador e servidor local, compartilhados (Etapa C) ----------------------------------------
# UMA definicao para a suite inteira: o Playwright sincrono nao aninha, entao duas fixtures de
# sessao em modulos diferentes abririam dois e a segunda falharia.

@pytest.fixture(scope="session")
def base_url():
    import servidor_local
    servidor = servidor_local.iniciar()
    yield f"http://127.0.0.1:{servidor.server_address[1]}"
    servidor.shutdown()


@pytest.fixture(scope="session")
def pw():
    """Playwright + Chromium locais. Sem eles, os testes que dependem desta fixture sao PULADOS,
    com o motivo, nunca aprovados por omissao."""
    import site_renderizado as sr
    try:
        contexto = sr.abrir_playwright()
        playwright = contexto.__enter__()
    except sr.PlaywrightIndisponivelError as e:
        pytest.skip(f"Playwright indisponivel neste ambiente: {e}")
    try:
        navegador = playwright.chromium.launch(headless=True)
        navegador.close()
    except Exception as e:
        contexto.__exit__(None, None, None)
        pytest.skip(f"Chromium nao inicia neste ambiente: {str(e)[:120]}")
    yield playwright
    contexto.__exit__(None, None, None)


@pytest.fixture(scope="session")
def medir(pw, base_url, tmp_path_factory):
    """Roda _fetch_dispositivo contra uma rota do servidor local e cacheia o resultado (dict, via
    asdict) por (rota, dispositivo). Usada por test_site_renderizado.py e test_caminho_contato.py."""
    import site_renderizado as sr
    pasta = tmp_path_factory.mktemp("capturas")
    cache = {}

    def _medir(rota, dispositivo="desktop", **kwargs):
        chave = (rota, dispositivo, tuple(sorted(kwargs.items())))
        if chave not in cache:
            import re as _re
            nome = _re.sub(r"\W", "_", rota) or "raiz"
            r = sr._fetch_dispositivo(pw, base_url + rota, dispositivo, nome, pasta, **kwargs)
            cache[chave] = sr.asdict(r)
        return cache[chave]

    _medir.pasta = pasta
    return _medir
