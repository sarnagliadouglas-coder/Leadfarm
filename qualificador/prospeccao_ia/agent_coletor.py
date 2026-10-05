import csv
import json
import os
import re
from urllib.parse import urlparse

import campanha as campanha_mod
import csv_contrato
import site_classificacao
import telefone_utils

# Alguns exports colam o telefone no fim do endereço por bug da ferramenta de extração
# (ex: "...Bajo600 00 01 11", ou "...Ficticia, 43960 00 01 07" onde "43" é o nº do prédio
# grudado ANTES do telefone). Por isso pegamos um bloco de dígitos e usamos os ÚLTIMOS 9,
# não os primeiros — Espanha usa números de telefone com exatamente 9 dígitos.
BLOCO_DIGITOS_RE = re.compile(r"(?:\d[\s.]?){6,}")

# A coluna "Municipality" do CSV vem errada quando o endereço não inclui CEP+cidade no final
# (ex: "C. Francisco Carratalá Cernuda, 31" -> Municipality = "31", o número do prédio, não a
# cidade). CEP espanhol tem 5 dígitos e sempre vem seguido do nome da cidade — só confiamos na
# cidade quando esse padrão aparece; senão fica None (honesto) em vez de lixo.
CIDADE_APOS_CEP_RE = re.compile(r"\d{5}\s+([A-Za-zÀ-ÿ][\wÀ-ÿ\s.'-]*)$")

# Em negócios com 0 avaliações, a ferramenta de extração às vezes desloca colunas e o texto
# "sem avaliação" (em vários idiomas, dependendo do locale do navegador usado) vaza pra dentro
# de "Categories" no lugar da categoria real. Sem esse filtro, isso vira a "categoria" do lead
# e contamina o prompt do qualificador (já vimos isso puxar o idioma da copy pro português).
CATEGORIA_INVALIDA_RE = re.compile(
    r"no\s*hay\s*rese|nenhuma\s*avalia|no\s*reviews|añadir\s*horario|añadir\s*sitio\s*web",
    re.IGNORECASE,
)

# Outros marcadores de linha deslocada (04/10/2026, CSV de abogados): glifo de ícone (caractere
# Unicode de uso privado) ou texto de horário ("Apertura: 9:00 (lun)") no lugar da categoria.
# Lista em config, não no código. Mesmo mecanismo de recuperação de CATEGORIA_INVALIDA_RE.
CAMINHO_CONFIG_LINHA_DESLOCADA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "linha_deslocada.json")
MOTIVO_LINHA_DESLOCADA = "linha_deslocada_irrecuperavel"
_config_linha_deslocada = {}


def _carregar_config_linha_deslocada(caminho=None):
    """Lida uma vez por caminho. Ausente/inválida levanta (o import não segue com detecção
    pela metade; main.importar_csv não grava nada)."""
    caminho = caminho or CAMINHO_CONFIG_LINHA_DESLOCADA
    if caminho not in _config_linha_deslocada:
        with open(caminho, "r", encoding="utf-8") as f:
            config = json.load(f)
        _config_linha_deslocada[caminho] = {
            "uso_privado": bool(config.get("categoria_com_caractere_de_uso_privado")),
            "regex": [re.compile(r, re.IGNORECASE) for r in config.get("marcadores_regex") or []],
        }
    return _config_linha_deslocada[caminho]


def _tem_caractere_de_uso_privado(texto):
    return any(0xE000 <= ord(c) <= 0xF8FF or 0xF0000 <= ord(c) <= 0x10FFFD for c in texto)


def padrao_de_linha_deslocada(categoria):
    """Nome do padrão de deslocamento que a 1ª categoria revela, ou None (linha íntegra)."""
    if not categoria:
        return None
    if CATEGORIA_INVALIDA_RE.search(categoria):
        return "sem_avaliacao"
    config = _carregar_config_linha_deslocada()
    if config["uso_privado"] and _tem_caractere_de_uso_privado(categoria):
        return "caractere_uso_privado"
    if any(r.search(categoria) for r in config["regex"]):
        return "marcador_config"
    return None


def _campos_suspeitos_na_linha_deslocada(linha):
    """Numa linha deslocada, confere se telefone, site, avaliações e nota têm a FORMA certa.
    Campo vazio é aceito (ausência real); campo preenchido com forma errada indica que outra
    coluna também deslocou -- e o lead não segue com dado trocado."""
    suspeitos = []
    telefone = (linha.get("Phone") or "").strip()
    if telefone:
        candidatos = [telefone]
    else:
        candidatos = [c.strip() for c in re.split(r"[,;/|\n]+", linha.get("Phones") or "") if c.strip()]
    for candidato in candidatos:
        numero = telefone_utils.numero_nacional_espanhol(candidato)
        if not (numero.isdigit() and len(numero) == 9):
            suspeitos.append("telefone")
            break
    website = (linha.get("Website") or "").strip()
    if website and site_classificacao._host(website) is None:
        suspeitos.append("website")
    avaliacoes = (linha.get("Review Count") or "").strip()
    if avaliacoes and not avaliacoes.isdigit() and not CATEGORIA_INVALIDA_RE.search(avaliacoes):
        suspeitos.append("avaliacoes")
    nota = (linha.get("Average Rating") or "").strip()
    if nota:
        try:
            if not 0 <= float(nota.replace(",", ".")) <= 5:
                suspeitos.append("nota")
        except ValueError:
            suspeitos.append("nota")
    return suspeitos


# Filtro comercial em Python (custo $0): só exclui organizações claramente fora do perfil de
# cliente (autônomos/profissionais liberais). Não exclui termos genéricos como "clínica" —
# clínicas pequenas são exatamente o cliente ideal. Lista de partida, editável.
#
# Checado só contra a CATEGORIA que o próprio Google atribuiu (nicho), nunca contra o nome
# livre do negócio — um "Centro de fisioterapia Hospital del Rey" é uma clínica pequena cujo
# nome referencia um bairro de Alicante, não um hospital de verdade. A categoria do Google
# ("Clínica de Fisioterapia") é um sinal muito mais confiável do tipo real do negócio.
TERMOS_EXCLUSAO_COMERCIAL = [
    "hospital",
    "universidad", "universidade",
    "fundación", "fundacion", "fundação",
    "ayuntamiento", "diputación", "diputacion", "generalitat", "ministerio", "conselleria",
    "seguridad social",
    "grupo hospitalario",
    "franquicia", "franquia",
]

# Sufixos jurídicos de empresa grande — esses sim valem checar no NOME (raramente aparecem
# numa referência de bairro/rua, ao contrário de "hospital").
SUFIXOS_EMPRESA_GRANDE = [" s.a.", " s.a,", " s.l.u.", " s.l.p.", " grupo "]

# Alguns donos de negócio cadastram o link do Instagram/Facebook no campo "Website" da ficha do
# Maps por não terem site próprio -- decisão deliberada deles, não erro de extração (ao
# contrário do deslocamento de colunas acima). Se deixarmos passar como "site" de verdade, dois
# problemas: (1) o lead vai pra Onda 2, que baixa o HTML e analisa como se fosse o site do
# negócio -- vai ler a página de login/perfil da rede social e gerar um "score de oportunidade"
# sem sentido nenhum; (2) o link de contato real (a rede social) fica soterrado dentro de
# "website", que ninguém olha pra decidir contatabilidade -- ver filtrar_contactabilidade_onda1
# em lead_qualification.py, que só olha os campos instagram/facebook.
#
# Checado por DOMÍNIO exato (host inteiro, sem 'www.') ou subdomínio dele -- nunca por substring
# solto. "x.com" como substring bateria dentro de "ficticiotex.com" (bug pego em teste antes de
# subir: ver test_dominio_social_nao_e_substring_solto).
DOMINIOS_REDE_SOCIAL = {
    "facebook.com", "instagram.com", "tiktok.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "youtu.be",
    "wa.me", "api.whatsapp.com", "whatsapp.com",
    "linktr.ee", "threads.net", "t.me", "telegram.me",
}

# Das redes acima, só instagram/facebook têm campo próprio no schema interno -- as outras
# (tiktok, linkedin, ...) não têm onde ir, ficam só reclassificando a campanha pra Onda 1 e
# preservadas em 'website' como referência.
DOMINIO_PARA_CAMPO_PROPRIO = {"instagram.com": "instagram", "facebook.com": "facebook"}

# Campos crus da ficha do Google Business Profile (GBP). O extractor passou a exportá-los
# nesta janela; ANTES eram lidos e descartados (ou nem liam). Aqui só são LIDOS e anexados
# ao lead -- a interpretação (o que é lacuna, o que é "não verificado") é 100% de
# gbp_diagnostic.py, não deste módulo. Chave interna por DOMÍNIO (gbp_horario, gbp_reivindicada
# ...), nunca o nome de coluna do extractor -- o extractor tem pendências abertas e vai mudar.
#
# 'Detail Scraped' é o GATE de verificação: distingue "campo vazio porque não existe na ficha"
# de "campo vazio porque o deep-scrape não rodou pra este lead". Sem ele um campo ausente
# engana quem consome. Valor cru preservado; gbp_diagnostic normaliza.
#
# A coluna DERIVADA 'Opportunity' do extractor (detectSharedWebsites etc.) NÃO é lida: ela
# carrega julgamento comercial do EXTRATOR ("Unclaimed = oportunidade alta" etc.) que não
# deve cruzar a fronteira EXTRATOR -> QUALIFICADOR -> COMERCIAL. Removida do contrato de
# saída em contract_version 1.0.0.
GBP_COLUNAS = {
    "gbp_reivindicada": "Claimed",
    "gbp_detalhe_scraped": "Detail Scraped",
    "gbp_horario": "Opening Hours",
    "gbp_descricao": "Description",
    "gbp_faixa_preco": "Price Range",
    "gbp_plus_code": "Plus Code",
    "gbp_dono": "Owner",
    "gbp_foto_destaque": "Featured Image",
}


def _campos_gbp_crus(linha):
    """Lê as colunas de GBP da linha do CSV. Coluna ausente do export (CSV antigo) -> None,
    sem quebrar -- gbp_diagnostic trata None como 'não verificado'."""
    return {chave: ((linha.get(coluna) or "").strip() or None) for chave, coluna in GBP_COLUNAS.items()}


def _dominio_da_url(url):
    """Domínio "raiz" da URL, sem 'www.' -- pra comparar por igualdade/sufixo, nunca por
    substring solto."""
    if not url:
        return None
    bruto = url.strip()
    if not re.match(r"^https?://", bruto, re.IGNORECASE):
        bruto = "http://" + bruto
    host = (urlparse(bruto).netloc or "").lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _e_link_de_rede_social(url):
    """Devolve o domínio de DOMINIOS_REDE_SOCIAL que bateu (host igual ou subdomínio dele), ou
    None. Nunca usa 'in'/regex de substring -- "x.com" não pode bater em "ficticiotex.com"."""
    dominio = _dominio_da_url(url)
    if not dominio:
        return None
    for candidato in DOMINIOS_REDE_SOCIAL:
        if dominio == candidato or dominio.endswith("." + candidato):
            return candidato
    return None


def _classificar_reputacao(nota_google):
    """Sinal simples e interpretável — não um score sofisticado. Reputação é contexto pro
    qualificador, nunca critério de corte aqui no coletor."""
    if nota_google is None:
        return "unknown"
    if nota_google < 3.5:
        return "weak"
    if nota_google < 4.5:
        return "moderate"
    return "strong"


class AgentColetor:
    def coletar_leads_de_csv(self, caminho_csv, campanha=None):
        """Lê o CSV e classifica os leads em Onda 1 (elegível), Onda 2 (fila futura) e
        reprovados. Valida o contrato EXTRATOR -> QUALIFICADOR (sidecar + header) ANTES de
        importar qualquer coisa -- violação de contrato levanta csv_contrato.ContratoCsvInvalido
        e nada é importado.

        `campanha` (dict já validado por campanha.carregar_campanha): cada lead recebe o
        carimbo `campanha_id`/`campanha_nicho`, e o corte de categoria da campanha roda ANTES
        dos filtros comerciais e da separação em ondas -- lead fora do perfil nunca chega a
        nenhuma onda. main.importar_csv sempre passa a campanha; None (uso direto em teste)
        pula carimbo e corte.

        Devolve (wave1, reprovados, wave2, custo, reconciliacao). `reconciliacao` conta o que
        entrou vs. o que sumiu no import (linhas sem Name, dedup interno) -- ver main.importar_csv,
        que completa com o dedup global e imprime a reconciliação."""
        print(f"\n[Coletor] Lendo leads de '{os.path.basename(caminho_csv)}'...")

        sidecar, avisos = csv_contrato.validar_sidecar(caminho_csv)
        colunas, linhas = self._ler_csv(caminho_csv)
        avisos += csv_contrato.validar_header(colunas)
        for aviso in avisos:
            print(f"[Coletor] ⚠️  {aviso}")
        if sidecar:
            print(f"[Coletor] sidecar do EXTRATOR OK (schema_version={sidecar.get('schema_version')}, "
                  f"extensão {sidecar.get('extensao_versao')}, {sidecar.get('linhas_totais')} linha(s), "
                  f"{sidecar.get('linhas_com_deep_scrape')} com deep-scrape).")

        leads_brutos = [self._montar_lead(linha) for linha in linhas]
        sem_nome = sum(1 for l in leads_brutos if l is None)
        validos = [l for l in leads_brutos if l]
        leads_dedup = self._deduplicar(validos)
        dedup_interno = len(validos) - len(leads_dedup)

        # Linha deslocada sem recuperação segura nunca segue com dado trocado (antes de
        # qualquer outro filtro: a categoria dela não é confiável).
        leads_dedup, reprovados_deslocada = self._aplicar_filtro_linha_deslocada(leads_dedup)
        if reprovados_deslocada:
            print(f"[Coletor] {len(reprovados_deslocada)} lead(s) com linha deslocada irrecuperável.")
        if campanha is not None:
            for lead in reprovados_deslocada:
                lead.update(campanha_mod.carimbo(campanha))

        reprovados_categoria = []
        if campanha is not None:
            for lead in leads_dedup:
                lead.update(campanha_mod.carimbo(campanha))
            leads_dedup, reprovados_categoria = self._aplicar_filtro_categoria(leads_dedup, campanha)
            if reprovados_categoria:
                print(f"[Coletor] {len(reprovados_categoria)} lead(s) fora das categorias da campanha "
                      f"'{campanha['id']}'.")

        aprovados, reprovados_comercial = self._aplicar_filtros_comerciais(leads_dedup)
        if reprovados_comercial:
            print(f"[Coletor] {len(reprovados_comercial)} lead(s) reprovado(s) pelos filtros comerciais.")
        reprovados = reprovados_deslocada + reprovados_categoria + reprovados_comercial

        wave1, wave2 = self._classificar_campanha(aprovados)
        print(f"[Coletor] {len(wave1)} lead(s) Onda 1 (sem site listado na ficha).")
        print(f"[Coletor] {len(wave2)} lead(s) Onda 2 (com site listado, guardados pra depois).")
        # Invariante: só fica com website preenchido E status not_listed quem foi reclassificado
        # aqui por ter link de rede social no campo "Website" (o único outro jeito de chegar em
        # not_listed é website vazio, e aí não há o que reportar).
        via_rede_social = [l for l in wave1 if l.get("website")]
        if via_rede_social:
            print(f"[Coletor] {len(via_rede_social)} lead(s) tinham link de rede social (não site próprio) no campo 'Website' -- reclassificados pra Onda 1.")
        print(f"[Coletor] Custo: $0,0000 (sem API)")

        reconciliacao = {
            "linhas_csv": len(linhas),
            "sem_nome": sem_nome,
            "dedup_interno": dedup_interno,
            "para_onda1": len(wave1),
            "para_onda2": len(wave2),
            "reprovados_comercial": len(reprovados_comercial),
            "reprovados_categoria": len(reprovados_categoria),
            "reprovados_linha_deslocada": len(reprovados_deslocada),
        }
        return wave1, reprovados, wave2, 0.0, reconciliacao

    @staticmethod
    def _aplicar_filtro_linha_deslocada(leads):
        """Reprova (motivo linha_deslocada_irrecuperavel) a linha deslocada cuja categoria não
        foi recuperada com segurança ou que tem telefone/site/avaliações/nota com forma errada."""
        aprovados, reprovados = [], []
        for lead in leads:
            info = lead.get("linha_deslocada")
            if info and (not info["categoria_recuperada"] or info["campos_suspeitos"]):
                lead["rejection_reason"] = MOTIVO_LINHA_DESLOCADA
                lead["rejection_detail"] = dict(info)
                reprovados.append(lead)
            else:
                aprovados.append(lead)
        return aprovados, reprovados

    @staticmethod
    def _aplicar_filtro_categoria(leads, campanha):
        """Corte de categoria da campanha ativa (fonte única das categorias no import). Cada
        reprovado leva o motivo e, em `rejection_detail`, a categoria que causou o corte."""
        aprovados, reprovados = [], []
        for lead in leads:
            corte = campanha_mod.motivo_categoria(lead.get("nicho"), campanha)
            if corte:
                motivo, termo = corte
                lead["rejection_reason"] = motivo
                lead["rejection_detail"] = {"categoria": lead.get("nicho"), "termo_excluido": termo,
                                            "campanha_id": campanha["id"]}
                reprovados.append(lead)
            else:
                aprovados.append(lead)
        return aprovados, reprovados

    @staticmethod
    def _ler_csv(caminho_csv):
        """Trabalho braçal em Python: tenta utf-8-sig -> utf-8 -> cp1252, nessa ordem.
        utf-8-sig cobre o caso comum (exports de ferramenta/Chrome saem com BOM UTF-8) e também
        lê UTF-8 sem BOM de forma transparente. cp1252 é o último recurso: quase nunca lança erro
        de decodificação, então só é tentado se os dois primeiros genuinamente falharem — usá-lo
        primeiro mascararia silenciosamente um arquivo UTF-8 mal lido. Se os três falharem, a
        exceção original propaga — sem gravar nada parcialmente corrompido.

        Devolve (fieldnames, linhas) -- o header vai pra validação do contrato."""
        encodings = ["utf-8-sig", "utf-8", "cp1252"]
        ultimo_erro = None
        for encoding in encodings:
            try:
                with open(caminho_csv, "r", encoding=encoding, newline="") as f:
                    leitor = csv.DictReader(f)
                    linhas = list(leitor)
                    colunas = list(leitor.fieldnames or [])
                print(f"[Coletor] CSV decodificado com '{encoding}'.")
                return colunas, linhas
            except (UnicodeDecodeError, UnicodeError) as e:
                ultimo_erro = e
        raise ultimo_erro or ValueError("Não foi possível decodificar o CSV")

    @staticmethod
    def _montar_lead(linha):
        """Mapeia as colunas do export do Google Maps pro schema interno. 'website_status' é
        um FATO sobre a ficha do Maps ('a coluna Website veio vazia'), não uma afirmação sobre
        a realidade do negócio — essa distinção importa lá na copy."""
        nome = (linha.get("Name") or "").strip()
        if not nome:
            return None

        website = (linha.get("Website") or "").strip() or None

        telefone = AgentColetor._resolver_telefone(linha)
        if not telefone:
            telefone = AgentColetor._extrair_telefone_do_endereco(linha)

        email = (linha.get("Email") or linha.get("Emails") or "").strip() or None
        # Emails pode vir com vários separados por vírgula/espaço; fica só o primeiro.
        if email and ("," in email or " " in email):
            email = re.split(r"[,\s]+", email)[0]

        instagram = (linha.get("Instagram") or "").strip() or None
        facebook = (linha.get("Facebook") or "").strip() or None
        # LinkedIn: só transporte de evidência para o COMERCIAL (contract_version 1.1.0).
        # NÃO entra em whatsapp_apto, contactability nem em nenhum score -- mesma leitura
        # crua de Instagram/Facebook, sem o backfill a partir de "Website".
        linkedin = (linha.get("LinkedIn") or "").strip() or None

        # "Website" com link de rede social (ver DOMINIOS_REDE_SOCIAL acima): não é um site
        # próprio, é o dono do negócio apontando pro perfil dele. Onda 1, não Onda 2 -- e se a
        # coluna dedicada (Instagram/Facebook) veio vazia, o link não pode se perder, senão o
        # filtro de contatabilidade da Onda 1 conclui "sem canal" por engano.
        dominio_social = _e_link_de_rede_social(website)
        if dominio_social:
            website_status = "not_listed_google_maps"
            campo_proprio = DOMINIO_PARA_CAMPO_PROPRIO.get(dominio_social)
            if campo_proprio == "instagram" and not instagram:
                instagram = website
            elif campo_proprio == "facebook" and not facebook:
                facebook = website
        else:
            website_status = "listed" if website else "not_listed_google_maps"

        endereco = (linha.get("Fulladdress") or "").strip() or None
        cidade = AgentColetor._extrair_cidade(linha)
        place_id = (linha.get("Place Id") or "").strip() or None
        google_maps_url = (linha.get("Google Maps URL") or "").strip() or None
        gbp_crus = _campos_gbp_crus(linha)

        nota_bruta = (linha.get("Average Rating") or "").strip()
        nota_google = None
        if nota_bruta:
            try:
                nota_google = float(nota_bruta.replace(",", "."))
            except ValueError:
                nota_google = None

        review_bruto = (linha.get("Review Count") or "").strip()
        review_count = None
        if review_bruto:
            try:
                review_count = int(review_bruto)
            except ValueError:
                review_count = None  # texto tipo "No hay reseñas" / "Nenhuma avaliação"

        # Nicho vem da própria linha (não perguntado ao usuário): primeira categoria do Google Maps.
        categorias = (linha.get("Categories") or "").strip()
        nicho = categorias.split(",")[0].strip() if categorias else ""

        linha_deslocada = None
        padrao = padrao_de_linha_deslocada(nicho)
        if padrao:
            # Linha deslocada (CATEGORIA_INVALIDA_RE ou config/linha_deslocada.json): a categoria
            # REAL não sumiu, só mudou de coluna. Antes ela era descartada junto com o lixo.
            recuperada = AgentColetor._recuperar_categoria_deslocada(linha)
            linha_deslocada = {"padrao": padrao, "categoria_recuperada": bool(recuperada),
                               "campos_suspeitos": _campos_suspeitos_na_linha_deslocada(linha)}
            if recuperada:
                nicho = recuperada
                # O que estava em Fulladdress era a categoria, não o endereço -- guardar
                # aquilo como endereço seria gravar dado errado. A cidade já vem None
                # sozinha (Municipality vem vazio nessas linhas) e é irrecuperável.
                endereco = None
            else:
                nicho = ""

        if not nicho:
            # Em espanhol de propósito: esse valor é lido pelo Claude como conteúdo de
            # referência no prompt (não só metadado interno) — ver CATEGORIA_INVALIDA_RE acima.
            nicho = "categoría sin especificar"

        lead = {
            "place_id": place_id,
            "nome": nome,
            "cidade": cidade,
            "endereco": endereco,
            "nota_google": nota_google,
            "review_count": review_count,
            "reputation_signal": _classificar_reputacao(nota_google),
            "website": website,
            "website_status": website_status,
            # Dado interno (Etapa C, passo C1): NAO roteia -- quem roteia e website_status, acima.
            "classe_site": site_classificacao.classificar_site(website),
            "telefone": telefone,
            "email": email,
            "instagram": instagram,
            "facebook": facebook,
            "linkedin": linkedin,
            "nicho": nicho,
            "google_maps_url": google_maps_url,
            **gbp_crus,
        }
        if linha_deslocada:
            # Rastro de auditoria; o corte (se houver) é de _aplicar_filtro_linha_deslocada.
            lead["linha_deslocada"] = linha_deslocada
        return lead

    @staticmethod
    def _resolver_telefone(linha):
        """Resolve o campo interno `telefone` a partir das colunas Phone/Phones.

        1. Phone (singular), se preenchido -- prioridade.
        2. Senão, Phones é dividido em candidatos (vírgula / ponto-e-vírgula /
           barra / quebra de linha) e devolve o PRIMEIRO que é celular espanhol
           (prefixo 6/7 após normalização). Isso corrige o bug antigo, em que
           "Phones" inteiro (ex.: "960000104, 612345678") virava uma string só e
           a normalização concatenava os dígitos das duas variantes antes de
           checar o primeiro dígito -- podendo classificar errado.
        3. Se nenhum candidato for celular, devolve o primeiro candidato mesmo
           assim (fallback histórico preservado).
        4. Nada em Phone/Phones -> None (quem chama tenta _extrair_telefone_do_endereco).
        """
        phone = (linha.get("Phone") or "").strip()
        if phone:
            return phone

        bruto = (linha.get("Phones") or "").strip()
        if not bruto:
            return None

        candidatos = [c.strip() for c in re.split(r"[,;/|\n]+", bruto) if c.strip()]
        if not candidatos:
            return None
        for candidato in candidatos:
            if telefone_utils.e_movel_espanhol(candidato):
                return candidato
        return candidatos[0]

    @staticmethod
    def _recuperar_categoria_deslocada(linha):
        """Nas linhas com 0 avaliações a ferramenta de extração desloca as colunas: o texto
        "sem avaliação" ocupa Categories e a categoria REAL cai em Fulladdress/Street
        (Municipality vem vazio). O deslocamento é determinístico -- medido em 9 de 9 linhas
        afetadas nos CSVs já importados, recuperando "Clínica de Fisioterapia" (5),
        "Fisioterapeuta" (2), "Dentista" e "Centro médico".

        Duas guardas, porque uma só não basta (o teste de rua sem número passava):

        1. Municipality VAZIO -- assinatura estrutural do deslocamento. Medido: vazio em 9/9
           das linhas deslocadas. Não é suficiente sozinho (24/333 linhas íntegras também têm
           Municipality vazio), mas é necessário.
        2. O candidato não pode parecer endereço: sem número, sem vírgula e sem a barra das
           abreviaturas de logradouro ("C/", "Avda/"). Medido: 0/9 dos candidatos válidos têm
           barra, contra 15/333 dos endereços íntegros -- ou seja, a barra nunca custa uma
           recuperação legítima e barra "C/ Mayor", que passaria nos outros dois testes."""
        if (linha.get("Municipality") or "").strip():
            return None

        for campo in ("Fulladdress", "Street"):
            candidato = (linha.get(campo) or "").strip()
            if not candidato or len(candidato) > 60:
                continue
            if "," in candidato or "/" in candidato or any(c.isdigit() for c in candidato):
                continue
            if padrao_de_linha_deslocada(candidato):
                continue
            return candidato
        return None

    @staticmethod
    def _extrair_cidade(linha):
        """Só confia na cidade quando ela aparece depois de um CEP (padrão confiável). A coluna
        Municipality sozinha é pouco confiável nesse export — ver CIDADE_APOS_CEP_RE acima."""
        for campo in ("Municipality", "Fulladdress"):
            valor = (linha.get(campo) or "").strip()
            m = CIDADE_APOS_CEP_RE.search(valor)
            if m:
                return m.group(1).strip().rstrip(",").strip()
        return None

    @staticmethod
    def _extrair_telefone_do_endereco(linha):
        """Último recurso: recupera o telefone que vazou pro campo de endereço, quando
        Phone/Phones vêm vazios (ver comentário do BLOCO_DIGITOS_RE acima)."""
        for campo in ("Fulladdress", "Street"):
            valor = (linha.get(campo) or "").strip()
            for m in BLOCO_DIGITOS_RE.finditer(valor):
                digitos = re.sub(r"\D", "", m.group())
                if len(digitos) >= 9:
                    ultimos9 = digitos[-9:]
                    return f"{ultimos9[0:3]} {ultimos9[3:5]} {ultimos9[5:7]} {ultimos9[7:9]}"
        return None

    @staticmethod
    def _deduplicar(leads):
        """Trabalho braçal em Python: dedup por place_id (identificador real do Google)."""
        vistos = set()
        leads_limpos = []
        for lead in leads:
            chave = lead.get("place_id") or lead["nome"].lower()
            if chave in vistos:
                continue
            vistos.add(chave)
            leads_limpos.append(lead)
        return leads_limpos

    @staticmethod
    def _aplicar_filtros_comerciais(leads):
        """Único corte em Python. NUNCA por nota — reputação é sinal (reputation_signal), não
        critério de corte. Reprova só por (a) termo de organização grande demais pro perfil de
        cliente, ou (b) nenhum sinal de contato/realidade do registro (sem telefone, sem email
        E sem nota — não é sobre reputação, é sobre não haver nenhuma evidência de que é um
        negócio ativo e contatável). Nunca reprova silenciosamente: motivo sempre registrado."""
        aprovados, reprovados = [], []
        for lead in leads:
            motivo = AgentColetor._motivo_exclusao_comercial(lead)
            if motivo:
                lead["rejection_reason"] = motivo  # extraído por quem persiste (main.py)
                reprovados.append(lead)
            else:
                aprovados.append(lead)
        return aprovados, reprovados

    @staticmethod
    def _motivo_exclusao_comercial(lead):
        categoria = f" {(lead.get('nicho') or '').lower()} "
        for termo in TERMOS_EXCLUSAO_COMERCIAL:
            if termo in categoria:
                return "large_organization"

        nome = f" {(lead.get('nome') or '').lower()} "
        for sufixo in SUFIXOS_EMPRESA_GRANDE:
            if sufixo in nome:
                return "large_organization"

        if not lead.get("telefone") and not lead.get("email") and lead.get("nota_google") is None:
            return "no_contact_no_signal"
        return None

    @staticmethod
    def _classificar_campanha(leads):
        """A decisão de campanha é NOSSA, baseada no dado bruto (website_status) — não no
        campo 'Opportunity' da extensão, que fica só como sinal auxiliar (repassado ao
        qualificador como contexto, nunca decide sozinho)."""
        wave1, wave2 = [], []
        for lead in leads:
            if lead["website_status"] == "listed":
                wave2.append(lead)
            else:
                wave1.append(lead)
        return wave1, wave2
