"""Lead cujo campo 'Website' do Maps é na verdade um link de rede social (Instagram/Facebook/...):
decisão deliberada do dono do negócio, não erro de extração (ao contrário do deslocamento de
colunas, ver test_import_colunas_deslocadas.py). Sem esse tratamento, dois problemas: o lead ia
pra Onda 2 e o website_analyzer baixava a página de perfil da rede social como se fosse o site
do negócio (score de oportunidade sem sentido); e se a coluna Instagram/Facebook dedicada tivesse
vindo vazia, o link de contato real ficava soterrado dentro de 'website', invisível pro filtro de
contatabilidade da Onda 1 (lead_qualification.filtrar_contactabilidade_onda1).

Achado real: 6 dos 103 leads do CSV de 2026-09-02 tinham link de Facebook/Instagram no campo
Website (Centro Dental Ficticio Uno, Dra. Profesional Ficticia, Odontología Ficticia Dos, Clínica dental
Ficticia Tres, FICTICIOTEX -- esse é site próprio, falso positivo evitado, ver teste de substring abaixo
--, Clínica Dental Ficticia Cuatro).
"""
from agent_coletor import AgentColetor, _e_link_de_rede_social


def _linha(**overrides):
    linha = {
        "Name": "Clínica Ejemplo", "Phone": "960000107", "Website": "", "Email": "",
        "Instagram": "", "Facebook": "",
        "Fulladdress": "C/ Ficticia, 1, 03000 Alacant, Alicante",
        "Street": "C/ Ficticia", "Municipality": "83, 03013 Alacant, Alicante",
        "Categories": "Clínica Dental", "Review Count": "50", "Average Rating": "4.5",
        "Place Id": "place_ok", "Google Maps URL": "https://maps.google.com/?cid=1",
    }
    linha.update(overrides)
    return linha


# --- Detecção do domínio, isolada -------------------------------------------------------------

def test_dominio_social_nao_e_substring_solto():
    """O bug que quase subiu: 'x.com' como substring bate dentro de 'ficticiotex.com'. A checagem
    tem que ser por domínio (host inteiro ou sufixo '.dominio'), nunca 'dominio in url'."""
    assert _e_link_de_rede_social("http://www.ficticiotex.com/") is None


def test_dominio_facebook_detectado_com_e_sem_www():
    assert _e_link_de_rede_social("https://www.facebook.com/centrodentalficticiouno/timeline") == "facebook.com"
    assert _e_link_de_rede_social("https://facebook.com/odontologia.ficticia.general") == "facebook.com"


def test_dominio_instagram_detectado_com_query_string():
    assert _e_link_de_rede_social("https://instagram.com/odontologiaficticiaintegral?igshid=abc") == "instagram.com"


def test_subdominio_de_rede_social_tambem_detectado():
    """m.facebook.com é Facebook igual -- sufixo '.facebook.com' tem que bater."""
    assert _e_link_de_rede_social("https://m.facebook.com/algumaclinica") == "facebook.com"


def test_site_proprio_normal_nao_e_rede_social():
    assert _e_link_de_rede_social("https://clinicaficticia-doce.com/") is None


def test_url_vazia_ou_none_nao_quebra():
    assert _e_link_de_rede_social("") is None
    assert _e_link_de_rede_social(None) is None


# --- Efeito no lead montado --------------------------------------------------------------------

def test_link_de_facebook_no_website_vira_onda_1():
    lead = AgentColetor._montar_lead(_linha(Website="https://www.facebook.com/clinicaexemplo"))
    assert lead["website_status"] == "not_listed_google_maps"


def test_link_de_facebook_faz_backfill_do_campo_facebook_se_vazio():
    lead = AgentColetor._montar_lead(_linha(Website="https://www.facebook.com/clinicaexemplo", Facebook=""))
    assert lead["facebook"] == "https://www.facebook.com/clinicaexemplo"


def test_link_de_instagram_faz_backfill_do_campo_instagram_se_vazio():
    lead = AgentColetor._montar_lead(_linha(Website="https://instagram.com/clinicaexemplo", Instagram=""))
    assert lead["instagram"] == "https://instagram.com/clinicaexemplo"


def test_backfill_nao_sobrescreve_campo_ja_preenchido():
    """Caso real (FICTICIOTEX): Website é site próprio, mas se fosse rede social e a coluna
    dedicada já veio com outro valor da ficha do Maps, esse valor original manda -- nunca
    sobrescrever dado que já veio direto da fonte certa."""
    lead = AgentColetor._montar_lead(_linha(
        Website="https://www.facebook.com/profile.php?id=100000000000001",
        Facebook="https://www.facebook.com/people/nome-oficial-da-pagina",
    ))
    assert lead["facebook"] == "https://www.facebook.com/people/nome-oficial-da-pagina"


def test_website_original_e_preservado_para_referencia():
    """O valor cru continua em 'website' -- só o ROTEAMENTO muda, o dado não some (é útil na
    planilha pra saber que aquele contato veio via rede social, não site)."""
    lead = AgentColetor._montar_lead(_linha(Website="https://www.facebook.com/clinicaexemplo"))
    assert lead["website"] == "https://www.facebook.com/clinicaexemplo"


def test_rede_social_sem_campo_proprio_ainda_vira_onda_1():
    """TikTok/LinkedIn/etc. não têm coluna dedicada no schema -- não tem onde fazer backfill,
    mas o roteamento pra Onda 1 continua valendo (não é site próprio de qualquer forma)."""
    lead = AgentColetor._montar_lead(_linha(Website="https://www.tiktok.com/@clinicaexemplo"))
    assert lead["website_status"] == "not_listed_google_maps"
    assert lead["instagram"] is None
    assert lead["facebook"] is None


def test_site_proprio_continua_indo_pra_onda_2_normalmente():
    lead = AgentColetor._montar_lead(_linha(Website="https://clinicaficticia-doce.com/"))
    assert lead["website_status"] == "listed"


def test_sem_website_continua_onda_1_como_antes():
    lead = AgentColetor._montar_lead(_linha(Website=""))
    assert lead["website_status"] == "not_listed_google_maps"
    assert lead["website"] is None


# --- Efeito de ponta a ponta na classificação de campanha ---------------------------------------

def test_classificar_campanha_manda_lead_com_link_social_pra_wave1():
    lead = AgentColetor._montar_lead(_linha(
        Website="https://www.instagram.com/clinicaexemplo", Instagram="", **{"Place Id": "place_social"},
    ))
    wave1, wave2 = AgentColetor._classificar_campanha([lead])
    assert len(wave1) == 1 and len(wave2) == 0
    assert wave1[0]["website_status"] == "not_listed_google_maps"  # é o website_status que roteia
