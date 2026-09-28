"""entrada_estrategia.py — monta a ENTRADA de uma chamada de LLM por lead da
nata (Etapa E2, `RUMO-COMERCIAL-2026-09.md` §5). Só fato medido entra: nada
de HTML, texto do site ou dado não confirmado atravessa esta função. Desenho
aprovado pelo diretor em 23/09/2026 — não reaberto aqui.

Campos, e quando cada um entra:
- **`nome` NUNCA entra na entrada** (decisão do diretor, 24/09/2026, quarta
  rodada): o nome do negócio sai da entrada do modelo — o prompt v5 proíbe
  citá-lo, e `validador_mensagem.validar_mensagem` rejeita `mensagem_1` que
  contenha o nome original do lead ou o corte de
  `nome_comercial.nome_comercial_limpo` (essa função continua existindo só
  para essa checagem, chamada pelo validador — nunca mais para compor a
  entrada). `ResultadoLead.nome` (uso interno/planilha) vem direto de
  `lead["identidade"]["nome"]`, não da entrada.
- `nicho` / `cidade`: só quando não são `None`. Os dois vêm `[string, null]`
  no contrato — um valor ausente não é fato, é lacuna (`cidade` em especial:
  pendência DP-12, hoje costuma vir vazia na base real). Aprovado pela
  supervisão em 24/09/2026 que `nicho` segue a mesma regra.
- `problemas_vendaveis`: `tipo` + `medicao` de cada item de
  `lead['problema_vendavel']`, mais o que segue — nunca `coletado_em`, que
  não é insumo de copy.
- **`lento_no_celular` é tratado à parte** (defeito real, achado em
  produção 24/09/2026 contra o lote de 23/09: 37 de 38 leads da nata são
  desse tipo). A `evidencia` crua desse tipo é texto de máquina —
  `"psi.lcp_ms=8076 > 4000"` — e nunca entra na entrada: ela carrega o
  corte técnico (4000) e o valor em milissegundos, nenhum dos dois é o que
  a mensagem deve citar. Em vez disso, o item carrega só `tipo`, `medicao`
  e o campo **derivado por programa** `segundos_carga_celular` (inteiro,
  `round(lcp_ms / 1000)`), a única coisa que o prompt orienta o modelo a
  citar. `lcp_ms` vem preferencialmente de `lead['psi']['lcp_ms']` (a
  medição, quando `psi_estado(lead) == CONFIRMADO_PRESENTE`); se a medição
  não estiver disponível ali, tenta parsear da própria string de evidência
  (`_LCP_MS_NA_EVIDENCIA`). Se nenhuma das duas fontes render um número, o
  item some sem `segundos_carga_celular` e sem `evidencia` — nunca com o
  texto técnico cru como alternativa.
- Demais tipos (`sem_contato_visivel`, `fora_do_ar`): `evidencia` continua
  como estava, sem tratamento especial — o defeito encontrado foi só em
  `lento_no_celular`.
- `nota_google` / `avaliacoes_google`: **os dois entram juntos, ou nenhum**
  (decisão do diretor, 24/09/2026 — "elogio" liberado na mensagem_1). Só
  entram quando `CampoEvidencia.presente()` nos dois **e** os valores batem
  o limiar de `config/entrada_estrategia.json` (`nota_google_minima`,
  `avaliacoes_minimas` — hoje 4,5 e 15, nunca fixo em código). Abaixo do
  limiar, ou não confirmado, os dois somem — o modelo vai direto ao
  problema, sem elogio. `entrada_estrategia.tem_elogio_reputacao(lead)` é a
  MESMA função usada pelo pipeline para decidir o campo `com_elogio` do
  resultado — nunca duas implementações do mesmo corte.
- `tem_whatsapp`: sempre — `contato.whatsapp_apto` é bool simples (não
  `CampoEvidencia`), recalculado pelo QUALIFICADOR, nunca `null`.
- `texto_site` (contrato 2.1.0, opcional): só entra quando
  `lead["texto_site"]["estado"] == "CONFIRMADO_PRESENTE"` — mesmo
  vocabulário de `psi`, não é `CampoEvidencia`. Ausente na entrada quando o
  lote não tem o campo (lote anterior a 2.1.0), quando é `null`, ou quando
  `NAO_VERIFICADO`. É o texto que o prompt usa para escolher o ângulo — a
  mensagem não expõe a pesquisa, só pode citar `trecho_site` LITERALMENTE
  presente aqui (checado por `validador_mensagem.py`).
- `apresentacao` (prompt v3, 24/09/2026): só entra quando
  `config/remetente_apresentacao.json` não está vazio — mesmo arquivo que
  `templates_direta.py` usa para a pista Direta, o diretor edita à mão, o
  código só lê. Não é fato do lead — é o mesmo texto para todo lead da
  rodada.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Optional

try:
    import templates_direta
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import templates_direta

TIPO_LENTO_NO_CELULAR = "lento_no_celular"
ESTADO_PSI_CONFIRMADO_PRESENTE = "CONFIRMADO_PRESENTE"

_LCP_MS_NA_EVIDENCIA = re.compile(r"lcp_ms\s*=\s*(\d+)")

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CAMINHO_CONFIG_PADRAO = _CONFIG_DIR / "entrada_estrategia.json"

_CHAVES_CONFIG_OBRIGATORIAS = ("nota_google_minima", "avaliacoes_minimas")


class ConfigEntradaInvalidaError(Exception):
    """`config/entrada_estrategia.json` ausente, ilegível ou incompleto."""


def carregar_limiares_reputacao(caminho: Path = CAMINHO_CONFIG_PADRAO) -> dict:
    """Lê e valida `config/entrada_estrategia.json`. Levanta
    `ConfigEntradaInvalidaError` com o caminho tentado se o arquivo não
    existir, não for JSON válido, ou faltar alguma das chaves exigidas."""
    caminho = Path(caminho)
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as e:
        raise ConfigEntradaInvalidaError(
            f"Config de limiares de reputação não encontrada em {caminho}: {e}"
        ) from e
    try:
        config = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ConfigEntradaInvalidaError(
            f"Config de limiares de reputação em {caminho} não é JSON válido: {e}"
        ) from e

    faltando = [c for c in _CHAVES_CONFIG_OBRIGATORIAS if c not in config]
    if faltando:
        raise ConfigEntradaInvalidaError(
            f"Config de limiares de reputação em {caminho} sem as chaves: {faltando}"
        )
    return config


def tem_elogio_reputacao(lead, limiares: Optional[dict] = None) -> bool:
    """`True` só quando nota e número de avaliações estão CONFIRMADOS e os
    dois batem o limiar (`limiares` omitido carrega
    `config/entrada_estrategia.json`). É a função única que decide o corte
    do elogio — usada tanto para incluir `nota_google`/`avaliacoes_google`
    na entrada quanto para o campo `com_elogio` do resultado do pipeline."""
    if limiares is None:
        limiares = carregar_limiares_reputacao()

    nota = lead["reputacao"]["nota_google"]
    avaliacoes = lead["reputacao"]["review_count"]
    if not nota.presente() or not avaliacoes.presente():
        return False

    return (
        nota.valor_confirmado >= limiares["nota_google_minima"]
        and avaliacoes.valor_confirmado >= limiares["avaliacoes_minimas"]
    )


def _lcp_ms_medido(lead) -> Optional[int]:
    """`lead['psi']['lcp_ms']`, só quando a medição está confirmada. `psi`
    nunca é `CampoEvidencia` (decisão D12 do contrato) — fica dict cru ou
    `None`, então checamos a forma à mão em vez de importar `psi_estado`
    (evitar acoplar este módulo à API inteira do `contrato_loader`)."""
    psi = lead["psi"]
    if isinstance(psi, Mapping) and psi.get("estado") == ESTADO_PSI_CONFIRMADO_PRESENTE:
        lcp_ms = psi.get("lcp_ms")
        if isinstance(lcp_ms, (int, float)):
            return int(lcp_ms)
    return None


def _lcp_ms_da_string(evidencia: str) -> Optional[int]:
    achado = _LCP_MS_NA_EVIDENCIA.search(evidencia or "")
    return int(achado.group(1)) if achado else None


def _item_problema(lead, item: Mapping) -> dict:
    if item["tipo"] != TIPO_LENTO_NO_CELULAR:
        return {
            "tipo": item["tipo"],
            "evidencia": item["evidencia"],
            "medicao": item["medicao"],
        }

    # lento_no_celular: nunca a string crua (carrega o corte 4000 e os ms,
    # nenhum dos dois é o que a mensagem deve citar) -- só o derivado.
    saida = {"tipo": item["tipo"], "medicao": item["medicao"]}
    lcp_ms = _lcp_ms_medido(lead)
    if lcp_ms is None:
        lcp_ms = _lcp_ms_da_string(item["evidencia"])
    if lcp_ms is not None:
        saida["segundos_carga_celular"] = round(lcp_ms / 1000)
    return saida


def texto_do_site(lead) -> Optional[str]:
    """Texto do campo `texto_site` (contrato 2.1.0), só quando
    `CONFIRMADO_PRESENTE` -- exatamente o texto que `construir_entrada`
    manda para o modelo (ou `None` se o modelo não recebeu nenhum). Pública
    porque `planilha_envio.py` precisa do MESMO texto para a coluna
    "Contexto para IA" — nunca uma segunda derivação divergente.
    `"texto_site" not in lead` cobre lote anterior a 2.1.0 (chave nem
    existe) sem levantar `KeyError` -- `Mapping.__contains__` tenta
    `lead["texto_site"]` por baixo, então continua passando pelas proteções
    normais de `LeadQualificado`."""
    if "texto_site" not in lead:
        return None
    campo = lead["texto_site"]
    if isinstance(campo, Mapping) and campo.get("estado") == ESTADO_PSI_CONFIRMADO_PRESENTE:
        return campo.get("texto") or None
    return None


def construir_entrada(
    lead, *, limiares_reputacao: Optional[dict] = None, apresentacao: Optional[str] = None
) -> dict:
    """Devolve o dict JSON-serializável enviado como entrada da chamada.
    `lead` é um `contrato_loader.LeadQualificado` (ou qualquer objeto com a
    mesma interface de acesso por chave). `limiares_reputacao` omitido
    carrega `config/entrada_estrategia.json` uma vez (via
    `carregar_limiares_reputacao`). `apresentacao` omitido carrega
    `config/remetente_apresentacao.json` (mesmo arquivo da pista Direta)."""
    if limiares_reputacao is None:
        limiares_reputacao = carregar_limiares_reputacao()
    if apresentacao is None:
        apresentacao = templates_direta.carregar_apresentacao()

    identidade = lead["identidade"]
    entrada: dict = {}

    if apresentacao:
        entrada["apresentacao"] = apresentacao

    if identidade["nicho"] is not None:
        entrada["nicho"] = identidade["nicho"]
    if identidade["cidade"] is not None:
        entrada["cidade"] = identidade["cidade"]

    entrada["problemas_vendaveis"] = [
        _item_problema(lead, item) for item in lead["problema_vendavel"]
    ]

    if tem_elogio_reputacao(lead, limiares_reputacao):
        entrada["nota_google"] = lead["reputacao"]["nota_google"].valor_confirmado
        entrada["avaliacoes_google"] = lead["reputacao"]["review_count"].valor_confirmado

    entrada["tem_whatsapp"] = lead["contato"]["whatsapp_apto"]

    texto_site = texto_do_site(lead)
    if texto_site:
        entrada["texto_site"] = texto_site

    return entrada
