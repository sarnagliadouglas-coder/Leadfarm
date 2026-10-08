import csv
import os
import re
import shutil
import json
import sys
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path

import campanha as campanha_mod
import contrato
import csv_contrato
import env_loader
import erro_import
import gbp_diagnostic
import lead_qualification
import output_json
import psi_client
import rede_multiunidade
import reprovados as rep
import saida_humana
import site_classificacao
import site_renderizado
import wave2_scoring
from agent_coletor import AgentColetor

# Limitadores de execução. Viviam em claude_client.py (removido) pra conter EXPOSIÇÃO DE
# CUSTO por rodada; como nenhuma etapa da Onda 1/2 chama API, viraram só guardas de tempo/
# volume e ficam desligados. None = sem limite -- os pontos de uso tratam None explicitamente.
MAX_RUNTIME_SECONDS = None
MAX_QUALIFICATION_CANDIDATES = None

# A Onda 2 faz I/O de rede (~2s por site) e o lote pode ter centenas de leads. Grava
# progresso a cada N análises pra que uma interrupção não custe a rodada inteira.
CHECKPOINT_WAVE2_A_CADA = 25

# --- Limites do PSI -------------------------------------------------------------------
# Ao contrário da Onda 2 (offline, $0, ~2s por site, batch_size=null), o PSI é quota externa
# e ~45s por lead medidos na prática -- 20x mais lento. Por isso ele tem teto POR PADRÃO: sem
# isso, um `python main.py psi` num backlog acumulado vira uma rodada de horas não pedida.
PSI_BATCH_SIZE = 40                 # ~30min por rodada, ao ritmo medido
PSI_MAX_RUNTIME_SECONDS = 1800      # guarda dura, mesmo papel do max_runtime_seconds da Onda 2
# Falha transiente domina no PSI: numa re-medição real dos 51 que falharam, 47 passaram -- e 31
# deles já na 1ª chamada, sem nem precisar do retry interno. Vale reagendar entre rodadas, mas
# com teto: sem ele, um site permanentemente quebrado queima quota em toda rodada, pra sempre.
PSI_MAX_RODADAS_POR_LEAD = 3

# --- Fase de renderização (Etapa C, passo C4) ---------------------------------------------
# ~1 min por site (estimativa, ainda não medida -- passo C5): grava a CADA lead medido, para que
# interromper (Ctrl+C, queda, fechar a janela) nunca custe o que já foi medido.
CHECKPOINT_RENDER_A_CADA = 1

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PATH_COLETADOS = os.path.join(DATA_DIR, "leads_coletados.json")
PATH_QUALIFICADOS = os.path.join(DATA_DIR, "leads_qualificados.json")
PATH_REPROVADOS = os.path.join(DATA_DIR, "leads_reprovados.json")
PATH_COM_SITE = os.path.join(DATA_DIR, "leads_com_site.json")
# Metadado da última importação (qual CSV do EXTRATOR alimentou esta rodada). Estado
# interno -- fica no DATA_DIR do projeto, NÃO faz parte do contrato externo.
PATH_IMPORT_META = os.path.join(DATA_DIR, "_import_meta.json")
# Histórico permanente das reprovações (reprovados.py): só de acréscimo, nunca zerado --
# nem pelo arquivar-pool. Dado operacional, fora do git.
PATH_HISTORICO_REPROVADOS = os.path.join(DATA_DIR, "historico_reprovados.jsonl")
# Traceback de erro do import (erro_import.gravar_log). Dado operacional, fora do git.
LOG_DIR = os.path.join(DATA_DIR, "logs")

# A saída (contrato QUALIFICADOR -> COMERCIAL) NÃO tem mais path fixo: vai para
# contrato.output_dir() (env QUALIFICADOR_OUTPUT_DIR), com nome versionado por rodada.
# Gerada por fase_saida(), nunca lida de volta (os JSONs de data/ continuam sendo a
# fonte de verdade do pipeline).


def carregar_json(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        conteudo = f.read().strip()
        return json.loads(conteudo) if conteudo else []


def salvar_json(path, dados):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=4)


def extrair_dominio(url):
    if not url:
        return None
    sem_protocolo = re.sub(r"^https?://", "", url.strip().lower())
    sem_www = re.sub(r"^www\.", "", sem_protocolo)
    return sem_www.split("/")[0] or None


def chave_dedup(dados_empresa):
    """Trabalho braçal em Python: prioridade place_id > domínio do site > telefone > nome+cidade."""
    place_id = dados_empresa.get("place_id")
    if place_id:
        return f"place_id:{place_id}"

    dominio = extrair_dominio(dados_empresa.get("website"))
    if dominio:
        return f"dominio:{dominio}"

    telefone = dados_empresa.get("telefone")
    if telefone:
        return f"telefone:{re.sub(r'[^0-9+]', '', telefone)}"

    nome = (dados_empresa.get("nome") or "").strip().lower()
    cidade = (dados_empresa.get("cidade") or "").strip().lower()
    return f"nome_cidade:{nome}|{cidade}"


def chaves_conhecidas(*listas_de_registros):
    conhecidas = set()
    for lista in listas_de_registros:
        for registro in lista:
            conhecidas.add(chave_dedup(registro.get("dados_empresa", {})))
    return conhecidas


def _todas_chaves_conhecidas():
    return chaves_conhecidas(
        carregar_json(PATH_COLETADOS),
        carregar_json(PATH_COM_SITE),
        carregar_json(PATH_REPROVADOS),
        carregar_json(PATH_QUALIFICADOS),
    )


def _acrescentar_novos(caminho, leads, status, conhecidas_globais):
    """Trabalho braçal em Python: acrescenta só os leads que ainda não são conhecidos
    (nem pendentes, nem qualificados, nem em nenhum outro arquivo já salvo)."""
    existentes = carregar_json(caminho)
    novos = [l for l in leads if chave_dedup(l) not in conhecidas_globais]
    for lead in novos:
        existentes.append({"dados_empresa": lead, "status": status})
    salvar_json(caminho, existentes)
    return len(novos)


def _registro_reprovado(lead, etapa, agora):
    """Registro de leads_reprovados.json: motivo (anexado por quem cortou) no nível do registro
    — nunca reprova silenciosamente —, `rejection_detail` (atravessa o contrato como
    detalhe_do_corte) e `detalhe_interno` (só histórico/consulta) quando existem, mais o
    carimbo de data, origem e etapa (reprovados.carimbar_registro)."""
    motivo = lead.pop("rejection_reason", "unknown")
    registro = {"dados_empresa": lead, "status": "rejected", "rejection_reason": motivo}
    detalhe = lead.pop("rejection_detail", None)
    if detalhe is not None:
        registro["rejection_detail"] = detalhe
    interno = lead.pop("detalhe_interno", None)
    if interno is not None:
        registro["detalhe_interno"] = interno
    return rep.carimbar_registro(registro, etapa, agora)


def _acrescentar_reprovados(leads, conhecidas_globais, etapa=rep.ETAPA_IMPORT):
    """Igual ao _acrescentar_novos, mas monta o registro de reprovação (_registro_reprovado)
    e, depois de gravar, acrescenta uma linha por reprovação ao histórico permanente."""
    existentes = carregar_json(PATH_REPROVADOS)
    novos = [l for l in leads if chave_dedup(l) not in conhecidas_globais]
    agora = _now_iso()
    registros = [_registro_reprovado(lead, etapa, agora) for lead in novos]
    existentes.extend(registros)
    salvar_json(PATH_REPROVADOS, existentes)
    rep.acrescentar_historico(PATH_HISTORICO_REPROVADOS, rep.linhas_reprovacao(registros))
    return len(novos)


def _remover_identico(lista, item):
    """Remove pelo OBJETO (identidade), nunca por igualdade -- dois dicts iguais seriam o
    mesmo para list.remove."""
    for i, existente in enumerate(lista):
        if existente is item:
            del lista[i]
            return
    raise ValueError("item não está na lista")


# Arquivos do pool com leads ATIVOS (não reprovados) -- o filtro de rede pode tirar um
# registro daqui e levá-lo para leads_reprovados.json.
def _arquivos_pool_ativo():
    return [PATH_COLETADOS, PATH_COM_SITE, PATH_QUALIFICADOS]


def _aplicar_filtro_rede(wave1, wave2, reprovados, config_rede, conhecidas_globais, chaves_fora_do_pool=frozenset()):
    """Filtro de redes / multiunidade (rede_multiunidade.py) sobre o POOL inteiro + os leads
    novos deste import. Só CALCULA e altera listas/registros em memória; devolve o que
    main.importar_csv precisa gravar. Nada é escrito aqui.

    - lead novo ativo com marca da lista, ou em grupo >= limiar: vai para `reprovados`
      (motivo rede_ou_multiunidade + rejection_detail);
    - registro JÁ no pool ativo em grupo >= limiar: sai do arquivo dele e vai para
      leads_reprovados.json (o registro inteiro é preservado, com status_anterior);
    - grupo menor que o limiar (2+): aviso `possivel_mesmo_negocio` nos ativos (novos e do
      pool); lead novo ativo sem par recebe [] (checado, nenhum par).
    Registros já reprovados contam para o tamanho do grupo, mas mantêm o motivo original.

    `chaves_fora_do_pool` (só a reavaliação usa): registros de leads_reprovados.json com essas
    chaves são tratados como fora do pool -- os leads devolvidos entram como novos (wave1/wave2)."""
    limiar = config_rede["limiar_rede"]
    marcas = config_rede["marcas"]

    def _novo(lead):
        return chave_dedup(lead) not in conhecidas_globais

    # 1. Marca (só leads novos ativos).
    por_marca = []
    for lista in (wave1, wave2):
        for lead in list(lista):
            if not _novo(lead):
                continue
            marca = rede_multiunidade.marca_no_nome(lead, marcas)
            if marca:
                lead["rejection_reason"] = rede_multiunidade.MOTIVO
                lead["rejection_detail"] = {"por": rede_multiunidade.POR_MARCA, "chave": marca, "tamanho_grupo": None}
                _remover_identico(lista, lead)
                por_marca.append(lead)
    reprovados.extend(por_marca)

    # 2. Fichas: pool inteiro (uma por chave) + leads novos deste import.
    pool = {caminho: carregar_json(caminho) for caminho in _arquivos_pool_ativo() + [PATH_REPROVADOS]}
    if chaves_fora_do_pool:
        pool[PATH_REPROVADOS] = [r for r in pool[PATH_REPROVADOS]
                                 if chave_dedup(r.get("dados_empresa") or {}) not in chaves_fora_do_pool]
    fichas, origem, vistas = [], [], set()
    for caminho, registros in pool.items():
        for registro in registros:
            emp = registro.get("dados_empresa")
            if not emp or chave_dedup(emp) in vistas:
                continue
            vistas.add(chave_dedup(emp))
            ativo = caminho != PATH_REPROVADOS and registro.get("status") != "rejected"
            fichas.append(emp)
            origem.append(("pool", caminho, registro, ativo))
    for lista, ativo in ((wave1, True), (wave2, True), (reprovados, False)):
        for lead in lista:
            if _novo(lead) and chave_dedup(lead) not in vistas:
                vistas.add(chave_dedup(lead))
                fichas.append(lead)
                origem.append(("novo", lista, lead, ativo))

    descartes, avisos = rede_multiunidade.agrupar(fichas, limiar)

    # 3. Aplicação em memória.
    pool_movidos, avisos_marcados, pool_alterado = [], 0, set()
    agora = _now_iso()
    for i, (tipo, onde, item, ativo) in enumerate(origem):
        if not ativo:
            continue
        if i in descartes:
            if tipo == "novo":
                item["rejection_reason"] = rede_multiunidade.MOTIVO
                item["rejection_detail"] = descartes[i]
                _remover_identico(onde, item)
                reprovados.append(item)
            else:
                _remover_identico(pool[onde], item)
                pool_movidos.append(rep.carimbar_registro(
                    {**item, "status": "rejected", "status_anterior": item.get("status"),
                     "rejection_reason": rede_multiunidade.MOTIVO,
                     "rejection_detail": descartes[i]}, rep.ETAPA_REDE_POOL, agora))
                pool_alterado.add(onde)
            continue
        if i in avisos:
            fichas[i]["possivel_mesmo_negocio"] = avisos[i]
            avisos_marcados += 1
            if tipo == "pool":
                pool_alterado.add(onde)
        elif tipo == "novo":
            fichas[i]["possivel_mesmo_negocio"] = []

    pool[PATH_REPROVADOS].extend(pool_movidos)
    if pool_movidos:
        pool_alterado.add(PATH_REPROVADOS)
    return {"pool": pool, "pool_alterado": pool_alterado, "pool_movidos": len(pool_movidos),
            "registros_movidos": pool_movidos, "por_marca": len(por_marca), "avisos": avisos_marcados}


def importar_csv(caminho_csv):
    print("\n--- IMPORT ---")
    if not caminho_csv or not os.path.exists(caminho_csv):
        raise erro_import.CsvIlegivelError(f"Arquivo não encontrado: {caminho_csv}")

    # Falha alta ANTES de ler o CSV ou gravar qualquer coisa: sidecar fora do contrato,
    # termo da busca que não aponta para exatamente uma campanha, campanha inválida (ou
    # config de redes ausente) -- o import não roda. Propaga, como ContratoCsvInvalido.
    sidecar, _avisos = csv_contrato.validar_sidecar(caminho_csv)
    escolha = campanha_mod.escolher_campanha((sidecar or {}).get("termo_busca"))
    campanha = escolha["campanha"]
    config_rede = rede_multiunidade.carregar_config()
    print("==================================================")
    for linha in escolha["avisos"]:
        print(f"[Import] {linha}")
    print("==================================================")
    print(f"[Import] Campanha: {campanha['id']} ({campanha['nicho']}); cidade: {escolha['cidade']}; "
          f"origem: {escolha['origem']}.")

    coletor = AgentColetor()
    try:
        wave1, reprovados, wave2, custo, recon = coletor.coletar_leads_de_csv(
            caminho_csv, campanha=campanha, cidade=escolha["cidade"])
    except csv_contrato.ContratoCsvInvalido:
        # Falha alta: contrato EXTRATOR -> QUALIFICADOR violado. Não é "este CSV está
        # corrompido", é "pare e conserte o EXTRATOR". Propaga (nada foi gravado).
        raise
    except (UnicodeError, csv.Error, OSError) as e:
        # CSV que não se deixa ler (decodificação, arquivo malformado, acesso). Falha alta
        # com mensagem clara (erro_import), nada gravado. Qualquer outra exceção é defeito
        # e sobe como erro inesperado -- antes um `except Exception` a engolia e saía com 0.
        raise erro_import.CsvIlegivelError(f"O CSV '{os.path.basename(caminho_csv)}' não pôde ser lido: {e}") from e

    # De que lista e de que busca veio cada lead (dado interno: output_json só lê campos
    # nomeados de dados_empresa) -- é daqui que a Onda 1 tira o carimbo da reprovação.
    origem = rep.carimbo_import(os.path.basename(caminho_csv), (sidecar or {}).get("termo_busca"))
    for lead in wave1 + wave2 + reprovados:
        lead.update(origem)

    total_coletor = len(wave1) + len(wave2) + len(reprovados)
    conhecidas_globais = _todas_chaves_conhecidas()
    rede = _aplicar_filtro_rede(wave1, wave2, reprovados, config_rede, conhecidas_globais)

    # Gravação: primeiro o pool alterado pelo filtro de rede, depois os leads novos.
    for caminho in rede["pool_alterado"]:
        salvar_json(caminho, rede["pool"][caminho])
    rep.acrescentar_historico(PATH_HISTORICO_REPROVADOS, rep.linhas_reprovacao(rede["registros_movidos"]))
    motivos_novos = {}
    for lead in reprovados:
        if chave_dedup(lead) not in conhecidas_globais:
            motivo = lead.get("rejection_reason", "unknown")
            motivos_novos[motivo] = motivos_novos.get(motivo, 0) + 1
    n_wave1 = _acrescentar_novos(PATH_COLETADOS, wave1, "eligible", conhecidas_globais)
    n_reprovados = _acrescentar_reprovados(reprovados, conhecidas_globais)
    n_wave2 = _acrescentar_novos(PATH_COM_SITE, wave2, "queued_future", conhecidas_globais)

    salvar_json(PATH_IMPORT_META, {"origem_csv": os.path.basename(caminho_csv), "importado_em": _now_iso(),
                                   "campanha_id": campanha["id"], "campanha_cidade": escolha["cidade"],
                                   "origem_campanha": escolha["origem"]})

    novos = n_wave1 + n_wave2 + n_reprovados
    dedup_global = total_coletor - novos

    print("==================================================")
    print(f"📥 {n_wave1} lead(s) Onda 1 novo(s) → fila de qualificação ({PATH_COLETADOS})")
    print(f"🚫 {n_reprovados} lead(s) reprovado(s) novo(s) → {PATH_REPROVADOS}")
    print(f"🌐 {n_wave2} lead(s) Onda 2 novo(s) → guardados pra depois ({PATH_COM_SITE})")
    print(f"💰 Custo da importação: ${custo:.4f}")
    print("==================================================")

    # Reconciliação: onde cada linha do CSV foi parar. Fecha o buraco de observabilidade
    # (antes, linhas sumiam sem contagem: sem Name, dedup interno, dedup global).
    soma = recon["sem_nome"] + recon["dedup_interno"] + dedup_global + novos
    print("--- RECONCILIAÇÃO DO IMPORT ---")
    print(f"Linhas no CSV:                              {recon['linhas_csv']}")
    print(f"  descartadas sem 'Name':                   {recon['sem_nome']}")
    print(f"  dedup interno (repetidas no mesmo CSV):   {recon['dedup_interno']}")
    print(f"  dedup global (já conhecidas de rodadas anteriores): {dedup_global}")
    print(f"  leads novos nesta rodada:                 {novos}")
    print(f"      → Onda 1: {n_wave1}   Onda 2: {n_wave2}   reprovados: {n_reprovados}")
    for motivo in sorted(motivos_novos):
        print(f"          reprovados por {motivo}: {motivos_novos[motivo]}")
    print(f"Confere ({recon['sem_nome']}+{recon['dedup_interno']}+{dedup_global}+{novos} = {soma}): "
          f"{'OK' if soma == recon['linhas_csv'] else 'DIVERGE ⚠️'}")
    print("--- FILTRO DE REDES / MULTIUNIDADE (pool inteiro) ---")
    print(f"  fichas JÁ no pool movidas para reprovados ({rede_multiunidade.MOTIVO}), fora da conta acima: "
          f"{rede['pool_movidos']}")
    print(f"  fichas ativas com aviso possivel_mesmo_negocio: {rede['avisos']}")
    print("==================================================")


def _mover_para_reprovados(leads_com_motivo):
    """Move leads que já sabemos que existem — não é uma inclusão condicional de lead novo,
    então não faz dedup contra o snapshot em disco (diferente de _acrescentar_reprovados):
    neste ponto do fluxo o lead ainda está fisicamente listado em leads_coletados.json, e só
    sai de lá no final de fase_qualify(). Reusar _acrescentar_reprovados aqui descartaria o
    lead como "já conhecido" e ele desapareceria sem ir pra lugar nenhum."""
    if not leads_com_motivo:
        return 0
    existentes = carregar_json(PATH_REPROVADOS)
    agora = _now_iso()
    registros = [_registro_reprovado(lead, rep.ETAPA_ONDA1, agora) for lead in leads_com_motivo]
    existentes.extend(registros)
    salvar_json(PATH_REPROVADOS, existentes)
    rep.acrescentar_historico(PATH_HISTORICO_REPROVADOS, rep.linhas_reprovacao(registros))
    return len(leads_com_motivo)


def _anotar_detalhe_onda1(leads, icp=None):
    """`detalhe_interno` (nunca rejection_detail: este atravessa o contrato) nos cortes da Onda 1."""
    for lead in leads:
        lead["detalhe_interno"] = rep.detalhe_onda1(lead, lead.get("rejection_reason"), icp)


def imprimir_qualificados_onda1(novos_qualificados):
    """Resumo de console pros leads da Onda 1 qualificados nesta rodada. A saída completa
    (pro Sistema 2 consumir) é o JSON de leads_saida.json -- isto aqui é só um retrato rápido
    da rodada. Sem copy: a geração de mensagem passou a ser trabalho do outro sistema."""
    if not novos_qualificados:
        return
    print("\n==================================================")
    print("✅ LEADS ONDA 1 QUALIFICADOS NESTA RODADA")
    print("==================================================")
    for idx, item in enumerate(novos_qualificados, 1):
        lead = item["dados_empresa"]
        qual = item.get("qualificacao", {})
        riscos = qual.get("risks") or []

        print(f"\n#{idx} — {lead.get('nome', 'Empresa')}")
        print(f"Score: {qual.get('score', '-')}  |  Prioridade: {qual.get('priority', '-')}  |  Contatabilidade: {qual.get('contactability', '-')}")
        print(f"Categoria: {lead.get('nicho', '-')}  |  Cidade: {lead.get('cidade') or '-'}")
        print(f"Por que contactar: {qual.get('reason_to_contact') or '-'}")
        if riscos:
            print(f"Riscos: {'; '.join(riscos)}")
        print("---")


def imprimir_metricas(m):
    print("\n==================================================")
    print("📊 MÉTRICAS DA RODADA (ONDA 1)")
    print("==================================================")
    print(f"Avaliados no pré-filtro ICP: {m['total_avaliados_pre_filtro']}")
    nota_icp = "" if m.get("icp_tem_filtro_ativo") else "  (nenhum filtro configurado em config/ideal_customer_profile.json)"
    print(f"Reprovados no pré-filtro ICP: {m['total_reprovados_icp']}{nota_icp}")
    print(f"Reprovados por falta de canal de contato (sem email/rede/celular): {m.get('total_reprovados_contato', 0)}")
    print(f"Avaliados pela Qualification (Python, $0): {m['chamadas_qualification']}")
    print(f"Qualificados: {m['qualificados']}  |  Desqualificados: {m['desqualificados']}")
    print(f"Custo total: ${m['custo_total_usd']:.4f} (Onda 1 inteira é Python puro, sem API)")
    print("==================================================")


def fase_qualify():
    """Funil da Onda 1, 100% Python, $0: pré-filtro ICP -> filtro de contatabilidade ->
    Qualification (score + prioridade) -> ranking. Não gera copy -- a geração de mensagem é
    trabalho do Sistema 2 agora. Cada lead qualificado termina em leads_qualificados.json com
    status 'qualified' (estado FINAL desta esteira), e de lá o fase_saida() o leva pro JSON de
    saída. MAX_RUNTIME_SECONDS é só guarda de tempo (não existe mais custo pra estourar)."""
    print("\n--- FASE: QUALIFY (ONDA 1) ---")
    icp = lead_qualification.carregar_icp()

    pendentes = carregar_json(PATH_COLETADOS)
    a_avaliar = [l for l in pendentes if l.get("status") == "eligible"]
    pool_qualificados_existente = carregar_json(PATH_QUALIFICADOS)

    if not a_avaliar and not pool_qualificados_existente:
        print("[Orquestrador] Nenhum lead pendente de qualificação. Rode `python main.py --csv <arquivo>` primeiro.")
        return None

    inicio = time.time()
    metricas = {
        "total_avaliados_pre_filtro": len(a_avaliar),
        "total_reprovados_icp": 0,
        "total_reprovados_contato": 0,
        "chamadas_qualification": 0,
        "qualificados": 0,
        "desqualificados": 0,
        "custo_total_usd": 0.0,
        "icp_tem_filtro_ativo": lead_qualification.icp_tem_filtro_ativo(icp),
    }

    # --- PRÉ-FILTRO ICP ($0) ---
    leads_a_avaliar = [l["dados_empresa"] for l in a_avaliar]
    aprovados_icp, reprovados_icp = lead_qualification.filtrar_icp(leads_a_avaliar, icp)
    metricas["total_reprovados_icp"] = len(reprovados_icp)
    _anotar_detalhe_onda1(reprovados_icp, icp)
    _mover_para_reprovados(reprovados_icp)

    # --- FILTRO DE CONTATABILIDADE ($0, exclusivo da Onda 1) ---
    # Sem email, sem rede social e sem celular espanhol (6/7xx) = nenhum canal pra abordar o
    # lead. Corta ANTES da Qualification -- não faz sentido pagar o processamento de um lead
    # que não há como contactar. Ver lead_qualification pro porquê disto não valer pra Onda 2.
    aprovados_contato, reprovados_contato = lead_qualification.filtrar_contactabilidade_onda1(aprovados_icp)
    metricas["total_reprovados_contato"] = len(reprovados_contato)
    _anotar_detalhe_onda1(reprovados_contato)
    _mover_para_reprovados(reprovados_contato)

    candidatos = aprovados_contato if MAX_QUALIFICATION_CANDIDATES is None else aprovados_contato[:MAX_QUALIFICATION_CANDIDATES]
    if MAX_QUALIFICATION_CANDIDATES is not None and len(aprovados_contato) > MAX_QUALIFICATION_CANDIDATES:
        print(f"[Orquestrador] {len(aprovados_contato)} candidato(s) após pré-filtro; avaliando só os primeiros {MAX_QUALIFICATION_CANDIDATES} (MAX_QUALIFICATION_CANDIDATES).")

    # Índice dos registros de origem (pra carregar gbp_diagnostico junto quando um lead
    # qualificado for movido pra leads_qualificados.json).
    registro_por_chave = {chave_dedup(l["dados_empresa"]): l for l in a_avaliar}

    # --- QUALIFICATION (Python puro, $0) ---
    qualificados_nesta_rodada = []
    desqualificados_nesta_rodada = []
    chaves_avaliadas = set()

    for idx, lead in enumerate(candidatos, 1):
        decorrido = time.time() - inicio
        if MAX_RUNTIME_SECONDS is not None and decorrido > MAX_RUNTIME_SECONDS:
            print(f"[Orquestrador] Parando Qualification: {MAX_RUNTIME_SECONDS}s de execução atingidos (MAX_RUNTIME_SECONDS).")
            break

        try:
            qual = lead_qualification.qualificar_onda1(lead, icp)
        except Exception as e:
            print(f"[Qualification] Erro ao avaliar '{lead.get('nome', 'Empresa')}': {e}")
            continue

        metricas["chamadas_qualification"] += 1
        chave = chave_dedup(lead)
        chaves_avaliadas.add(chave)

        if qual.get("qualified"):
            print(f"[Qualification] [{idx}/{len(candidatos)}] {lead.get('nome', 'Empresa')} -> qualificado (score={qual.get('score')})")
            registro_origem = registro_por_chave.get(chave, {})
            novo_registro = {
                "dados_empresa": lead,
                "qualificacao": qual,
                "status": "qualified",
            }
            if "gbp_diagnostico" in registro_origem:
                novo_registro["gbp_diagnostico"] = registro_origem["gbp_diagnostico"]
            qualificados_nesta_rodada.append(novo_registro)
        else:
            print(f"[Qualification] [{idx}/{len(candidatos)}] {lead.get('nome', 'Empresa')} -> desqualificado")
            lead["rejection_reason"] = "qualification_declined"
            lead["detalhe_interno"] = rep.detalhe_onda1(lead, "qualification_declined", qualificacao=qual)
            desqualificados_nesta_rodada.append(lead)

    metricas["qualificados"] = len(qualificados_nesta_rodada)
    metricas["desqualificados"] = len(desqualificados_nesta_rodada)
    _mover_para_reprovados(desqualificados_nesta_rodada)

    # --- RANKING ($0, puro Python) -- ordena o pool inteiro (novos + já existentes) ---
    pool = pool_qualificados_existente + qualificados_nesta_rodada
    ranqueados = lead_qualification.ranquear(pool)
    salvar_json(PATH_QUALIFICADOS, ranqueados)

    chaves_tratadas = chaves_avaliadas | {chave_dedup(l) for l in reprovados_icp} | {chave_dedup(l) for l in reprovados_contato}
    pendentes_restantes = [
        l for l in pendentes
        if l.get("status") == "eligible" and chave_dedup(l["dados_empresa"]) not in chaves_tratadas
    ]
    salvar_json(PATH_COLETADOS, pendentes_restantes)

    imprimir_qualificados_onda1(qualificados_nesta_rodada)
    imprimir_metricas(metricas)

    print("==================================================")
    print("🎉 Qualificação (Onda 1) concluída!")
    print(f"📁 {len(ranqueados)} lead(s) qualificado(s) em {PATH_QUALIFICADOS}")
    if pendentes_restantes:
        print(f"⏳ {len(pendentes_restantes)} lead(s) ainda pendente(s) de pré-filtro/Qualification pra próxima execução.")
    print("==================================================")

    return metricas


def _config_gbp():
    return wave2_scoring.carregar_config_wave2().get("gbp_diagnostic") or gbp_diagnostic.CONFIG_DEFAULT


def fase_gbp():
    """Diagnóstico determinístico de completude de ficha GBP -- roda pra TODOS os leads (Onda 1
    e Onda 2), antes da bifurcação por website_status. $0, sem LLM. Anota 'gbp_diagnostico' em
    cada registro de leads_coletados / leads_com_site / leads_qualificados. Idempotente:
    re-executar recalcula tudo (self-healing quando o extractor for corrigido -- ver
    gbp_diagnostic.avaliar_saude_do_lote)."""
    print("\n--- FASE: GBP (diagnóstico de ficha do Google, $0, sem LLM) ---")
    config = _config_gbp()

    arquivos = [PATH_COLETADOS, PATH_COM_SITE, PATH_QUALIFICADOS]
    registros_por_arquivo = {p: carregar_json(p) for p in arquivos}
    todos_leads = [r["dados_empresa"] for regs in registros_por_arquivo.values() for r in regs if r.get("dados_empresa")]

    if not todos_leads:
        print("[GBP] Nenhum lead pra diagnosticar.")
        return None

    rebaixados, avisos = gbp_diagnostic.avaliar_saude_do_lote(todos_leads, config)
    for aviso in avisos:
        print(f"[GBP] ⚠️  {aviso}")

    total = 0
    for caminho, registros in registros_por_arquivo.items():
        for r in registros:
            if r.get("dados_empresa"):
                r["gbp_diagnostico"] = gbp_diagnostic.diagnosticar(r["dados_empresa"], rebaixados, config)
                total += 1
        salvar_json(caminho, registros)

    print(f"[GBP] {total} lead(s) diagnosticado(s). Campos rebaixados no lote: {sorted(rebaixados) or 'nenhum'}")
    return {"diagnosticados": total, "campos_rebaixados": sorted(rebaixados), "avisos": avisos}


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _selecionar_lote_wave2(leads, batch_size, max_retry_attempts):
    """Prioriza queued_future (nunca tentado) antes de needs_review (retry) — nunca inclui
    unavailable_permanent (já esgotou as tentativas, precisa de reset manual)."""
    fila_nova = [l for l in leads if l.get("status") == "queued_future"]
    fila_retry = [
        l for l in leads
        if l.get("status") == "needs_review"
        and (l.get("website_analysis") or {}).get("attempts", 0) < max_retry_attempts
    ]
    fila = fila_nova + fila_retry
    return fila if batch_size is None else fila[:batch_size]


def imprimir_top_sites_onda2(leads_com_site, config):
    """Ranqueia todo o pool 'analyzed' (não só o lote desta rodada) — mesmo espírito da Onda 1:
    o TOP não deve esquecer sites bons analisados em execuções anteriores."""
    analisados = [l for l in leads_com_site if l.get("status") == "analyzed"]
    if not analisados:
        print("\n[Wave2] Nenhum site analisado ainda pra montar o TOP.")
        return

    ranqueados = wave2_scoring.ranquear(analisados)
    top_n, _ = lead_qualification.separar_top_n(ranqueados, config["top_n_display"])

    print("\n==================================================")
    print("🌐 TOP SITES PARA REVISÃO (ONDA 2)")
    print("==================================================")
    for idx, item in enumerate(top_n, 1):
        lead = item["dados_empresa"]
        cf = item.get("commercial_fit") or {}
        wo = item.get("website_opportunity") or {}
        razoes = (wo.get("reasons") or [])[:4]

        print(f"\n#{idx} — {lead.get('nome', 'Empresa')}")
        print(f"Categoria: {lead.get('nicho', '-')}  |  Cidade: {lead.get('cidade') or '-'}")
        print(f"Website: {lead.get('website', '-')}")
        print(f"Commercial Fit: {cf.get('score', '-')}  |  Website Opportunity: {wo.get('score', '-')}  |  Priority: {item.get('priority_label', '-')}")
        if razoes:
            print("Principais sinais:")
            for r in razoes:
                print(f"  - {r}")
        print("---")


def imprimir_metricas_wave2(metricas, duracao_segundos, leads_com_site):
    pendentes = sum(1 for l in leads_com_site if l.get("status") in ("queued_future", "needs_review"))
    print("\n==================================================")
    print("📊 MÉTRICAS DA RODADA (ONDA 2)")
    print("==================================================")
    print(f"Avaliados nesta rodada: {metricas['avaliados']}")
    print(f"  analyzed: {metricas.get('analyzed', 0)}  |  needs_review: {metricas.get('needs_review', 0)}  |  unavailable_permanent: {metricas.get('unavailable_permanent', 0)}")
    print(f"Tempo decorrido: {duracao_segundos:.1f}s")
    print(f"Custo: $0.00 (nenhuma chamada de IA)")
    if pendentes:
        print(f"⏳ {pendentes} lead(s) ainda pendente(s) (queued_future/needs_review) pra próxima execução.")
    print("==================================================")


def fase_wave2():
    """Onda 2: pré-qualificação de sites SEM LLM. Nunca gera copy, nunca chama IA. Resiliência
    em 2 camadas: website_analyzer nunca lança, e o loop aqui também envolve a avaliação
    composta num try/except — bug de scoring/config também nunca derruba o lote."""
    print("\n--- FASE: WAVE 2 (pré-qualificação de sites, $0, sem LLM) ---")
    config = wave2_scoring.carregar_config_wave2()
    icp = lead_qualification.carregar_icp()

    leads = carregar_json(PATH_COM_SITE)
    lote = _selecionar_lote_wave2(leads, config["batch_size"], config["max_retry_attempts"])

    if not lote:
        print("[Orquestrador] Nenhum lead pendente de análise de site.")
        imprimir_top_sites_onda2(leads, config)
        return None

    inicio = time.time()
    metricas = {"avaliados": 0}
    indice_por_chave = {chave_dedup(l["dados_empresa"]): i for i, l in enumerate(leads)}

    for idx, item in enumerate(lote, 1):
        decorrido = time.time() - inicio
        if config["max_runtime_seconds"] is not None and decorrido > config["max_runtime_seconds"]:
            print(f"[Orquestrador] Parando Wave2: {config['max_runtime_seconds']}s de execução atingidos.")
            break

        lead = item["dados_empresa"]
        print(f"[Wave2] [{idx}/{len(lote)}] Analisando {lead.get('nome', 'Empresa')} ({lead.get('website')})...")

        try:
            resultado = wave2_scoring.avaliar_lead(lead, icp, config)
        except Exception as e:
            print(f"[Wave2] Erro inesperado ao avaliar '{lead.get('nome', 'Empresa')}': {e}")
            resultado = {
                "website_analysis": {
                    "status": "unavailable", "error": str(e), "error_type": "unknown",
                    "checked_at": _now_iso(), "facts": {}, "signals_available": False, "signals": None,
                },
                "commercial_fit": {"score": 0, "reasons": ["erro inesperado durante avaliação"]},
                "website_opportunity": None, "priority_score": None, "priority_label": "needs_review",
                "wave2_evaluated_at": _now_iso(),
            }

        tentativas_anteriores = (item.get("website_analysis") or {}).get("attempts", 0)
        resultado["website_analysis"]["attempts"] = tentativas_anteriores + 1

        sucesso = resultado["website_analysis"]["status"] == "ok"
        if sucesso:
            status_lead = "analyzed"
        elif resultado["website_analysis"]["attempts"] >= config["max_retry_attempts"]:
            status_lead = "unavailable_permanent"
        else:
            status_lead = "needs_review"

        registro_atualizado = {**item, **resultado, "status": status_lead}
        leads[indice_por_chave[chave_dedup(lead)]] = registro_atualizado

        metricas["avaliados"] += 1
        metricas[status_lead] = metricas.get(status_lead, 0) + 1
        print(f"[Wave2]   -> status={status_lead} priority={resultado['priority_label']} "
              f"(cf={resultado['commercial_fit']['score']} wo={(resultado['website_opportunity'] or {}).get('score', '-')})")

        # Checkpoint: `leads` é sempre a lista COMPLETA (o loop sobrescreve in-place via
        # indice_por_chave), então salvar no meio grava um arquivo íntegro, só com menos
        # leads analisados. Sem isso, um Ctrl+C ou uma queda no meio de um lote grande
        # jogaria fora a rodada inteira -- ~2s de rede por site, 500 sites = ~17min.
        if metricas["avaliados"] % CHECKPOINT_WAVE2_A_CADA == 0:
            salvar_json(PATH_COM_SITE, leads)
            print(f"[Wave2]   💾 checkpoint: {metricas['avaliados']} analisado(s) em disco.")

    salvar_json(PATH_COM_SITE, leads)

    imprimir_top_sites_onda2(leads, config)
    imprimir_metricas_wave2(metricas, time.time() - inicio, leads)

    print("==================================================")
    print("🎉 Wave 2 concluída!")
    print(f"📁 Resultados salvos em: {PATH_COM_SITE}")
    print("==================================================")

    return metricas


def _psi_rodadas(registro):
    """Quantas rodadas de PSI este lead já teve. Ponto ÚNICO do default pra registros medidos
    antes do campo existir: se tem bloco psi, uma medição já aconteceu (1), senão nenhuma (0).
    Seleção e incremento leem daqui pelo mesmo motivo -- dois defaults separados divergem."""
    psi = registro.get("psi")
    if not psi:
        return 0
    return psi.get("rodadas", 1)


def _psi_reagendavel(registro, max_rodadas):
    """Uma medição que falhou volta pra fila só se a falha foi transiente E o lead ainda não
    esgotou as rodadas. Falha permanente (URL inválida, chave ruim, resposta em formato
    inesperado) daria exatamente o mesmo erro numa rodada futura -- reagendar só gastaria quota.

    Compatibilidade: registros medidos antes de 'falha_transiente'/'rodadas' existirem não têm
    esses campos. Assume transiente (dá a chance em vez de descartar o lead pra sempre por
    ausência de metadado) e rodadas=1 (uma medição já aconteceu, é o que se sabe de fato)."""
    psi = registro.get("psi") or {}
    if psi.get("estado") != psi_client.NAO_VERIFICADO:
        return False
    if not psi.get("falha_transiente", True):
        return False
    return _psi_rodadas(registro) < max_rodadas


def _selecionar_lote_psi(leads, batch_size, max_rodadas):
    """Mesmo padrão do _selecionar_lote_wave2: prioriza quem nunca foi medido antes de quem é
    retry, e nunca inclui quem já esgotou as rodadas nem quem já tem medição boa."""
    analisados = [l for l in leads if l.get("status") == "analyzed"]
    fila_nova = [l for l in analisados if not l.get("psi")]
    fila_retry = [l for l in analisados if l.get("psi") and _psi_reagendavel(l, max_rodadas)]
    fila = fila_nova + fila_retry
    return fila if batch_size is None else fila[:batch_size]


def fase_psi():
    """PSI (PageSpeed Insights), fase própria DEPOIS de fase_wave2. Só leads com site analisado
    (status 'analyzed'): os que nunca foram medidos, mais os que falharam por causa transiente e
    ainda têm rodada disponível (ver _selecionar_lote_psi). Isolada de propósito:
    website_analyzer/wave2_scoring continuam puros, offline e $0. Sem PSI_ENABLED/PSI_API_KEY,
    degrada -- não grava nada e a saída marca os campos de PSI como NAO_VERIFICADO. O
    performance_score NÃO entra no priority_score: vai cru pro output (Sistema 2 decide o peso
    e usa 'medido_em' pra revalidar)."""
    print("\n--- FASE: PSI (PageSpeed Insights, opcional) ---")
    if not psi_client.esta_habilitado():
        print("[PSI] PSI_ENABLED não ligado -- pulando (saída marca os campos de PSI como NAO_VERIFICADO).")
        return None

    leads = carregar_json(PATH_COM_SITE)
    alvos = _selecionar_lote_psi(leads, PSI_BATCH_SIZE, PSI_MAX_RODADAS_POR_LEAD)
    if not alvos:
        print("[PSI] Nenhum site analisado pendente de medição.")
        return None

    pendentes_totais = len(_selecionar_lote_psi(leads, None, PSI_MAX_RODADAS_POR_LEAD))
    if pendentes_totais > len(alvos):
        print(f"[PSI] {pendentes_totais} lead(s) pendente(s); medindo {len(alvos)} nesta rodada "
              f"(PSI_BATCH_SIZE). Rode de novo pra continuar de onde parou.")

    indice_por_chave = {chave_dedup(l["dados_empresa"]): i for i, l in enumerate(leads)}
    inicio = time.time()
    medidos = 0
    interrompido_por_tempo = False

    for idx, item in enumerate(alvos, 1):
        decorrido = time.time() - inicio
        if PSI_MAX_RUNTIME_SECONDS is not None and decorrido > PSI_MAX_RUNTIME_SECONDS:
            print(f"[PSI] Parando: {PSI_MAX_RUNTIME_SECONDS}s de execução atingidos "
                  f"(PSI_MAX_RUNTIME_SECONDS). {len(alvos) - medidos} lead(s) ficam pra próxima rodada.")
            interrompido_por_tempo = True
            break

        emp = item["dados_empresa"]
        url = emp.get("website")
        rodadas_anteriores = _psi_rodadas(item)
        print(f"[PSI] [{idx}/{len(alvos)}] {emp.get('nome', 'Empresa')} ({url})...")
        resultado = psi_client.medir(url)
        # 'tentativas' (do psi_client) conta chamadas DENTRO de uma medição; 'rodadas' conta
        # quantas vezes esta fase já voltou neste lead. São coisas diferentes: o teto entre
        # rodadas é o que impede um site quebrado de queimar quota pra sempre.
        resultado["rodadas"] = rodadas_anteriores + 1
        leads[indice_por_chave[chave_dedup(emp)]]["psi"] = resultado
        medidos += 1
        print(f"[PSI]   -> {resultado['estado']}"
              + (f" perf={resultado['performance_score']}" if resultado.get("performance_score") is not None else "")
              + f" (rodada {resultado['rodadas']}/{PSI_MAX_RODADAS_POR_LEAD})")
        if medidos % CHECKPOINT_WAVE2_A_CADA == 0:
            salvar_json(PATH_COM_SITE, leads)
            print(f"[PSI]   💾 checkpoint: {medidos} medição(ões) em disco.")

    salvar_json(PATH_COM_SITE, leads)
    print(f"[PSI] {medidos} medição(ões) gravada(s) em {PATH_COM_SITE}")
    restantes = len(_selecionar_lote_psi(leads, None, PSI_MAX_RODADAS_POR_LEAD))
    if restantes:
        print(f"[PSI] {restantes} lead(s) ainda pendente(s) -- rode `python main.py psi` de novo.")
    return {"medidos": medidos, "pendentes": restantes, "interrompido_por_tempo": interrompido_por_tempo}


# --- Fase de renderização (Etapa C, passo C4) -----------------------------------------------------
# Mede o site COM JavaScript (site_renderizado.py), um site por vez (Q7, sem paralelismo), só nos
# leads cuja classe do site é "proprio". Resultado em DADO INTERNO (registro de leads_com_site.json,
# chave "site_renderizado") e capturas em data/capturas_site/ -- ambos fora do Git. NÃO toca no
# contrato, no output_json, nos pesos nem no roteamento Onda 1/2. DESLIGADA por padrão.

def _pasta_capturas():
    # Calculada na hora (não constante de módulo): acompanha DATA_DIR, então a suíte, que redireciona
    # DATA_DIR para um tmp, nunca escreve no data/ real.
    return os.path.join(DATA_DIR, "capturas_site")


def _relativo_ao_data(caminho):
    if not caminho:
        return caminho
    try:
        rel = os.path.relpath(caminho, DATA_DIR)
    except ValueError:  # outro drive
        return caminho
    fora = rel == ".." or rel.startswith(".." + os.sep)
    return caminho if fora else rel.replace("\\", "/")


def _classe_site_do_registro(item):
    """A classe gravada na importação (C1); registros anteriores ao C1 não a têm -- recalcula da
    mesma função pura."""
    emp = item.get("dados_empresa") or {}
    return emp.get("classe_site") or site_classificacao.classificar_site(emp.get("website"))


def _render_bloco(estado, motivo, tentativas, url, resultado=None, detalhe=None):
    return {"estado": estado, "motivo": motivo, "detalhe": detalhe, "tentativas": tentativas,
            "avaliado_em": _now_iso(), "url": url, "resultado": resultado}


def _render_pendente(item, max_tentativas):
    """Quem ainda entra na fase. Sem bloco: nunca avaliado. 'pulado': só volta se a classe passou a ser
    "proprio". 'medido', 'anti_bot' e 'http_erro': TERMINAIS -- são fatos daquela data; repetir só
    bateria de novo num site que barrou/quebrou (remedir = apagar o bloco de propósito).
    'nao_verificado' por AMBIENTE (sem Playwright/navegador): sempre volta, sem gastar tentativa.
    'nao_verificado' por erro do site (timeout, DNS...): volta até max_tentativas."""
    bloco = item.get("site_renderizado")
    if not bloco:
        return True
    estado = bloco.get("estado")
    if estado == site_renderizado.ESTADO_PULADO:
        return _classe_site_do_registro(item) == site_classificacao.PROPRIO
    if estado == site_renderizado.ESTADO_NAO_VERIFICADO:
        if bloco.get("motivo") in (site_renderizado.MOTIVO_PLAYWRIGHT_INDISPONIVEL,
                                   site_renderizado.MOTIVO_NAVEGADOR_INDISPONIVEL):
            return True
        return bloco.get("tentativas", 1) < max_tentativas
    return False


def _render_ambiente_indisponivel(leads, alvos, motivo, detalhe):
    """Playwright ou navegador ausentes: o lead fica NAO_VERIFICADO com o motivo -- nunca "medido e sem
    problema" -- e NÃO gasta tentativa (o defeito é do ambiente, não do site)."""
    for item in alvos:
        anterior = (item.get("site_renderizado") or {}).get("tentativas", 0)
        item["site_renderizado"] = _render_bloco(
            site_renderizado.ESTADO_NAO_VERIFICADO, motivo, anterior,
            (item.get("dados_empresa") or {}).get("website"), None, detalhe)
    salvar_json(PATH_COM_SITE, leads)
    print(f"[Render] INDISPONÍVEL: {motivo} -- {detalhe}")
    print(f"[Render] {len(alvos)} lead(s) marcado(s) NAO_VERIFICADO; nada foi medido. "
          f"Resolva o ambiente e rode de novo: eles voltam para a fila.")
    return {"ambiente_indisponivel": motivo, "nao_verificado": len(alvos), "medido": 0}


def fase_render():
    """Fase de renderização (JS), DESLIGADA por padrão (RENDER_ENABLED). Depois de fase_wave2, mesmo
    desenho de fase_psi: só grava em dado interno; sem Playwright/navegador degrada com motivo."""
    print("\n--- FASE: RENDER (site com JavaScript, opcional) ---")
    if not site_renderizado.esta_habilitado():
        print(f"[Render] {site_renderizado.ENV_HABILITAR} não ligado -- pulando (nada é lido nem gravado).")
        return None

    max_tentativas = wave2_scoring.carregar_config_wave2()["max_retry_attempts"]
    leads = carregar_json(PATH_COM_SITE)
    pendentes = [l for l in leads if l.get("dados_empresa") and _render_pendente(l, max_tentativas)]
    if not pendentes:
        print("[Render] Nenhum lead com site pendente de renderização.")
        return None

    a_medir, pulados = [], 0
    for item in pendentes:
        emp = item["dados_empresa"]
        classe = _classe_site_do_registro(item)
        motivo_pulo = None
        if classe != site_classificacao.PROPRIO:
            motivo_pulo = f"classe_site:{classe}"
        elif not emp.get("place_id"):
            motivo_pulo = "sem_place_id"
        if motivo_pulo:
            item["site_renderizado"] = _render_bloco(site_renderizado.ESTADO_PULADO, motivo_pulo, 0, emp.get("website"))
            pulados += 1
        else:
            a_medir.append(item)
    if pulados:
        salvar_json(PATH_COM_SITE, leads)
        print(f"[Render] {pulados} lead(s) pulado(s) (classe do site diferente de 'proprio' ou sem place_id) -- não é erro.")
    if not a_medir:
        return {"medido": 0, "pulado": pulados}

    try:
        contexto = site_renderizado.abrir_playwright()
        playwright = contexto.__enter__()
    except site_renderizado.PlaywrightIndisponivelError as e:
        return _render_ambiente_indisponivel(leads, a_medir, site_renderizado.MOTIVO_PLAYWRIGHT_INDISPONIVEL, str(e))
    except Exception as e:
        return _render_ambiente_indisponivel(
            leads, a_medir, site_renderizado.MOTIVO_PLAYWRIGHT_INDISPONIVEL, f"não iniciou: {str(e)[:150]}")

    try:
        try:
            site_renderizado.verificar_navegador(playwright)
        except site_renderizado.NavegadorIndisponivelError as e:
            return _render_ambiente_indisponivel(leads, a_medir, site_renderizado.MOTIVO_NAVEGADOR_INDISPONIVEL, str(e))
        return _render_medir(leads, a_medir, playwright, max_tentativas, pulados)
    finally:
        contexto.__exit__(None, None, None)


def _render_medir(leads, a_medir, playwright, max_tentativas, pulados):
    pasta = _pasta_capturas()
    os.makedirs(pasta, exist_ok=True)
    contagem = {}
    try:
        for idx, item in enumerate(a_medir, 1):
            emp = item["dados_empresa"]
            url = emp.get("website")
            tentativas = (item.get("site_renderizado") or {}).get("tentativas", 0) + 1
            print(f"[Render] [{idx}/{len(a_medir)}] {emp.get('nome', 'Empresa')} ({url})...")
            try:
                ficha = site_renderizado.processar_lead(playwright, emp["place_id"], url, Path(pasta))
                for r in ficha["por_dispositivo"].values():
                    r["screenshot_ref"] = _relativo_ao_data(r.get("screenshot_ref"))
                estado, motivo = site_renderizado.resumir_estado_do_lead(ficha["por_dispositivo"])
                bloco = _render_bloco(estado, motivo, tentativas, url, ficha)
            except Exception as e:  # um site ruim nunca derruba o lote (mesmo espírito de fase_wave2)
                bloco = _render_bloco(site_renderizado.ESTADO_NAO_VERIFICADO, f"excecao:{type(e).__name__}",
                                      tentativas, url, None, str(e)[:200])
            item["site_renderizado"] = bloco
            contagem[bloco["estado"]] = contagem.get(bloco["estado"], 0) + 1
            print(f"[Render]   -> {bloco['estado']}" + (f" ({bloco['motivo']})" if bloco["motivo"] else "")
                  + f" (tentativa {tentativas}/{max_tentativas})")
            if idx % CHECKPOINT_RENDER_A_CADA == 0:
                salvar_json(PATH_COM_SITE, leads)
    finally:
        # Ctrl+C ou qualquer BaseException: o que já foi medido fica em disco.
        salvar_json(PATH_COM_SITE, leads)

    restantes = sum(1 for l in leads if l.get("dados_empresa") and _render_pendente(l, max_tentativas)
                    and _classe_site_do_registro(l) == site_classificacao.PROPRIO)
    print(f"[Render] {sum(contagem.values())} lead(s) medido(s) nesta rodada: {contagem}; capturas em {pasta}")
    if restantes:
        print(f"[Render] {restantes} lead(s) ainda pendente(s) -- rode `python main.py render` de novo.")
    return {**contagem, "pulado": pulados, "pendentes": restantes}


def _ler_origem_csv():
    meta = carregar_json(PATH_IMPORT_META)
    return meta.get("origem_csv") if isinstance(meta, dict) else None


def fase_saida():
    """Monta as DUAS saídas de trabalho do QUALIFICADOR (Etapa D, passo D6). Só leitura
    dos JSONs do pipeline, nunca grava neles.

    1. Contrato (máquina) QUALIFICADOR -> COMERCIAL: nata + candidatos_triagem +
       descartados, cada campo-evidência com seu estado de verificação (ver output_json).
       Grava em contrato.output_dir() (env QUALIFICADOR_OUTPUT_DIR), nome versionado por
       rodada -- nunca sobrescreve rodadas anteriores -- + sidecar .meta.json.
    2. CSV (humano) DIRETA + ESPERA -- os leads que NÃO atravessam o contrato (ver
       saida_humana). Grava na pasta oficial (saida_humana.saida_humana_dir(), dentro do
       repo) + cópia de conveniência best-effort fora do repo (QUALIFICADOR_SAIDA_HUMANA_DIR)."""
    print("\n--- FASE: SAÍDA (contrato QUALIFICADOR -> COMERCIAL + CSV humano) ---")
    origem_csv = _ler_origem_csv()
    qualificados = carregar_json(PATH_QUALIFICADOS)
    com_site = carregar_json(PATH_COM_SITE)
    saida = output_json.montar(
        qualificados,
        com_site,
        carregar_json(PATH_REPROVADOS),
        origem_csv=origem_csv,
    )

    # Validação contra o schema formal ANTES de gravar. Inválido -> levanta e nada é
    # escrito (nem o JSON, nem o sidecar).
    contrato.validar(saida)

    out_dir = contrato.output_dir()
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = f"leads_qualificados_{ts}_v{contrato.CONTRACT_VERSION}"
    path_json = os.path.join(out_dir, base + ".json")
    path_meta = os.path.join(out_dir, base + ".meta.json")

    s = saida["stats"]
    meta = {
        "contract_version": contrato.CONTRACT_VERSION,
        "gerado_em": saida["generated_at"],
        "origem_csv": origem_csv,
        "leads_total": s["leads_total"],
        "sem_site": s["sem_site"],
        "com_site": s["com_site"],
        "descartados": s["descartados"],
        "qualificador_versao": contrato.QUALIFICADOR_VERSION,
    }

    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=4)
    with open(path_meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=4)

    print(f"[Saída] {s['leads_total']} lead(s) ({s['sem_site']} sem site, {s['com_site']} com site) "
          f"+ {s['descartados']} descartado(s) → {path_json}")
    print(f"[Saída] sidecar → {path_meta}")
    if s["onda2_ainda_pendente"]:
        print(f"[Saída] ⏳ {s['onda2_ainda_pendente']} lead(s) da Onda 2 ainda sem análise (não entram na saída ainda).")

    # --- Saída humana (CSV): DIRETA + ESPERA, fora do contrato ---------------------------
    linhas_humanas = saida_humana.montar_linhas(qualificados, com_site)
    pasta_oficial = saida_humana.saida_humana_dir()
    os.makedirs(pasta_oficial, exist_ok=True)
    path_csv = saida_humana.caminho_sem_sobrescrever(pasta_oficial, saida_humana.nome_arquivo(ts))
    saida_humana.escrever_csv(linhas_humanas, path_csv)
    saida_humana.escrever_leiame(pasta_oficial)
    print(f"[Saída humana] {len(linhas_humanas)} lead(s) → {path_csv}")

    pasta_copia = saida_humana.copia_conveniencia_dir()
    ok_copia, msg_copia = saida_humana.copiar_conveniencia(path_csv, pasta_copia)
    if pasta_copia:
        if ok_copia:
            print(f"[Saída humana] cópia de conveniência → {msg_copia}")
        else:
            print(f"[Saída humana] ⚠ {msg_copia}")

    direta = sum(1 for l in linhas_humanas if l["pista"] == saida_humana.PISTA_DIRETA)
    espera = sum(1 for l in linhas_humanas if l["pista"] == saida_humana.PISTA_ESPERA)

    print("\n[Resumo]")
    print(f"  nata: {s['nata']}")
    print(f"  candidatos_triagem: {s['candidatos_triagem']}")
    print(f"  direta: {direta}")
    print(f"  espera: {espera}")
    print(f"  descartados: {s['descartados']}")
    print(f"  contrato   → {path_json}")
    print(f"  saída humana → {path_csv}")

    return s


# --- Leads reprovados: consulta, reavaliação e arquivamento do pool (07/10/2026) --------------

def _arquivos_do_pool():
    """O que o arquivar-pool zera (e o backup copia, junto com o histórico)."""
    return [PATH_COLETADOS, PATH_COM_SITE, PATH_QUALIFICADOS, PATH_REPROVADOS, PATH_IMPORT_META]


def _carimbo_hora_local():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _fazer_backup(prefixo, pastas=()):
    """Backup conferido por hash do pool + histórico (+ `pastas`). Levanta rep.BackupFalhouError;
    backup pela metade fica como ...-INCOMPLETO, nunca apagado."""
    pasta, copiados, ausentes = rep.backup_conferido(
        _arquivos_do_pool() + [PATH_HISTORICO_REPROVADOS], prefixo, _carimbo_hora_local(), pastas=pastas)
    print(f"Backup feito e conferido ({len(copiados)} arquivo(s), cada cópia igual ao original): {pasta}")
    if ausentes:
        print(f"  (não existiam, nada a copiar: {', '.join(ausentes)})")
    return pasta


def fase_reprovados(desde=None, ate=None, motivo=None, campanha=None, cidade=None, categoria=None, lista=False,
                    fuso=None):
    """Consulta SÓ DE LEITURA ao histórico permanente das reprovações. `fuso` (tzinfo) só para
    teste; None = fuso local do computador."""
    todas, ilegiveis = rep.ler_historico(PATH_HISTORICO_REPROVADOS)
    filtros = {"desde": desde, "ate": ate, "motivo": motivo, "campanha": campanha,
               "cidade": cidade, "categoria": categoria}
    selecionadas = rep.filtrar(todas, **filtros, fuso=fuso)
    for linha in rep.relatorio(todas, selecionadas, filtros, ilegiveis, PATH_HISTORICO_REPROVADOS, lista, fuso):
        print(linha)
    return selecionadas


def _resumo_lead(emp, vezes=1):
    repetido = f" (aparece {vezes} vezes)" if vezes > 1 else ""
    return (f"{emp.get('nome') or '?'} · {emp.get('nicho') or '?'} · {emp.get('campanha_cidade') or '?'} "
            f"(campanha {emp.get('campanha_id') or '?'}){repetido}")


def _planejar_reavaliacao():
    """Calcula, SÓ EM MEMÓRIA, o que a reavaliação faria. Nada é gravado aqui.

    Entram os registros de leads_reprovados.json cortados por categoria. Cada um é repassado
    pela versão ATUAL da campanha do próprio lead (campanha_id). O que passa na categoria
    segue o resto do import que não chegou a fazer: filtros comerciais, separação em ondas e
    filtro de redes sobre o pool inteiro (mesma regra do import).

    Tudo é POR LEAD (chave de dedupe): um lead com vários registros aparece uma vez, com
    `vezes` = quantas vezes está em leads_reprovados.json; repetido nunca volta (olho humano)."""
    reprovados_disco = carregar_json(PATH_REPROVADOS)
    plano = {"candidatos": [], "registros_candidatos": 0, "vezes": {}, "sem_campanha": [], "continua_fora": [],
             "ja_no_pool": [], "repetidos": [], "wave1": [], "wave2": [], "outro_filtro": [], "rede": None,
             "registro_por_chave": {}, "conhecidas": set()}
    candidatos = [r for r in reprovados_disco
                  if r.get("dados_empresa") and r.get("rejection_reason") in rep.MOTIVOS_DE_CATEGORIA]
    plano["registros_candidatos"] = len(candidatos)
    por_chave = {}
    for r in candidatos:
        por_chave.setdefault(chave_dedup(r["dados_empresa"]), r)  # o primeiro registro representa o lead
    plano["candidatos"] = list(por_chave.values())
    if not plano["candidatos"]:
        return plano
    campanhas = {c["id"]: c for c in campanha_mod.carregar_campanhas_disponiveis()}
    chaves_ativas = chaves_conhecidas(*(carregar_json(p) for p in _arquivos_pool_ativo()))
    contagem = plano["vezes"]
    for r in reprovados_disco:
        if r.get("dados_empresa"):
            chave = chave_dedup(r["dados_empresa"])
            contagem[chave] = contagem.get(chave, 0) + 1

    passam = []
    for chave, registro in por_chave.items():
        emp = json.loads(json.dumps(registro["dados_empresa"]))  # cópia: o disco só muda no --confirmar
        camp = campanhas.get(emp.get("campanha_id"))
        if camp is None:
            plano["sem_campanha"].append(registro)
            continue
        corte = campanha_mod.motivo_categoria(emp.get("nicho"), camp)
        if corte:
            plano["continua_fora"].append((registro, corte[0]))
        elif chave in chaves_ativas:
            plano["ja_no_pool"].append(registro)
        elif contagem[chave] > 1:
            plano["repetidos"].append(registro)
        else:
            passam.append(emp)
            plano["registro_por_chave"][chave] = registro
    if not passam:
        return plano

    aprovados, outro_filtro = AgentColetor._aplicar_filtros_comerciais(passam)
    wave1, wave2 = AgentColetor._classificar_campanha(aprovados)
    chaves_voltam = set(plano["registro_por_chave"])
    conhecidas = _todas_chaves_conhecidas() - chaves_voltam
    plano["rede"] = _aplicar_filtro_rede(wave1, wave2, outro_filtro, rede_multiunidade.carregar_config(),
                                         conhecidas, chaves_fora_do_pool=chaves_voltam)
    plano.update(wave1=wave1, wave2=wave2, outro_filtro=outro_filtro, conhecidas=conhecidas)
    return plano


def _imprimir_plano_reavaliacao(plano):
    def resumo(emp):
        return _resumo_lead(emp, plano["vezes"].get(chave_dedup(emp), 1))

    print("==================================================")
    print(" REAVALIAÇÃO DOS REPROVADOS POR CATEGORIA")
    print(" (cada lead pela versão atual da campanha dele)")
    print("==================================================")
    registros = (f" ({plano['registros_candidatos']} registros)"
                 if plano["registros_candidatos"] != len(plano["candidatos"]) else "")
    print(f"Reprovados por categoria no pool atual: {len(plano['candidatos'])} lead(s){registros}")
    voltam = [(e, "Onda 1 (sem site)") for e in plano["wave1"]] + [(e, "Onda 2 (com site)") for e in plano["wave2"]]
    print(f"\nVoltariam para a fila: {len(voltam)} lead(s)")
    for emp, destino in voltam:
        print(f"  - {resumo(emp)} -> {destino}")
    print(f"\nContinuam fora, porque a categoria ainda não serve: {len(plano['continua_fora'])} lead(s)")
    for registro, motivo in plano["continua_fora"]:
        print(f"  - {resumo(registro['dados_empresa'])}: {rep.rotulo_motivo(motivo)}")
    print(f"\nPassam na categoria, mas continuam fora por outro motivo: {len(plano['outro_filtro'])} lead(s)")
    for lead in plano["outro_filtro"]:
        print(f"  - {resumo(lead)}: {rep.rotulo_motivo(lead.get('rejection_reason'))}")
    if plano["sem_campanha"]:
        print(f"\nCampanha não encontrada (o lead não volta): {len(plano['sem_campanha'])} lead(s)")
        for registro in plano["sem_campanha"]:
            print(f"  - {resumo(registro['dados_empresa'])}")
    if plano["ja_no_pool"]:
        print(f"\nJá estão no pool ativo (não duplicam, ficam como estão): {len(plano['ja_no_pool'])} lead(s)")
        for registro in plano["ja_no_pool"]:
            print(f"  - {resumo(registro['dados_empresa'])}")
    if plano["repetidos"]:
        print(f"\nAparecem mais de uma vez nos reprovados (não voltam; precisam de olho humano): "
              f"{len(plano['repetidos'])} lead(s)")
        for registro in plano["repetidos"]:
            print(f"  - {resumo(registro['dados_empresa'])}")
    movidos = (plano["rede"] or {}).get("registros_movidos") or []
    if movidos:
        print(f"\nATENÇÃO: fichas que hoje estão ATIVAS e sairiam do pool, porque formam rede com um lead "
              f"devolvido (mesma regra do import): {len(movidos)}")
        for registro in movidos:
            print(f"  - {resumo(registro['dados_empresa'])}")
    print("==================================================")


def fase_reavaliar(confirmar=False):
    """Sem `confirmar`: só MOSTRA o que voltaria para a fila -- nenhum arquivo é tocado.
    Com `confirmar`: backup conferido do pool, depois aplica e registra cada devolução no
    histórico."""
    try:
        plano = _planejar_reavaliacao()
    except (campanha_mod.CampanhaInvalidaError, rede_multiunidade.ConfigRedeInvalidaError) as e:
        print(f"Não consegui reavaliar: {e}\nNada foi alterado.")
        return None
    _imprimir_plano_reavaliacao(plano)
    rede = plano["rede"]
    ha_mudanca = bool(plano["wave1"] or plano["wave2"] or plano["outro_filtro"])
    if not confirmar:
        print("Nada foi alterado (esta é só a prévia).")
        if ha_mudanca:
            print("Para aplicar o que está acima, rode: python main.py reavaliar --confirmar")
        return {"confirmado": False, "plano": plano}
    if not ha_mudanca:
        print("Não há nada para aplicar. Nenhum arquivo foi alterado.")
        return {"confirmado": True, "plano": plano, "devolvidos": 0}

    try:
        backup = _fazer_backup("pool-antes-de-reavaliar")
    except rep.BackupFalhouError as e:
        print(f"O backup falhou: {e}")
        return None

    agora = _now_iso()
    novos_registros = [_registro_reprovado(lead, rep.ETAPA_REAVALIACAO, agora) for lead in plano["outro_filtro"]]
    for caminho in rede["pool_alterado"] - {PATH_REPROVADOS}:
        salvar_json(caminho, rede["pool"][caminho])
    salvar_json(PATH_REPROVADOS, rede["pool"][PATH_REPROVADOS] + novos_registros)
    n1 = _acrescentar_novos(PATH_COLETADOS, plano["wave1"], "eligible", plano["conhecidas"])
    n2 = _acrescentar_novos(PATH_COM_SITE, plano["wave2"], "queued_future", plano["conhecidas"])

    linhas = rep.linhas_reprovacao(rede["registros_movidos"]) + rep.linhas_reprovacao(novos_registros)
    for lista, destino in ((plano["wave1"], "onda1"), (plano["wave2"], "onda2")):
        for emp in lista:
            anterior = plano["registro_por_chave"][chave_dedup(emp)]
            linhas.append(rep.linha_devolucao(anterior, emp, destino, agora))
    rep.acrescentar_historico(PATH_HISTORICO_REPROVADOS, linhas)

    print(f"Feito: {n1 + n2} lead(s) devolvido(s) à fila ({n1} na Onda 1, {n2} na Onda 2); "
          f"{len(novos_registros)} continuam fora por outro motivo; "
          f"{len(rede['registros_movidos'])} ficha(s) ativa(s) saíram por rede.")
    print("Cada devolução ficou anotada no histórico de reprovados.")
    return {"confirmado": True, "plano": plano, "devolvidos": n1 + n2, "backup": str(backup)}


def fase_arquivar_pool(confirmar=False):
    """Único jeito de arquivar o pool. Sem `confirmar`: só mostra. Com `confirmar`: copia os
    quatro JSONs, o _import_meta.json, o histórico e a pasta data/capturas_site/ para o backup,
    confere cada cópia por hash e SÓ ENTÃO zera os quatro JSONs e o _import_meta.json e remove
    data/capturas_site/. O histórico nunca é movido, zerado nem alterado; data/logs/ fica onde
    está."""
    print("==================================================")
    print(" ARQUIVAR O POOL DO QUALIFICADOR")
    print("==================================================")
    for caminho in _arquivos_do_pool():
        nome = os.path.basename(caminho)
        if os.path.exists(caminho):
            dados = carregar_json(caminho)
            qtd = f"{len(dados)} registro(s)" if isinstance(dados, list) else "metadado da última importação"
            print(f"  {nome}: {qtd} -> vai para o backup e depois é zerado")
        else:
            print(f"  {nome}: não existe (nada a fazer)")
    capturas = _pasta_capturas()
    if os.path.isdir(capturas):
        n_capturas = sum(1 for p in Path(capturas).rglob("*") if p.is_file())
        print(f"  capturas_site/: {n_capturas} arquivo(s) de captura de site -> vão para o backup e depois "
              f"saem do data/")
    else:
        print("  capturas_site/: não existe (nada a fazer)")
    hist_existe = os.path.exists(PATH_HISTORICO_REPROVADOS)
    print(f"  {os.path.basename(PATH_HISTORICO_REPROVADOS)}: "
          + ("é copiado para o backup e CONTINUA no lugar, sem nenhuma mudança" if hist_existe
             else "ainda não existe (nada a copiar)"))
    print("  logs/: fica onde está (não entra no arquivamento)")
    print(f"Pasta do backup: {rep.dir_backups()}{os.sep}pool-arquivado-<data e hora>")
    if not confirmar:
        print("Nada foi alterado (esta é só a prévia). Para arquivar de verdade, rode: "
              "python main.py arquivar-pool --confirmar")
        return {"confirmado": False}

    hash_hist_antes = rep.sha256(PATH_HISTORICO_REPROVADOS) if hist_existe else None
    try:
        backup = _fazer_backup("pool-arquivado", pastas=[capturas])
    except rep.BackupFalhouError as e:
        print(f"O backup falhou: {e}")
        print("O pool NÃO foi zerado.")
        return None

    for caminho in [PATH_COLETADOS, PATH_COM_SITE, PATH_QUALIFICADOS, PATH_REPROVADOS]:
        salvar_json(caminho, [])
    salvar_json(PATH_IMPORT_META, {})
    havia_capturas = os.path.isdir(capturas)
    if havia_capturas:
        shutil.rmtree(capturas)  # só depois de cada captura copiada e conferida por hash

    hash_hist_depois = rep.sha256(PATH_HISTORICO_REPROVADOS) if os.path.exists(PATH_HISTORICO_REPROVADOS) else None
    if hash_hist_depois != hash_hist_antes:
        print("ATENÇÃO: o histórico de reprovados mudou durante o arquivamento -- confira o backup.")
    print("Pool arquivado: os quatro arquivos de leads e o _import_meta.json foram zerados"
          + (", e as capturas de site saíram do data/ (estão no backup)." if havia_capturas else "."))
    print("O histórico de reprovados ficou intacto.")
    print(f"Backup: {backup}")
    return {"confirmado": True, "backup": str(backup), "historico_intacto": hash_hist_depois == hash_hist_antes}


def fase_all(caminho_csv=None):
    """Comando único: importa (se um CSV for passado) e roda 1 lote de cada esteira —
    Onda 1 (fase_qualify) e Onda 2 (fase_wave2). As duas ondas são 100% $0 -- não esvazia a
    fila inteira, só avança 1 lote por execução; rodar de novo continua de onde parou."""
    print("\n--- FASE: ALL (import opcional + GBP + 1 lote Onda 1 + 1 lote Onda 2) ---")
    if caminho_csv:
        importar_csv(caminho_csv)

    fase_gbp()
    metricas_qualify = fase_qualify()
    metricas_wave2 = fase_wave2()
    fase_psi()
    if site_renderizado.esta_habilitado():
        fase_render()
    fase_saida()

    custo_onda1 = metricas_qualify["custo_total_usd"] if metricas_qualify else 0.0

    print("\n==================================================")
    print("🧾 LOG DE CUSTO — RODADA COMPLETA (ONDA 1 + ONDA 2)")
    print("==================================================")
    print(f"Onda 1 (Qualification, Python puro, $0): ${custo_onda1:.4f}")
    print("Onda 2 (pré-qualificação de sites): $0.0000 (sem LLM)")
    print(f"TOTAL da rodada: ${custo_onda1:.4f}")
    print("==================================================")

    return {"custo_total_usd": custo_onda1, "onda1": metricas_qualify, "onda2": metricas_wave2}


def _tornar_console_tolerante(fluxos=None):
    """Troca só o *error handler* de encoding de stdout/stderr para "replace" -- nunca a
    codificação em si. Existe porque o console padrão do Windows normalmente está em
    cp1252, que não tem os emojis/setas decorativos usados nos prints deste módulo (🤖,
    →, 🎉, ⏳...); sem isto, a primeira linha do banner já derruba o processo com
    UnicodeEncodeError, antes de fazer qualquer coisa, e só roda com
    `PYTHONIOENCODING=utf-8` -- que o operador não tem por que conhecer nem configurar.
    Escolhida em vez de forçar UTF-8: o console não entende UTF-8 sem `chcp 65001`
    (mudança de ambiente que também não é razoável pedir do operador) e escreveria byte
    UTF-8 interpretado como cp1252 -- lixo, não acento certo. `errors="replace"`
    substitui só o caractere impossível por "?"; os acentos (á, ç, ã, é, ô...) continuam
    saindo certos, porque cp1252 já os cobre -- provado em
    test_console_tolerante.py::test_tornar_console_tolerante_preserva_acentos_e_troca_emoji."""
    for fluxo in fluxos if fluxos is not None else (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is None:
            continue  # stream sem reconfigure() (ex.: capturado por um runner de teste)
        try:
            reconfigurar(errors="replace")
        except ValueError:
            pass  # stream já fechado ou não suporta -- nunca trava a rodada por causa disto


def run():
    _tornar_console_tolerante()

    parser = argparse.ArgumentParser(
        description="Sistema de prospecção: importa leads de um CSV do Google Maps e os prepara (determinístico, $0) pro Sistema 2.",
    )
    parser.add_argument("command", nargs="?", choices=["gbp", "qualify", "wave2", "psi", "render", "saida", "all",
                                                       "reprovados", "reavaliar", "arquivar-pool"],
                        help="'gbp' diagnóstico de ficha, 'qualify' Onda 1, 'wave2' Onda 2, 'psi' PageSpeed (opcional), 'render' site com JavaScript (opcional, desligado por padrão: RENDER_ENABLED), 'saida' (re)monta leads_saida.json, 'all' roda tudo (importando primeiro se --csv for passado), 'reprovados' consulta o histórico de reprovados (só leitura), 'reavaliar' repassa os reprovados por categoria pela campanha atual (só mostra; aplica com --confirmar), 'arquivar-pool' arquiva o pool com backup (só mostra; aplica com --confirmar).")
    parser.add_argument("--csv", dest="csv_path", metavar="ARQUIVO", help="Importa leads a partir deste CSV (custo $0). Combinado com 'all', importa e já processa em seguida.")
    parser.add_argument("--desde", metavar="AAAA-MM-DD", help="reprovados: só a partir desta data.")
    parser.add_argument("--ate", metavar="AAAA-MM-DD", help="reprovados: só até esta data.")
    parser.add_argument("--motivo", help="reprovados: só este motivo (código, ex.: icp_categoria_fora_do_perfil).")
    parser.add_argument("--campanha", help="reprovados: campanha contendo este texto.")
    parser.add_argument("--cidade", help="reprovados: cidade da busca contendo este texto.")
    parser.add_argument("--categoria", help="reprovados: categoria do Google contendo este texto.")
    parser.add_argument("--lista", action="store_true", help="reprovados: mostra também cada lead.")
    parser.add_argument("--confirmar", action="store_true", help="reavaliar / arquivar-pool: aplica de verdade (sem isto, só mostra).")
    args = parser.parse_args()
    if args.confirmar and args.command not in ("reavaliar", "arquivar-pool"):
        parser.error("--confirmar só vale para 'reavaliar' e 'arquivar-pool'.")
    filtros_usados = any(getattr(args, n) for n in ("desde", "ate", "motivo", "campanha", "cidade", "categoria", "lista"))
    if filtros_usados and args.command != "reprovados":
        parser.error("--desde, --ate, --motivo, --campanha, --cidade, --categoria e --lista só valem para 'reprovados'.")
    for nome in ("desde", "ate"):
        if getattr(args, nome):
            try:
                setattr(args, nome, rep.parse_data(getattr(args, nome)))
            except ValueError as e:
                parser.error(str(e))

    # Carrega prospeccao_ia/.env (se existir) sem sobrescrever o ambiente real. É o ponto
    # que faz PSI_ENABLED/PSI_API_KEY no .env terem efeito -- o resto do código lê os.environ
    # direto. Só no entrypoint: testes que chamam as fases direto não disparam isto.
    definidas = env_loader.carregar_env()
    if definidas:
        print(f"[env] .env carregado: {', '.join(sorted(definidas))}")

    print("==================================================")
    print(" 🤖 SISTEMA AUTÔNOMO DE PROSPECÇÃO (ESPANHA) 🤖")
    print("==================================================")

    if not args.csv_path:
        _despachar(args, parser)
        return
    # Com import: erro previsto vira mensagem curta + log + código de saída (erro_import);
    # qualquer outro erro grava o log e sobe como sempre -- nunca é engolido.
    try:
        _despachar(args, parser)
    except erro_import.PREVISTOS as e:
        log = erro_import.gravar_log(e, LOG_DIR)
        print(erro_import.mensagem(e, log), file=sys.stderr)
        sys.exit(erro_import.CODIGO_SAIDA)
    except Exception as e:
        log = erro_import.gravar_log(e, LOG_DIR)
        print(f"\n[Erro inesperado] detalhe técnico também gravado em: {log}", file=sys.stderr)
        raise


def _despachar(args, parser):
    if args.command == "all":
        fase_all(args.csv_path)
    elif args.csv_path:
        importar_csv(args.csv_path)
    elif args.command == "gbp":
        fase_gbp()
    elif args.command == "qualify":
        fase_qualify()
    elif args.command == "wave2":
        fase_wave2()
    elif args.command == "psi":
        fase_psi()
    elif args.command == "render":
        fase_render()
    elif args.command == "saida":
        fase_saida()
    elif args.command == "reprovados":
        fase_reprovados(desde=getattr(args, "desde", None), ate=getattr(args, "ate", None),
                        motivo=getattr(args, "motivo", None), campanha=getattr(args, "campanha", None),
                        cidade=getattr(args, "cidade", None), categoria=getattr(args, "categoria", None),
                        lista=getattr(args, "lista", False))
    elif args.command == "reavaliar":
        fase_reavaliar(confirmar=getattr(args, "confirmar", False))
    elif args.command == "arquivar-pool":
        fase_arquivar_pool(confirmar=getattr(args, "confirmar", False))
    else:
        parser.print_help()


if __name__ == "__main__":
    run()
