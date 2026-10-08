"""Leads reprovados: carimbo, histórico permanente, consulta e backup do pool.

Decisão do diretor (07/10/2026). Tudo aqui é dado INTERNO do QUALIFICADOR -- nada deste
módulo atravessa para o COMERCIAL:

- carimbo de cada reprovação (`reprovado_em`, `origem_csv`, `termo_busca`, `etapa`) no
  registro de `leads_reprovados.json`, no nível do registro (output_json só lê
  `dados_empresa`, `rejection_reason` e `rejection_detail`);
- `detalhe_interno`: o detalhe dos cortes da Onda 1. NUNCA `rejection_detail`, que
  atravessa o contrato como `detalhe_do_corte` (output_json._descartado_saida);
- histórico `data/historico_reprovados.jsonl`: só de acréscimo, uma linha por evento
  (`reprovado` ou `devolvido`), nunca reescrito, deduplicado nem zerado -- nem pelo
  arquivamento do pool;
- backup conferido por sha256 dos arquivos do pool, fora do repositório (arquivar-pool e
  reavaliar --confirmar).

A orquestração (quais arquivos, quando gravar) fica em main.py; aqui só funções sobre
listas, registros e caminhos recebidos.
"""
import copy
import hashlib
import json
import os
import shutil
from datetime import date, datetime
from pathlib import Path

import campanha as campanha_mod
import contrato
import telefone_utils

ETAPA_IMPORT = "import"
ETAPA_ONDA1 = "onda1"
ETAPA_REDE_POOL = "rede_pool"
ETAPA_REAVALIACAO = "reavaliacao"

EVENTO_REPROVADO = "reprovado"
EVENTO_DEVOLVIDO = "devolvido"

# Pasta-raiz dos backups, FORA do repositório: <pasta que contém o LeadFarm>/_backups/leadfarm.
# Derivada de contrato.eqc_root() (nunca caminho absoluto de máquina); env só para teste.
ENV_BACKUP_DIR = "QUALIFICADOR_BACKUP_DIR"

# Motivo -> frase para o diretor. Motivo sem frase aparece com o próprio código.
ROTULOS_MOTIVO = {
    "large_organization": "organização grande: hospital, grupo ou rede",
    "no_contact_no_signal": "sem telefone, sem e-mail e sem nota no Google",
    "sem_canal_de_contato": "sem canal para abordar: sem e-mail, sem rede social e sem celular",
    "qualification_declined": "sem nenhum sinal: sem nota, sem avaliações e sem rede social",
    "icp_categoria_fora_do_perfil": "categoria fora do perfil da campanha",
    "icp_categoria_excluida": "categoria excluída pela campanha",
    "icp_rating_abaixo_minimo": "nota do Google abaixo do mínimo",
    "icp_reviews_abaixo_minimo": "poucas avaliações, abaixo do mínimo",
    "rede_ou_multiunidade": "rede ou várias unidades do mesmo negócio",
    "linha_deslocada_irrecuperavel": "linha da lista com dados trocados, sem conserto seguro",
    "unknown": "motivo não registrado",
}

MOTIVOS_DE_CATEGORIA = (campanha_mod.MOTIVO_FORA_DO_PERFIL, campanha_mod.MOTIVO_EXCLUIDA)


def rotulo_motivo(motivo):
    frase = ROTULOS_MOTIVO.get(motivo)
    return f"{frase} ({motivo})" if frase else str(motivo)


# --- carimbo -------------------------------------------------------------------------------


def carimbo_import(origem_csv, termo_busca) -> dict:
    """Gravado em `dados_empresa` de cada lead no import, para a Onda 1 achar depois de que
    lista e de que busca o lead veio."""
    return {"origem_csv": origem_csv, "termo_busca": termo_busca}


def carimbar_registro(registro, etapa, agora):
    """Acrescenta ao registro de reprovação (in place) data, origem e etapa."""
    emp = registro.get("dados_empresa") or {}
    registro["reprovado_em"] = agora
    registro["origem_csv"] = emp.get("origem_csv")
    registro["termo_busca"] = emp.get("termo_busca")
    registro["etapa"] = etapa
    return registro


def detalhe_onda1(lead, motivo, icp=None, qualificacao=None):
    """`detalhe_interno` de um corte da Onda 1 (fatos que causaram o corte)."""
    icp = icp or {}
    if motivo == "icp_rating_abaixo_minimo":
        return {"nota_google": lead.get("nota_google"), "minimo": icp.get("rating_minimo")}
    if motivo == "icp_reviews_abaixo_minimo":
        return {"review_count": lead.get("review_count"), "minimo": icp.get("reviews_minimo")}
    if motivo == "sem_canal_de_contato":
        return {"tem_email": bool(lead.get("email")), "tem_instagram": bool(lead.get("instagram")),
                "tem_facebook": bool(lead.get("facebook")),
                "telefone_celular_espanhol": telefone_utils.e_movel_espanhol(lead.get("telefone"))}
    if motivo == "qualification_declined":
        qual = qualificacao or {}
        return {"score": qual.get("score"), "reasons": qual.get("reasons")}
    return None


# --- histórico -----------------------------------------------------------------------------


def _linha_historico(evento, registro, em, extra=None):
    emp = registro.get("dados_empresa") or {}
    linha = {
        "evento": evento,
        "em": em,
        "place_id": emp.get("place_id"),
        "nome": emp.get("nome"),
        "categoria": emp.get("nicho"),
        "campanha_id": emp.get("campanha_id"),
        "campanha_nicho": emp.get("campanha_nicho"),
        "campanha_cidade": emp.get("campanha_cidade"),
        "origem_csv": registro.get("origem_csv", emp.get("origem_csv")),
        "termo_busca": registro.get("termo_busca", emp.get("termo_busca")),
        "etapa": registro.get("etapa"),
        "motivo": registro.get("rejection_reason"),
        "rejection_detail": registro.get("rejection_detail"),
        "detalhe_interno": registro.get("detalhe_interno"),
        "dados_empresa": copy.deepcopy(emp),
    }
    if extra:
        linha.update(extra)
    return linha


def acrescentar_historico(caminho, linhas):
    """Só ACRESCENTA (modo "a"): nunca reescreve, deduplica nem apaga linha existente."""
    if not linhas:
        return 0
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "a", encoding="utf-8", newline="\n") as f:
        for linha in linhas:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return len(linhas)


def linhas_reprovacao(registros):
    return [_linha_historico(EVENTO_REPROVADO, r, r.get("reprovado_em")) for r in registros]


def linha_devolucao(registro_anterior, dados_empresa, destino, em):
    """Linha `devolvido`: o registro de reprovação que saiu (motivo, data) e o destino."""
    base = {**registro_anterior, "dados_empresa": dados_empresa}
    return _linha_historico(EVENTO_DEVOLVIDO, base, em, {
        "reprovado_em_anterior": registro_anterior.get("reprovado_em"),
        "destino": destino,
    })


def ler_historico(caminho):
    """Lista de linhas do histórico. Linha ilegível é contada, nunca descartada em silêncio."""
    if not os.path.exists(caminho):
        return [], 0
    linhas, ilegiveis = [], 0
    with open(caminho, "r", encoding="utf-8") as f:
        for texto in f:
            texto = texto.strip()
            if not texto:
                continue
            try:
                linhas.append(json.loads(texto))
            except json.JSONDecodeError:
                ilegiveis += 1
    return linhas, ilegiveis


# --- consulta ------------------------------------------------------------------------------


def _instante(iso):
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def _data_local(iso, fuso=None):
    """Data do evento no fuso `fuso` (tzinfo); None = fuso local do computador."""
    instante = _instante(iso)
    if instante is None:
        return None
    return instante.astimezone(fuso).date()


def _contem(valor, filtro):
    return campanha_mod.normalizar(filtro) in campanha_mod.normalizar(valor or "")


def _id_lead(linha):
    return linha.get("place_id") or f"nome:{linha.get('nome')}"


def filtrar(linhas, desde=None, ate=None, motivo=None, campanha=None, cidade=None, categoria=None, fuso=None):
    """Só as reprovações (evento `reprovado`) que passam em todos os filtros. Datas pela data no
    fuso `fuso` (None = fuso local do computador); campanha/cidade/categoria por trecho, sem
    acento nem maiúscula."""
    saida = []
    for l in linhas:
        if l.get("evento") != EVENTO_REPROVADO:
            continue
        dia = _data_local(l.get("em"), fuso)
        if desde and (dia is None or dia < desde):
            continue
        if ate and (dia is None or dia > ate):
            continue
        if motivo and l.get("motivo") != motivo:
            continue
        if campanha and not _contem(l.get("campanha_id"), campanha):
            continue
        if cidade and not _contem(l.get("campanha_cidade"), cidade):
            continue
        if categoria and not _contem(l.get("categoria"), categoria):
            continue
        saida.append(l)
    return saida


def _contar(linhas, chave, rotulo=None):
    contagem = {}
    for l in linhas:
        valor = l.get(chave)
        nome = rotulo(valor) if rotulo else (valor if valor not in (None, "") else "(sem informação)")
        contagem[nome] = contagem.get(nome, 0) + 1
    return sorted(contagem.items(), key=lambda kv: (-kv[1], str(kv[0])))


def _fmt_data(dia):
    return dia.strftime("%d/%m/%Y")


def seguidas_de_devolucao(selecionadas, todas):
    """Reprovações que tiveram uma devolução do MESMO lead DEPOIS delas (compara os instantes).
    Uma devolução anterior à reprovação (o lead voltou e foi reprovado de novo) não conta."""
    devolucoes = {}
    for l in todas:
        if l.get("evento") == EVENTO_DEVOLVIDO and _instante(l.get("em")):
            devolucoes.setdefault(_id_lead(l), []).append(_instante(l.get("em")))
    saida = []
    for l in selecionadas:
        quando = _instante(l.get("em"))
        if quando and any(d > quando for d in devolucoes.get(_id_lead(l), [])):
            saida.append(l)
    return saida


def _contagem_eventos_e_leads(linhas):
    n_leads = len({_id_lead(l) for l in linhas})
    return f"{len(linhas)} reprovação(ões), de {n_leads} lead(s) diferente(s)"


def relatorio(todas, selecionadas, filtros, ilegiveis=0, caminho=None, lista=False, fuso=None):
    """Texto da consulta, em linguagem clara (devolve a lista de linhas para imprimir)."""
    out = ["==================================================",
           " LEADS REPROVADOS — consulta (nada é alterado)",
           "=================================================="]
    reprovacoes = [l for l in todas if l.get("evento") == EVENTO_REPROVADO]
    if not reprovacoes:
        out.append("Ainda não há nenhuma reprovação anotada no histórico.")
        if caminho:
            out.append(f"(arquivo do histórico: {caminho})")
        return out
    dias = [d for d in (_data_local(l.get("em"), fuso) for l in reprovacoes) if d]
    if dias:
        out.append(f"O histórico começa em {_fmt_data(min(dias))} e tem {_contagem_eventos_e_leads(reprovacoes)} ao todo.")
    out.append("(Um mesmo lead pode ter mais de uma reprovação: por exemplo, devolvido à fila e reprovado de novo.)")
    if ilegiveis:
        out.append(f"Atenção: {ilegiveis} linha(s) do histórico não puderam ser lidas e ficaram de fora.")
    descricao = []
    if filtros.get("desde"):
        descricao.append(f"desde {_fmt_data(filtros['desde'])}")
    if filtros.get("ate"):
        descricao.append(f"até {_fmt_data(filtros['ate'])}")
    if filtros.get("motivo"):
        descricao.append(f"motivo: {rotulo_motivo(filtros['motivo'])}")
    for chave, nome in (("campanha", "campanha"), ("cidade", "cidade"), ("categoria", "categoria")):
        if filtros.get(chave):
            descricao.append(f"{nome} contendo \"{filtros[chave]}\"")
    out.append("Filtro: " + ("; ".join(descricao) if descricao else "nenhum (todas as reprovações)"))
    out.append("")
    if not selecionadas:
        out.append("Nenhuma reprovação encontrada com esse filtro.")
        no_historico = {l.get("motivo") for l in reprovacoes}
        out.append("")
        out.append("Motivos válidos (código para usar em --motivo):")
        for codigo in sorted(set(ROTULOS_MOTIVO) | no_historico, key=str):
            marca = "  [há reprovações no histórico]" if codigo in no_historico else ""
            out.append(f"  {codigo} = {ROTULOS_MOTIVO.get(codigo, 'motivo sem frase')}{marca}")
        return out
    out.append(f"Total encontrado: {_contagem_eventos_e_leads(selecionadas)}.")
    devolvidas = seguidas_de_devolucao(selecionadas, todas)
    if devolvidas:
        out.append(f"Destas, {len(devolvidas)} reprovação(ões) foram seguidas de devolução à fila, pela reavaliação.")
    blocos = (
        ("Por motivo", "motivo", rotulo_motivo),
        ("Por campanha", "campanha_id", None),
        ("Por cidade (a da busca)", "campanha_cidade", None),
        ("Por categoria do Google", "categoria", None),
    )
    for titulo, chave, rotulo in blocos:
        out.append("")
        out.append(f"{titulo}:")
        for nome, n in _contar(selecionadas, chave, rotulo):
            out.append(f"  {n:>4}  {nome}")
    if lista:
        out.append("")
        out.append("Lista (data · nome · categoria · cidade · motivo · lista de origem):")
        for l in sorted(selecionadas, key=lambda x: x.get("em") or ""):
            dia = _data_local(l.get("em"), fuso)
            out.append(f"  {_fmt_data(dia) if dia else '?'} · {l.get('nome') or '?'} · {l.get('categoria') or '?'} · "
                       f"{l.get('campanha_cidade') or '?'} · {rotulo_motivo(l.get('motivo'))} · "
                       f"{l.get('origem_csv') or '?'}")
    return out


def parse_data(texto):
    """AAAA-MM-DD -> date. Levanta ValueError com mensagem clara."""
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        raise ValueError(f"Data \"{texto}\" não entendida. Use o formato ano-mês-dia, por exemplo 2026-10-01.")


# --- backup do pool ------------------------------------------------------------------------


def dir_backups_padrao() -> Path:
    """A pasta REAL de backups: <pasta acima do LeadFarm>/_backups/leadfarm (ignora o env)."""
    return Path(contrato.eqc_root()).resolve().parent.parent / "_backups" / "leadfarm"


def dir_backups() -> Path:
    """`QUALIFICADOR_BACKUP_DIR` (teste) vence; senão `dir_backups_padrao()`."""
    env = (os.environ.get(ENV_BACKUP_DIR) or "").strip()
    if env:
        return Path(env)
    return dir_backups_padrao()


def sha256(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


class BackupFalhouError(Exception):
    pass


SUFIXO_INCOMPLETO = "-INCOMPLETO"


def _copiar_conferindo(origem, destino, rotulo):
    """Uma cópia + conferência por sha256. Devolve o hash; levanta OSError ou ValueError."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origem, destino)
    h_origem, h_copia = sha256(origem), sha256(destino)
    if h_origem != h_copia:
        raise ValueError(f"a cópia de {rotulo} não bate com o original (hash diferente)")
    return h_origem


def backup_conferido(caminhos, prefixo, carimbo_hora, pastas=()):
    """Copia cada arquivo EXISTENTE de `caminhos` e cada arquivo de cada pasta EXISTENTE de
    `pastas` (com a estrutura de subpastas) para <dir_backups()>/<prefixo>-<carimbo_hora>/ e
    confere cada cópia por sha256.

    Qualquer falha => BackupFalhouError e quem chamou não altera nada. A pasta do backup que
    ficou pela metade NUNCA é apagada: é renomeada para "...-INCOMPLETO" (a mensagem diz isso).
    Devolve (pasta, [(nome, sha256)], [nomes ausentes])."""
    pasta = dir_backups() / f"{prefixo}-{carimbo_hora}"
    if pasta.exists():
        raise BackupFalhouError(f"A pasta de backup já existe: {pasta}. Nada foi alterado.")
    try:
        pasta.mkdir(parents=True)
    except OSError as e:
        raise BackupFalhouError(f"Não consegui criar a pasta de backup {pasta}: {e}. Nada foi alterado.") from e
    copiados, ausentes = [], []
    itens = []
    for origem in caminhos:
        nome = os.path.basename(origem)
        if os.path.exists(origem):
            itens.append((origem, pasta / nome, nome))
        else:
            ausentes.append(nome)
    for raiz in pastas:
        nome_pasta = os.path.basename(os.path.normpath(raiz))
        if not os.path.isdir(raiz):
            ausentes.append(nome_pasta + "/")
            continue
        for arquivo in sorted(Path(raiz).rglob("*")):
            if arquivo.is_file():
                rel = arquivo.relative_to(raiz)
                itens.append((str(arquivo), pasta / nome_pasta / rel, f"{nome_pasta}/{rel.as_posix()}"))
    for origem, destino, rotulo in itens:
        try:
            copiados.append((rotulo, _copiar_conferindo(origem, destino, rotulo)))
        except (OSError, ValueError) as e:
            raise BackupFalhouError(_marcar_incompleto(pasta, f"A cópia de {rotulo} falhou: {e}.")) from e
    return pasta, copiados, ausentes


def _marcar_incompleto(pasta, motivo):
    """Renomeia o backup pela metade para ...-INCOMPLETO (nunca apaga) e monta a mensagem."""
    incompleta = pasta.with_name(pasta.name + SUFIXO_INCOMPLETO)
    try:
        pasta.rename(incompleta)
        onde = f"O backup ficou incompleto e foi guardado como {incompleta} (nada foi apagado)."
    except OSError as e:
        onde = (f"O backup ficou incompleto em {pasta}; não consegui renomeá-lo para ...{SUFIXO_INCOMPLETO} "
                f"({e}). Nada foi apagado.")
    return f"{motivo} {onde} Nada foi alterado no pool."
