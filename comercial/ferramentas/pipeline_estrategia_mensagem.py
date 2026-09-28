"""pipeline_estrategia_mensagem.py — Etapa E2 (`RUMO-COMERCIAL-2026-09.md`
§5): uma chamada de LLM por lead da `nata`, que devolve estratégia + primeira
mensagem, validada por programa. Usa a infraestrutura da Etapa E1
(`llm_cliente`, `llm_config`, `custo_llm`, `registro_consumo`) — nenhum
prompt comercial vive lá, só aqui e em `prompts/estrategia_mensagem_sistema.md`.

Fluxo por lead (`processar_lead`):
1. `entrada_estrategia.construir_entrada(lead)` — só fato medido.
2. Chama o modelo com o prompt de sistema versionado + a entrada como JSON.
3. `validador_mensagem.validar_mensagem` — falhou, UMA nova tentativa,
   passando o motivo da falha de volta ao modelo. Falhou de novo: o lead sai
   como `status="rejeitado_validador"` com o motivo. Nunca aceita em
   silêncio.

Toda chamada (das duas tentativas, sempre) registra consumo via
`registro_consumo.registrar_chamada` — sucesso ou rejeição.

Saída de uma rodada (`escrever_saida_rodada`): uma pasta nova por rodada,
nunca sobrescrita, com `resultados.json`, `resultados.csv` (UTF-8 com BOM,
para abrir no Excel) e `consumo.jsonl`. Pasta padrão: `comercial/_mensagens/`
— dado operacional, fora do Git (`.gitignore`).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import llm_config
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import llm_config

import entrada_estrategia
import templates_direta
from custo_llm import calcular_custo_usd
from entrada_estrategia import construir_entrada
from llm_cliente import chamar_llm
from registro_consumo import registrar_chamada
from validador_mensagem import carregar_config as carregar_config_validacao
from validador_mensagem import validar_mensagem

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
CAMINHO_PROMPT_PADRAO = _PROMPTS_DIR / "estrategia_mensagem_sistema.md"

_DADOS_DIR = Path(__file__).resolve().parent.parent / "_mensagens"
DIRETORIO_SAIDA_PADRAO = _DADOS_DIR

MAX_TENTATIVAS = 2
TIPO_FORA_DO_AR = "fora_do_ar"


class PastaDaRodadaJaExisteError(Exception):
    """A pasta de saída de uma rodada já existe — nunca sobrescrever uma
    rodada anterior. Rodadas são identificadas pelo timestamp; rode de novo
    um segundo depois, ou passe um `agora` diferente."""


@dataclass
class ResultadoLead:
    place_id: Optional[str]
    nome: str
    status: str  # "ok" | "rejeitado_validador"
    tentativas: int
    com_elogio: str = "não"  # "sim"/"não" -- decidido pelo programa, nunca pelo modelo (regra do diretor, 24/09/2026)
    conferir_antes_de_enviar: str = "não"  # "sim" para todo lead com problema fora_do_ar
    custo_total_usd: float = 0.0
    modelo: Optional[str] = None  # modelo efetivamente usado na última chamada (resposta.modelo)
    estrategia: Optional[str] = None
    canal_sugerido: Optional[str] = None
    mensagem_1: Optional[str] = None
    fato_usado: Optional[str] = None
    trecho_site: Optional[str] = None  # v3 do prompt (24/09/2026) -- citação literal de texto_site, quando houver
    motivo_rejeicao: Optional[str] = None


def carregar_prompt_sistema(caminho: Path = CAMINHO_PROMPT_PADRAO) -> str:
    caminho = Path(caminho)
    try:
        return caminho.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as e:
        raise FileNotFoundError(
            f"Prompt de sistema não encontrado em {caminho}. "
            f"Ver comercial/prompts/estrategia_mensagem_sistema.md."
        ) from e


def _mensagem_de_correcao(motivos: list) -> str:
    return (
        "La respuesta anterior no cumplió estas reglas: "
        + "; ".join(motivos)
        + ". Corrige exactamente eso y devuelve de nuevo SOLO el JSON con "
        "los 4 campos, sin explicación ni cercas de código."
    )


def _tem_problema_fora_do_ar(lead) -> bool:
    return any(item["tipo"] == TIPO_FORA_DO_AR for item in lead["problema_vendavel"])


def _sim_ou_nao(valor: bool) -> str:
    return "sim" if valor else "não"


def processar_lead(
    lead,
    *,
    lead_id: str,
    prompt_sistema: str,
    cliente: Any = None,
    modelo: Optional[str] = None,
    tabela_precos: Optional[dict] = None,
    config_validacao: Optional[dict] = None,
    limiares_reputacao: Optional[dict] = None,
    apresentacao: Optional[str] = None,
    caminho_log_consumo: Optional[Path] = None,
) -> ResultadoLead:
    """Processa um lead: até `MAX_TENTATIVAS` chamadas, cada uma registrada
    em consumo, validando a saída de cada tentativa. `lead_id` identifica o
    lead no log de consumo (recomendado: `place_id`, ou um id sintético
    quando ausente — ver `_id_do_lead`).

    `com_elogio` e `conferir_antes_de_enviar` são decididos pelo PROGRAMA,
    nunca pelo modelo (decisão do diretor, 24/09/2026) — calculados antes de
    qualquer chamada e presentes no resultado independente do desfecho
    (`ok` ou `rejeitado_validador`)."""
    tabela_precos = tabela_precos or llm_config.carregar_tabela_precos()
    config_validacao = config_validacao or carregar_config_validacao()
    limiares_reputacao = limiares_reputacao or entrada_estrategia.carregar_limiares_reputacao()
    if apresentacao is None:
        apresentacao = templates_direta.carregar_apresentacao()

    entrada = construir_entrada(lead, limiares_reputacao=limiares_reputacao, apresentacao=apresentacao)
    com_elogio = _sim_ou_nao(entrada_estrategia.tem_elogio_reputacao(lead, limiares_reputacao))
    conferir_antes_de_enviar = _sim_ou_nao(_tem_problema_fora_do_ar(lead))
    nome_negocio = lead["identidade"]["nome"]

    entrada_json = json.dumps(entrada, ensure_ascii=False)
    mensagens = [{"role": "user", "content": entrada_json}]

    custo_total = 0.0
    resultado_validacao = None
    tentativa = 0

    while tentativa < MAX_TENTATIVAS:
        tentativa += 1
        resposta = chamar_llm(
            mensagens, system=prompt_sistema, modelo=modelo, cliente=cliente
        )
        custo = calcular_custo_usd(resposta.uso, resposta.modelo, tabela_precos)
        custo_total += custo
        if caminho_log_consumo is not None:
            registrar_chamada(
                caminho_log_consumo,
                lead_id=lead_id,
                modelo=resposta.modelo,
                uso=resposta.uso,
                custo_usd=custo,
            )

        resultado_validacao = validar_mensagem(
            resposta.texto, entrada, config=config_validacao, nome_negocio=nome_negocio
        )
        if resultado_validacao.valido:
            dados = resultado_validacao.dados
            return ResultadoLead(
                place_id=lead["place_id"],
                nome=nome_negocio,
                status="ok",
                tentativas=tentativa,
                com_elogio=com_elogio,
                conferir_antes_de_enviar=conferir_antes_de_enviar,
                custo_total_usd=custo_total,
                modelo=resposta.modelo,
                estrategia=dados["estrategia"],
                canal_sugerido=dados["canal_sugerido"],
                mensagem_1=dados["mensagem_1"],
                fato_usado=dados["fato_usado"],
                trecho_site=dados.get("trecho_site"),
            )

        mensagens = mensagens + [
            {"role": "assistant", "content": resposta.texto},
            {"role": "user", "content": _mensagem_de_correcao(resultado_validacao.motivos)},
        ]

    return ResultadoLead(
        place_id=lead["place_id"],
        nome=nome_negocio,
        status="rejeitado_validador",
        tentativas=tentativa,
        com_elogio=com_elogio,
        conferir_antes_de_enviar=conferir_antes_de_enviar,
        custo_total_usd=custo_total,
        modelo=resposta.modelo,
        motivo_rejeicao="; ".join(resultado_validacao.motivos),
    )


def _id_do_lead(lead, indice: int) -> str:
    place_id = lead["place_id"]
    return place_id if place_id else f"sem-place-id-{indice}"


def processar_lote(
    leads: list,
    *,
    prompt_sistema: str,
    limite: Optional[int] = None,
    cliente: Any = None,
    modelo: Optional[str] = None,
    tabela_precos: Optional[dict] = None,
    config_validacao: Optional[dict] = None,
    limiares_reputacao: Optional[dict] = None,
    apresentacao: Optional[str] = None,
    caminho_log_consumo: Optional[Path] = None,
) -> list:
    """Processa `leads` (tipicamente `lote.nata`), até `limite` (todos, se
    omitido). Mesma tabela de preços, config de validação, limiares de
    reputação e apresentação carregados uma vez, reaproveitados em todo o
    lote."""
    tabela_precos = tabela_precos or llm_config.carregar_tabela_precos()
    config_validacao = config_validacao or carregar_config_validacao()
    limiares_reputacao = limiares_reputacao or entrada_estrategia.carregar_limiares_reputacao()
    if apresentacao is None:
        apresentacao = templates_direta.carregar_apresentacao()

    selecionados = leads if limite is None else leads[:limite]
    return [
        processar_lead(
            lead,
            lead_id=_id_do_lead(lead, i),
            prompt_sistema=prompt_sistema,
            cliente=cliente,
            modelo=modelo,
            tabela_precos=tabela_precos,
            config_validacao=config_validacao,
            limiares_reputacao=limiares_reputacao,
            apresentacao=apresentacao,
            caminho_log_consumo=caminho_log_consumo,
        )
        for i, lead in enumerate(selecionados)
    ]


def _pasta_rodada(saida_dir: Path, agora: datetime) -> Path:
    return Path(saida_dir) / f"rodada_{agora.strftime('%Y%m%d-%H%M%S')}"


def criar_pasta_rodada(
    saida_dir: Path = DIRETORIO_SAIDA_PADRAO,
    agora: Optional[datetime] = None,
) -> Path:
    """Cria a pasta `rodada_<timestamp>` dentro de `saida_dir` — UMA vez, no
    início da rodada, antes de qualquer chamada de LLM. É aqui, e só aqui,
    que mora a checagem de nunca sobrescrever uma rodada anterior
    (`PastaDaRodadaJaExisteError`). Consumo (`registro_consumo`) e
    `escrever_saida_rodada` gravam DENTRO da pasta já criada por esta
    função — nenhum dos dois cria ou apaga a pasta.

    Defeito corrigido em 24/09/2026 (primeiro teste real): antes, a pasta só
    era criada implicitamente pelo log de consumo (que faz
    `mkdir(parents=True, exist_ok=True)` na primeira chamada) e a checagem de
    "já existe" só rodava DEPOIS, no fim da rodada, em `escrever_saida_rodada`
    — ou seja, toda rodada com pelo menos uma chamada de LLM encontrava a
    própria pasta que ela mesma tinha criado e levantava
    `PastaDaRodadaJaExisteError` na hora de gravar os resultados, perdendo o
    trabalho todo."""
    agora = agora or datetime.now(timezone.utc)
    pasta = _pasta_rodada(saida_dir, agora)
    if pasta.exists():
        raise PastaDaRodadaJaExisteError(
            f"{pasta} já existe — nunca sobrescrever uma rodada anterior."
        )
    pasta.mkdir(parents=True)
    return pasta


def escrever_saida_rodada(resultados: list, *, pasta: Path) -> Path:
    """Grava `resultados.json` + `resultados.csv` (UTF-8 com BOM) dentro de
    `pasta` — já criada por `criar_pasta_rodada`. Não cria a pasta e não
    checa sobrescrita: isso já aconteceu na criação. Devolve `pasta`."""
    pasta = Path(pasta)
    (pasta / "resultados.json").write_text(
        json.dumps([asdict(r) for r in resultados], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    colunas = [
        "place_id",
        "nome",
        "status",
        "tentativas",
        "com_elogio",
        "conferir_antes_de_enviar",
        "canal_sugerido",
        "mensagem_1",
        "fato_usado",
        "trecho_site",
        "modelo",
        "motivo_rejeicao",
        "custo_total_usd",
        "estrategia",
    ]
    with (pasta / "resultados.csv").open("w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.DictWriter(f, fieldnames=colunas)
        escritor.writeheader()
        for r in resultados:
            escritor.writerow(asdict(r))

    return pasta


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Etapa E2 — estratégia + primeira mensagem por lead da nata."
    )
    ap.add_argument("--limite", type=int, default=None, help="Processa só os N primeiros leads da nata.")
    ap.add_argument("--lote", type=Path, default=None, help="Arquivo do lote do QUALIFICADOR (default: mais recente).")
    ap.add_argument("--saida-dir", type=Path, default=DIRETORIO_SAIDA_PADRAO)
    ap.add_argument("--prompt", type=Path, default=CAMINHO_PROMPT_PADRAO)
    ap.add_argument(
        "--modelo", type=str, default=None,
        help="Roda a mesma nata com outro modelo (default: resolver_modelo() -- COMERCIAL_LLM_MODEL ou modelo_default da tabela de preços). Serve ao teste cego entre modelos.",
    )
    ap.add_argument(
        "--place-ids", type=str, default=None,
        help="Lista de place_id separados por vírgula -- processa só esses leads da nata (default: todos).",
    )
    args = ap.parse_args(argv)

    try:
        import contrato_loader
    except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import contrato_loader

    import anthropic

    chave = llm_config.resolver_api_key()
    tabela_precos = llm_config.carregar_tabela_precos()
    modelo = args.modelo or llm_config.resolver_modelo(tabela_precos)
    config_validacao = carregar_config_validacao()
    limiares_reputacao = entrada_estrategia.carregar_limiares_reputacao()
    prompt_sistema = carregar_prompt_sistema(args.prompt)

    lote = contrato_loader.carregar_lote(caminho=args.lote)
    nata = lote.nata
    if args.place_ids:
        selecionados = {p.strip() for p in args.place_ids.split(",") if p.strip()}
        nata = [lead for lead in nata if lead["place_id"] in selecionados]

    cliente = anthropic.Anthropic(api_key=chave)

    pasta = criar_pasta_rodada(args.saida_dir)
    caminho_log_consumo = pasta / "consumo.jsonl"

    resultados = processar_lote(
        nata,
        prompt_sistema=prompt_sistema,
        limite=args.limite,
        cliente=cliente,
        modelo=modelo,
        tabela_precos=tabela_precos,
        config_validacao=config_validacao,
        limiares_reputacao=limiares_reputacao,
        caminho_log_consumo=caminho_log_consumo,
    )

    escrever_saida_rodada(resultados, pasta=pasta)

    ok = sum(1 for r in resultados if r.status == "ok")
    rejeitados = len(resultados) - ok
    print(f"OK: {len(resultados)} lead(s) processado(s) -> {pasta} ({ok} ok, {rejeitados} rejeitado(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
