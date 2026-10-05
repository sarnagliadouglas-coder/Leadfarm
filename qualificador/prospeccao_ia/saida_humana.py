"""saida_humana.py -- monta e grava o CSV humano (Etapa D, passo D6): as pistas DIRETA e
ESPERA, os leads que NAO atravessam o contrato v2.0.0 (RUMO-COMERCIAL-2026-09 secao 3.1/3.7).
So montagem e gravacao -- nao mexe em contrato, schema nem regua. $0, sem LLM,
determinístico: mesma entrada, mesma saida.

DIRETA = classe_site != "proprio" (sem_site, portal, rede_social, superficie_google,
construtor). Decisao da supervisao, 23/09/2026 (Etapa D, passo D6): o prompt original so
listava sem_site/portal/rede_social; ampliado pras 5 classes nao-proprias porque:
  - superficie_google nao e site do negocio, e pagina gerada pelo proprio Google -- o caso
    mais puro de "precisa de site";
  - construtor (subdominio gratuito) e site de verdade, mas a fase de renderizacao (C4) so
    mede classe_site "proprio" -- um lead de construtor NUNCA teria problema vendavel
    detectado e ficaria preso na ESPERA para sempre, invisivel. Mandar pra DIRETA e o
    tratamento honesto: abordagem a mao, com template, sem estudo caro (mesmo §3.4: sinal
    MEDIO, nao abre a nata sozinho).
Pendencia registrada (nao implementada aqui): se um dia quisermos que leads de construtor
cheguem a nata, a fase de renderizacao precisa deixar de filtrar so por "proprio".

ESPERA = site proprio, sem problema vendavel, que nao virou candidato a triagem visual --
reusa output_json._lead_site() (a MESMA funcao que decide nata/candidatos_triagem no
contrato) pra nunca duplicar essa regra: um lead so entra aqui quando _lead_site() devolve
None pra ele. Por construcao, um lead de nata ou candidato a triagem NUNCA aparece aqui --
_lead_site() so devolve None quando NAO e nenhum dos dois.
"""
import csv
import os
import shutil

import agent_coletor
import contrato
import output_json
import site_classificacao

# --- Colunas do CSV, nesta ordem (Etapa D, passo D6) ---------------------------------------
COLUNAS = (
    "pista", "motivo", "nome", "nicho", "cidade", "telefone", "email", "instagram", "site",
    "classe_site", "avaliacoes", "nota", "google_maps_url", "place_id",
    # Acrescentadas no FIM em 2026-10 (nunca mudar a ordem das anteriores): carimbo da
    # campanha ativa no import, aviso do filtro de redes (rede_multiunidade.py) e a
    # prioridade da Onda 1 como lead_qualification.qualificar_onda1 já calcula.
    "campanha_id", "campanha_nicho", "possivel_mesmo_negocio", "prioridade_rotulo", "prioridade_score",
)

# Valor das colunas de campanha/aviso quando o lead foi importado antes de o campo existir --
# mesmo vocabulário de estado do contrato; nunca valor inventado.
NAO_VERIFICADO = "NAO_VERIFICADO"

PISTA_DIRETA = "direta"
PISTA_ESPERA = "espera"

MOTIVO_POR_CLASSE = {
    site_classificacao.SEM_SITE: "sem site",
    site_classificacao.PORTAL: "site é portal",
    site_classificacao.REDE_SOCIAL: "site é rede social",
    site_classificacao.SUPERFICIE_GOOGLE: "site é página do Google",
    site_classificacao.CONSTRUTOR: "site em construtor gratuito",
}
MOTIVO_ESPERA = "sem problema encontrado"

# RUMO-COMERCIAL-2026-09 §3.6: mínimo pra ocupar a faixa prioritária da Direta.
MIN_AVALIACOES_PRIORITARIA = 10
MIN_NOTA_PRIORITARIA = 3.5

# --- Localização das pastas (Etapa D, passos D6/D6b) -----------------------------------------
# Oficial, dentro do repositório. QUALIFICADOR_SAIDA_HUMANA_OUTPUT_DIR (caminho final) tem
# precedência -- mesmo padrão de QUALIFICADOR_OUTPUT_DIR (contrato.output_dir()); sem ela,
# <eqc_root>/pipeline/saidas-humanas, reusando contrato.eqc_root() (mesma resolução que
# output_dir()/contract_schema_path() já usam) em vez de reimplementar a descoberta aqui.
# Faltava esta variável até o passo D6b -- isolar um ensaio de main.py exigia monkeypatchar
# a função direto; agora é uma linha (ver ENTREGA do D6b, item 2).
_SAIDA_HUMANA_REL = ("pipeline", "saidas-humanas")
ENV_OUTPUT_DIR = "QUALIFICADOR_SAIDA_HUMANA_OUTPUT_DIR"

# Cópia de conveniência, FORA do repositório -- só por env var, nunca caminho fixo em código
# nem em documentação versionada (CLAUDE.md raiz §4). Ver .env.example.
ENV_COPIA_DIR = "QUALIFICADOR_SAIDA_HUMANA_DIR"

LEIAME_NOME = "LEIA-ME.txt"
LEIAME_TEXTO = (
    "Esta pasta é a cópia OFICIAL dos CSVs de leads DIRETA/ESPERA do QUALIFICADOR\n"
    "(as pistas que não atravessam o contrato com o COMERCIAL).\n"
    "\n"
    "O caminho desta pasta pode ser trocado pela variável QUALIFICADOR_SAIDA_HUMANA_OUTPUT_DIR\n"
    "(ex.: pra isolar um ensaio manual do programa -- ver .env.example).\n"
    "\n"
    "A cópia que aparece na pasta indicada por QUALIFICADOR_SAIDA_HUMANA_DIR (normalmente\n"
    "a área de trabalho do operador) é só uma CONVENIÊNCIA de leitura -- editar aquele\n"
    "arquivo NÃO volta para o sistema; o arquivo desta pasta (a oficial) é que vale.\n"
    "\n"
    "Nenhum destes arquivos entra no versionamento (Git) -- são dados operacionais,\n"
    "ficam só em disco.\n"
)


def _env(nome):
    return (os.environ.get(nome) or "").strip()


def saida_humana_dir():
    """Pasta oficial onde os CSVs humanos são gravados. QUALIFICADOR_SAIDA_HUMANA_OUTPUT_DIR
    (caminho final) tem precedência; senão, <eqc_root>/pipeline/saidas-humanas. Lê o
    ambiente a cada chamada -- mesmo padrão de contrato.output_dir() -- pra um ensaio
    manual (ou um teste) isolar com um `set`/`monkeypatch.setenv`, sem precisar trocar a
    função em si."""
    return _env(ENV_OUTPUT_DIR) or str(contrato.eqc_root().joinpath(*_SAIDA_HUMANA_REL))


def copia_conveniencia_dir():
    """Pasta de conveniência (fora do repo), lida só de QUALIFICADOR_SAIDA_HUMANA_DIR.
    None se a variável não estiver definida -- a cópia só acontece quando o operador
    configurou o destino; nenhum programa LÊ essa cópia de volta."""
    return _env(ENV_COPIA_DIR) or None


# --- Montagem das linhas ---------------------------------------------------------------------


def _classe_do_registro(emp):
    return emp.get("classe_site") or site_classificacao.classificar_site(emp.get("website"))


def _canais_de_contato(emp):
    """Contagem objetiva de canais de contato preenchidos -- mesmos quatro campos que
    output_json._contato() expõe (telefone/email/instagram/facebook). Usada só pro
    desempate na ordenação; não vai para nenhuma coluna do CSV."""
    return sum(1 for c in (emp.get("telefone"), emp.get("email"), emp.get("instagram"), emp.get("facebook")) if c)


def _cidade_para_exibicao(emp):
    """Cidade só para EXIBIÇÃO nesta coluna do CSV -- nunca grava nada de volta em
    nenhum dado real, e não é uma extração nova: reusa o MESMO padrão confiável que
    `agent_coletor._extrair_cidade` já usa na importação (cidade depois do CEP,
    `CIDADE_APOS_CEP_RE`), agora sobre `endereco` como reserva só quando `cidade` já veio
    vazia. Sem CEP reconhecível no endereço, fica em branco -- nunca inventa dado."""
    cidade = emp.get("cidade")
    if cidade:
        return cidade
    m = agent_coletor.CIDADE_APOS_CEP_RE.search(emp.get("endereco") or "")
    return m.group(1).strip().rstrip(",").strip() if m else ""


def _campo_do_import(emp, campo):
    if campo not in emp:
        return NAO_VERIFICADO
    return emp.get(campo) or ""


def _possivel_mesmo_negocio(emp):
    """place_id(s) da(s) outra(s) ficha(s), separados por vírgula. Vazio = checado, sem par;
    NAO_VERIFICADO = lead importado antes do filtro de redes."""
    if "possivel_mesmo_negocio" not in emp:
        return NAO_VERIFICADO
    ids = []
    for par in emp.get("possivel_mesmo_negocio") or []:
        pid = par.get("place_id") or ""
        if pid and pid not in ids:
            ids.append(pid)
    return ", ".join(ids)


def _linha(pista, motivo, emp, classe_site, qualificacao=None):
    """`qualificacao`: bloco da Onda 1 (`leads_qualificados.json`); None nas linhas vindas da
    Onda 2 -- aí prioridade_rotulo/prioridade_score ficam vazias (não há prioridade da Onda 1)."""
    qualificacao = qualificacao or {}
    prioridade_score = qualificacao.get("score")
    avaliacoes = emp.get("review_count")
    nota = emp.get("nota_google")
    return {
        "pista": pista,
        "motivo": motivo,
        "nome": emp.get("nome") or "",
        "nicho": emp.get("nicho") or "",
        "cidade": _cidade_para_exibicao(emp),
        "telefone": emp.get("telefone") or "",
        "email": emp.get("email") or "",
        "instagram": emp.get("instagram") or "",
        "site": emp.get("website") or "",
        "classe_site": classe_site,
        "avaliacoes": avaliacoes if avaliacoes is not None else "",
        "nota": nota if nota is not None else "",
        "google_maps_url": emp.get("google_maps_url") or "",
        "place_id": emp.get("place_id") or "",
        "campanha_id": _campo_do_import(emp, "campanha_id"),
        "campanha_nicho": _campo_do_import(emp, "campanha_nicho"),
        "possivel_mesmo_negocio": _possivel_mesmo_negocio(emp),
        "prioridade_rotulo": qualificacao.get("priority") or "",
        "prioridade_score": prioridade_score if prioridade_score is not None else "",
        # Chaves internas de ordenação -- nunca gravadas (escrever_csv usa extrasaction="ignore").
        "_avaliacoes_num": avaliacoes if isinstance(avaliacoes, (int, float)) else 0,
        "_nota_num": nota if isinstance(nota, (int, float)) else 0,
        "_canais": _canais_de_contato(emp),
    }


def montar_linhas(qualificados, com_site):
    """qualificados = leads_qualificados.json (Onda 1, status 'qualified') -- sempre DIRETA,
    porque Onda 1 é por definição 'sem site listado no Maps' (agent_coletor._classificar_campanha).
    com_site = leads_com_site.json (Onda 2; só os já analisados) -- DIRETA quando classe_site
    não é 'proprio', ESPERA quando é 'proprio' e output_json._lead_site() não o mandou pro
    contrato (nem nata, nem candidato à triagem)."""
    linhas = []

    for r in qualificados:
        if r.get("status") != "qualified" or not r.get("dados_empresa"):
            continue
        emp = r["dados_empresa"]
        classe = _classe_do_registro(emp)
        motivo = MOTIVO_POR_CLASSE.get(classe, MOTIVO_POR_CLASSE[site_classificacao.SEM_SITE])
        linhas.append(_linha(PISTA_DIRETA, motivo, emp, classe, r.get("qualificacao")))

    for r in com_site:
        if r.get("status") not in output_json._STATUS_ONDA2_PRONTOS or not r.get("dados_empresa"):
            continue
        emp = r["dados_empresa"]
        classe = _classe_do_registro(emp)
        if classe != site_classificacao.PROPRIO:
            motivo = MOTIVO_POR_CLASSE.get(classe, MOTIVO_POR_CLASSE[site_classificacao.PORTAL])
            linhas.append(_linha(PISTA_DIRETA, motivo, emp, classe))
            continue
        if output_json._lead_site(r) is None:
            linhas.append(_linha(PISTA_ESPERA, MOTIVO_ESPERA, emp, classe))

    return _ordenar(linhas)


def _grupo(linha):
    """0 = Direta prioritária (>=10 avaliações E nota >=3,5) · 1 = resto da Direta ·
    2 = Espera. RUMO-COMERCIAL-2026-09 §3.6."""
    if linha["pista"] == PISTA_ESPERA:
        return 2
    prioritaria = (
        linha["_avaliacoes_num"] >= MIN_AVALIACOES_PRIORITARIA
        and linha["_nota_num"] >= MIN_NOTA_PRIORITARIA
    )
    return 0 if prioritaria else 1


def _ordenar(linhas):
    """Grupo (Direta prioritária, resto da Direta, Espera) -> avaliações decrescente ->
    canais de contato decrescente -> place_id/nome (determinismo -- mesma entrada, mesma
    ordem, sempre; sem isso duas rodadas com o mesmo dado produziriam CSVs diferentes)."""
    return sorted(
        linhas,
        key=lambda l: (
            _grupo(l),
            -l["_avaliacoes_num"],
            -l["_canais"],
            l["place_id"] or "",
            l["nome"] or "",
        ),
    )


# --- Gravação do CSV ---------------------------------------------------------------------


def escrever_csv(linhas, caminho):
    """Grava UTF-8 COM BOM (utf-8-sig) e delimitador ';'.

    Escolha, não padrão: o Excel do Windows só reconhece um CSV como UTF-8 (e mostra
    acento certo -- "não", "avaliações") quando o arquivo carrega o BOM; sem ele, o Excel
    assume a codificação ANSI/Windows-1252 da localização do Windows e estraga acento.
    O delimitador ';' evita o outro defeito clássico: localizações ES/PT-BR usam vírgula
    como separador DECIMAL, então o Excel trata um CSV separado por vírgula como uma
    coluna só, a menos que o operador use Dados > Texto para Colunas manualmente. Os dois
    juntos abrem certo com duplo-clique, sem passo manual nenhum -- provado por
    test_saida_humana.py::test_csv_relido_bate_com_o_gravado (grava e relê de volta)."""
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for linha in linhas:
            w.writerow(linha)


def nome_arquivo(ts):
    """qualificador_<timestamp>.csv -- SEM número de versão (decisão da supervisão,
    Etapa D, passo D6b, item 2). O JSON do contrato leva v2.0.0 no nome porque É o
    contrato; este CSV não é -- gravar contrato.QUALIFICADOR_VERSION (1.1.0) no nome dele
    só criava dois números de versão diferentes na mesma pasta, convite ao erro de quem
    olha a pasta por cima."""
    return f"qualificador_{ts}.csv"


def caminho_sem_sobrescrever(pasta, nome_base):
    """Nunca sobrescreve: se `nome_base` já existir em `pasta`, acrescenta um sufixo
    numérico crescente até achar um nome livre."""
    raiz, ext = os.path.splitext(nome_base)
    caminho = os.path.join(pasta, nome_base)
    n = 2
    while os.path.exists(caminho):
        caminho = os.path.join(pasta, f"{raiz}_{n}{ext}")
        n += 1
    return caminho


def escrever_leiame(pasta):
    """Grava LEIA-ME.txt na pasta oficial, só se ainda não existir -- nunca sobrescreve
    (mesma garantia dada a qualquer arquivo já gravado nesta pasta)."""
    caminho = os.path.join(pasta, LEIAME_NOME)
    if os.path.exists(caminho):
        return
    os.makedirs(pasta, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(LEIAME_TEXTO)


def copiar_conveniencia(caminho_oficial, pasta_destino):
    """Cópia BEST-EFFORT de `caminho_oficial` para `pasta_destino`. Nunca levanta --
    pasta inexistente (cria), sem permissão, disco cheio, arquivo aberto no Excel: tudo
    vira (False, motivo). A rodada NUNCA falha por causa desta cópia; nenhum programa lê
    o resultado de volta. Devolve (sucesso: bool, caminho_ou_motivo: str)."""
    if not pasta_destino:
        return False, f"{ENV_COPIA_DIR} não definida -- cópia de conveniência pulada."
    try:
        os.makedirs(pasta_destino, exist_ok=True)
        destino = os.path.join(pasta_destino, os.path.basename(caminho_oficial))
        shutil.copy2(caminho_oficial, destino)
        return True, destino
    except OSError as e:
        return False, f"cópia de conveniência falhou ({e}) -- a rodada segue normalmente."
