"""Classificador da classe do site (Etapa C, passo C1). Sem rede.

Prova nas DUAS PONTAS (~/.claude/CLAUDE.md §4):
  - o que deve classificar CERTO classifica (uma classe por categoria da lista, mais proprio e sem_site);
  - o que deve NAO casar nao casa (substring solta, dominio no meio do host, no caminho, na query,
    apex de sufixo) -- incluindo o caso "x.com dentro de ficticiotex.com";
  - controle negativo: a lista e quem decide (config vazio => tudo proprio; injetar um dominio
    muda o resultado) e o caso de substring DISCRIMINA (uma implementacao ingenua o erraria).
"""
import copy
import json
import re

import pytest

import agent_coletor
import site_classificacao as sc
from agent_coletor import AgentColetor


# --- 1. Deve classificar certo ---------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://www.instagram.com/clinica",
    "instagram.com/x",
    "HTTP://M.FACEBOOK.COM/x",
    "https://facebook.com/pagina?ref=1",
    "https://linktr.ee/foo",
    "https://wa.me/34600123456",
    "https://api.whatsapp.com/send?phone=34600123456",
    "https://threads.net/@x",
    "https://pinterest.es/a",
    "https://t.me/canal",
    "https://instagram.com:443/x",
    "instagram.com.",
    "https://clinica.es@instagram.com/x",          # userinfo: quem manda e o host depois do @
])
def test_rede_social(url):
    assert sc.classificar_site(url) == sc.REDE_SOCIAL


@pytest.mark.parametrize("url", [
    "https://www.doctoralia.es/medico/x",
    "booksy.com/es-es/1",
    "https://clinica.treatwell.es",                # subdominio de um dominio da lista
    "https://www.paginasamarillas.es/f/x",
    "//www.doctoralia.es/x",                       # URL relativa ao protocolo
])
def test_portal(url):
    assert sc.classificar_site(url) == sc.PORTAL


@pytest.mark.parametrize("url", [
    "https://clinica.wixsite.com/site",
    "https://x.negocio.site",                      # sufixo
    "https://x.business.site/",                    # sufixo
    "https://algo.myportfolio.com",                # sufixo (so existe como sufixo na origem)
    "https://foo.blogspot.com",
    "http://a.b.wordpress.com",
    "https://clinica.godaddysites.com",
])
def test_construtor(url):
    assert sc.classificar_site(url) == sc.CONSTRUTOR


@pytest.mark.parametrize("url", [
    "https://g.page/x",
    "https://maps.app.goo.gl/abc",
    "https://sites.google.com/view/x",
    "https://www.google.com/maps/place/x",
    "https://goo.gl/maps/x",
    "HTTP://G.PAGE/abc",
])
def test_superficie_google(url):
    assert sc.classificar_site(url) == sc.SUPERFICIE_GOOGLE


@pytest.mark.parametrize("url", [
    "https://fisioficticia-trece.com/",
    "clinicafisio.es",
    "https://www.fisiotherapia.com:8443/x?y=1",
    "https://user:pw@dominio.es/",
    "  https://Clinica.ES  ",
    "https://instagram.com@clinica.es/",           # o host e clinica.es, nao instagram.com
])
def test_proprio(url):
    assert sc.classificar_site(url) == sc.PROPRIO


@pytest.mark.parametrize("url", [
    None, "", "   ", "-", "N/A", "sitio", "http://", "http://.", "http://foo..com", "http://foo bar.com",
    "mailto:a@b.com", "tel:+34600123456", "javascript:void(0)", "file:///C:/x.html", "ftp://x.com", 123,
])
def test_sem_site_quando_nao_ha_host_utilizavel(url):
    assert sc.classificar_site(url) == sc.SEM_SITE


# --- 2. Deve NAO casar -----------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://ficticiotex.com",                        # "x.com" como substring -- o bug que quase subiu
    "http://www.ficticiotex.com/",
    "https://wax.com",
    "https://myinstagram.com",
    "https://notfacebook.com",
    "https://awixsite.com",
    "https://clinicawixsite.com",
    "https://fb.com.evil.es",                      # dominio da lista no MEIO do host
    "https://instagram.com.clinica.es",
    "https://wixsite.com.clinica.es",
    "https://booksy.com.es",
    "https://g.page.evil.es",
    "https://google.com.evil.es",
    "https://clinica.es/?ref=instagram.com",       # na query
    "https://clinica.es/facebook.com",             # no caminho
    "https://clinica.es/wixsite.com/x",            # no caminho
    "https://clinica.es/#instagram.com",           # no fragmento
    "https://negocio.site",                        # apex de um SUFIXO: so os subdominios casam
    "https://business.site",
    "https://myportfolio.com",
])
def test_nao_casa_e_fica_proprio(url):
    assert sc.classificar_site(url) == sc.PROPRIO


def test_substring_ingenua_erraria_o_caso_de_ficticiotex():
    """Nao-vacuidade: prova que o caso 'ficticiotex.com' DISCRIMINA. A checagem ingenua
    ('dominio in url') o classificaria como rede social; a real, nao."""
    def ingenua(url):
        return any(d in url for d in ("x.com", "instagram.com", "facebook.com"))

    assert ingenua("https://ficticiotex.com") is True
    assert sc.classificar_site("https://ficticiotex.com") == sc.PROPRIO


# --- 3. Controle negativo: a lista e quem decide ---------------------------------------------

def _config_minima(tmp_path, nome="vazia.json", categorias_alteradas=None):
    """Lista valida e VAZIA. Cada nome de arquivo e um caminho novo: o carregador faz cache por caminho."""
    base = {
        "fontes": {"teste": {"arquivo": "a.py", "linhas": "1-2", "copiado_em": "2026-09-20"}},
        "categorias": {
            "rede_social": {"dominios": [], "sufixos": []},
            "portal": {"dominios": [], "sufixos": []},
            "construtor": {"dominios": [], "sufixos": []},
            "superficie_google": {"dominios": [], "sufixos": []},
        },
    }
    base["categorias"].update(categorias_alteradas or {})
    caminho = tmp_path / nome
    caminho.write_text(json.dumps(base), encoding="utf-8")
    return str(caminho)


def _com(categorias_alteradas, tmp_path):
    return _config_minima(tmp_path, "com_injecao.json", categorias_alteradas)


def test_lista_vazia_classifica_tudo_como_proprio(tmp_path):
    cfg = _config_minima(tmp_path)
    for url in ("https://instagram.com/x", "https://www.doctoralia.es/x", "https://a.wixsite.com"):
        assert sc.classificar_site(url, cfg) == sc.PROPRIO


def test_injetar_um_dominio_muda_o_resultado_duas_pontas(tmp_path):
    url = "https://clinica-x.es/agenda"
    assert sc.classificar_site(url, _config_minima(tmp_path)) == sc.PROPRIO           # ausente antes
    injetado = _com({"portal": {"dominios": [{"valor": "clinica-x.es", "origem": ["teste"]}],
                                "sufixos": []}}, tmp_path)
    assert sc.classificar_site(url, injetado) == sc.PORTAL                             # presente depois


def test_sufixo_injetado_casa_subdominio_e_nao_o_apex(tmp_path):
    cfg = _com({"construtor": {"dominios": [], "sufixos": [{"valor": ".meusite.xyz", "origem": ["teste"]}]}},
               tmp_path)
    assert sc.classificar_site("https://loja.meusite.xyz", cfg) == sc.CONSTRUTOR
    assert sc.classificar_site("https://meusite.xyz", cfg) == sc.PROPRIO


# --- 4. A lista real: integridade e proveniencia ----------------------------------------------

def test_lista_real_carrega_e_tem_as_quatro_categorias():
    dominios = sc.carregar_dominios()
    assert set(dominios) == set(sc.CATEGORIAS_DA_LISTA)
    for categoria, bloco in dominios.items():
        assert bloco["dominios"], f"{categoria} sem dominios"


def test_cada_entrada_diz_de_onde_veio_e_a_fonte_tem_arquivo_linhas_e_data():
    bruto = json.load(open(sc.CAMINHO_CONFIG, encoding="utf-8"))
    for id_fonte, fonte in bruto["fontes"].items():
        assert fonte["arquivo"] and fonte["linhas"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", fonte["copiado_em"]), id_fonte
    for categoria, bloco in bruto["categorias"].items():
        for tipo in ("dominios", "sufixos"):
            for e in bloco[tipo]:
                assert e["origem"] and all(o in bruto["fontes"] for o in e["origem"]), (categoria, e)


def test_fechamento_da_copia_pelas_contagens_de_origem():
    """Fechamento aritmetico da copia (18/09 do global: a unidade e a que pode se perder). Se alguem
    apagar uma entrada copiada, este teste acusa -- atualize os numeros CONSCIENTEMENTE ao editar."""
    bruto = json.load(open(sc.CAMINHO_CONFIG, encoding="utf-8"))
    contagem = {}
    for bloco in bruto["categorias"].values():
        for tipo in ("dominios", "sufixos"):
            for e in bloco[tipo]:
                for o in e["origem"]:
                    contagem[o] = contagem.get(o, 0) + 1
    assert contagem == {
        "extrator:PLATFORM_DOMAINS": 50,
        "extrator:PLATFORM_DOMAIN_SUFFIXES": 14,
        "qualificador:DOMINIOS_REDE_SOCIAL": 15,
    }
    for id_fonte, fonte in bruto["fontes"].items():
        assert fonte["entradas_na_origem"] == contagem[id_fonte], id_fonte


def test_cada_entrada_da_lista_classifica_na_propria_categoria():
    """Toda entrada, ela mesma e um subdominio dela; todo sufixo, so o subdominio (nao o apex)."""
    for categoria, bloco in sc.carregar_dominios().items():
        for d in bloco["dominios"]:
            assert sc.classificar_site(f"https://{d}/") == categoria, d
            assert sc.classificar_site(f"https://loja.{d}/") == categoria, d
        for s in bloco["sufixos"]:
            assert sc.classificar_site(f"https://x{s}/") == categoria, s
    # o apex de cada sufixo que NAO e tambem dominio da lista fica "proprio"
    todos_dominios = {d for b in sc.carregar_dominios().values() for d in b["dominios"]}
    for bloco in sc.carregar_dominios().values():
        for s in bloco["sufixos"]:
            if s[1:] not in todos_dominios:
                assert sc.classificar_site(f"https://{s[1:]}/") == sc.PROPRIO, s


def test_toda_a_lista_do_agent_coletor_e_rede_social_aqui():
    """Consistencia entre as duas listas do QUALIFICADOR: a que ROTEIA (agent_coletor) e a copia."""
    for d in agent_coletor.DOMINIOS_REDE_SOCIAL:
        assert sc.classificar_site(f"https://{d}/x") == sc.REDE_SOCIAL, d
        assert sc.classificar_site(f"https://www.{d}") == sc.REDE_SOCIAL, d


@pytest.mark.parametrize("url", [
    "https://www.facebook.com/a", "https://ficticiotex.com", "http://instagram.com/x", "https://clinica.es",
    "https://linktr.ee/x", "https://x.com/y", "https://notx.com",
])
def test_concorda_com_o_detector_do_agent_coletor_em_rede_social(url):
    assert (agent_coletor._e_link_de_rede_social(url) is not None) == (sc.classificar_site(url) == sc.REDE_SOCIAL)


# --- 5. Lista invalida: falha alta (controles negativos do carregador) ------------------------

def _base_valida():
    return json.loads(json.dumps({
        "fontes": {"teste": {"arquivo": "a.py", "linhas": "1-2", "copiado_em": "2026-09-20"}},
        "categorias": {
            "rede_social": {"dominios": [{"valor": "a.com", "origem": ["teste"]}], "sufixos": []},
            "portal": {"dominios": [], "sufixos": []},
            "construtor": {"dominios": [], "sufixos": [{"valor": ".b.site", "origem": ["teste"]}]},
            "superficie_google": {"dominios": [], "sufixos": []},
        },
    }))


def test_base_valida_carrega(tmp_path):
    p = tmp_path / "ok.json"
    p.write_text(json.dumps(_base_valida()), encoding="utf-8")
    assert sc.classificar_site("https://loja.a.com", str(p)) == sc.REDE_SOCIAL


def _sem_categoria(d):
    del d["categorias"]["portal"]


def _categoria_extra(d):
    d["categorias"]["outra"] = {"dominios": [], "sufixos": []}


def _com_esquema(d):
    d["categorias"]["portal"]["dominios"].append({"valor": "https://x.com", "origem": ["teste"]})


def _maiuscula(d):
    d["categorias"]["portal"]["dominios"].append({"valor": "Booksy.com", "origem": ["teste"]})


def _com_www(d):
    d["categorias"]["portal"]["dominios"].append({"valor": "www.booksy.com", "origem": ["teste"]})


def _sufixo_sem_ponto(d):
    d["categorias"]["construtor"]["sufixos"].append({"valor": "c.site", "origem": ["teste"]})


def _dominio_sem_ponto(d):
    d["categorias"]["portal"]["dominios"].append({"valor": "booksy", "origem": ["teste"]})


def _origem_desconhecida(d):
    d["categorias"]["portal"]["dominios"].append({"valor": "booksy.com", "origem": ["nao-existe"]})


def _sem_origem(d):
    d["categorias"]["portal"]["dominios"].append({"valor": "booksy.com", "origem": []})


def _repetido_entre_categorias(d):
    d["categorias"]["portal"]["dominios"].append({"valor": "a.com", "origem": ["teste"]})


def _repetido_na_categoria(d):
    d["categorias"]["rede_social"]["dominios"].append({"valor": "a.com", "origem": ["teste"]})


def _sem_fontes(d):
    d["fontes"] = {}


def _fonte_sem_data(d):
    d["fontes"]["teste"]["copiado_em"] = ""


@pytest.mark.parametrize("quebra", [
    _sem_categoria, _categoria_extra, _com_esquema, _maiuscula, _com_www, _sufixo_sem_ponto,
    _dominio_sem_ponto, _origem_desconhecida, _sem_origem, _repetido_entre_categorias,
    _repetido_na_categoria, _sem_fontes, _fonte_sem_data,
], ids=lambda f: f.__name__)
def test_lista_invalida_falha_alto(tmp_path, quebra):
    dados = copy.deepcopy(_base_valida())
    quebra(dados)
    p = tmp_path / "ruim.json"
    p.write_text(json.dumps(dados), encoding="utf-8")
    with pytest.raises(sc.ConfigDominiosInvalidaError):
        sc.classificar_site("https://x.es", str(p))


def test_arquivo_ausente_e_json_quebrado_falham_alto(tmp_path):
    with pytest.raises(sc.ConfigDominiosInvalidaError):
        sc.classificar_site("https://x.es", str(tmp_path / "nao-existe.json"))
    ruim = tmp_path / "quebrado.json"
    ruim.write_text("{nao e json", encoding="utf-8")
    with pytest.raises(sc.ConfigDominiosInvalidaError):
        sc.classificar_site("https://x.es", str(ruim))


# --- 6. Sem rede -----------------------------------------------------------------------------

_PROIBIDOS = ("urllib.request", "socket", "http.client", "requests", "playwright", "ssl", "anthropic")


def _imports_proibidos(fonte):
    achados = []
    for linha in fonte.splitlines():
        if linha.strip().startswith(("import ", "from ")):
            achados += [t for t in _PROIBIDOS if re.search(rf"\b{re.escape(t)}\b", linha)]
    return achados


def test_modulo_nao_importa_rede_nem_llm():
    import inspect
    assert _imports_proibidos(inspect.getsource(sc)) == []


def test_o_detector_de_imports_proibidos_funciona_nas_duas_pontas():
    assert _imports_proibidos("import os\nfrom urllib.parse import urlsplit\n") == []
    assert _imports_proibidos("import os\nimport urllib.request\n") == ["urllib.request"]


# --- 7. A classe no dado interno do lead; roteamento intocado ---------------------------------

def _linha(**overrides):
    linha = {
        "Name": "Clinica Ejemplo", "Phone": "960000107", "Website": "", "Email": "",
        "Instagram": "", "Facebook": "",
        "Fulladdress": "C/ Ficticia, 1, 03000 Alacant, Alicante",
        "Street": "C/ Ficticia", "Municipality": "83, 03013 Alacant, Alicante",
        "Categories": "Clinica Dental", "Review Count": "50", "Average Rating": "4.5",
        "Place Id": "place_ok", "Google Maps URL": "https://maps.google.com/?cid=1",
    }
    linha.update(overrides)
    return linha


@pytest.mark.parametrize("website, classe, status", [
    ("https://fisioficticia-trece.com/", "proprio", "listed"),
    ("https://www.doctoralia.es/x", "portal", "listed"),                # portal AINDA e "listed": roteamento intocado
    ("https://clinica.wixsite.com/x", "construtor", "listed"),          # idem
    ("https://sites.google.com/view/x", "superficie_google", "listed"),
    ("https://www.instagram.com/clinica", "rede_social", "not_listed_google_maps"),
    ("", "sem_site", "not_listed_google_maps"),
])
def test_classe_gravada_no_lead_sem_mudar_o_roteamento(website, classe, status):
    lead = AgentColetor._montar_lead(_linha(Website=website))
    assert lead["classe_site"] == classe
    assert lead["website_status"] == status


def test_a_classe_atravessa_a_fronteira_do_contrato_como_campo_explicito():
    import output_json
    import inspect
    assert "classe_site" in inspect.getsource(output_json)
