"""templates_direta.py — monta a "Mensagem sugerida" da pista Direta a partir
de `config/templates_direta.json` (Etapa E2b, planilha de envio). Nenhum
texto fica embutido no código — o diretor edita o JSON.

- Template escolhido pela `classe_site` do lead (`sem_site`,
  `superficie_google`, `portal`, `rede_social`, `construtor`). Sem template
  para a classe (ex.: `proprio` — esse lead tem mensagem própria da Etapa
  E2, não vem daqui): `montar_mensagem_direta` devolve `None`.
- **Sem `{nome}`** (decisão do diretor, 24/09/2026, quarta rodada): o nome
  do negócio nunca aparece na mensagem — "Vi {nome} en Google Maps" virou
  "Vi su perfil en Google Maps" em `config/templates_direta.json`.
  `validar_mensagem_direta` ainda recebe `lead.get("nome")` como
  `nome_negocio` — rede de segurança contra o nome vazar por outro campo do
  template (`{portal}`/`{rede}`/`{dominio}`, por exemplo).
- `{apresentacao}` vem de `config/remetente_apresentacao.json` — o diretor
  edita à mão; este módulo só lê.
- `{elogio}` só entra quando nota e avaliações batem
  `config/entrada_estrategia.json` (`nota_google_minima`,
  `avaliacoes_minimas`) — o MESMO limiar da Etapa E2
  (`entrada_estrategia.tem_elogio_reputacao`), nunca um segundo número.
  Nota formatada com vírgula decimal (`4,5`), nunca ponto.
- `{portal}`/`{rede}`/`{dominio}` derivados do domínio do site: mapeados por
  `nomes_dominio` quando conhecido (ex.: `doctoralia.es` -> `Doctoralia`);
  senão, rótulo derivado do próprio domínio (`construtor` sempre usa o
  domínio cru, nunca um nome bonito — é o próprio "problema" citado).

Toda mensagem renderizada passa por `validador_mensagem.validar_mensagem`
(a MESMA validação da Etapa E2 — saudação, preço, informalidade, termina em
"?", número fora da entrada) antes de entrar na planilha.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

try:
    import validador_mensagem
except ModuleNotFoundError:  # pragma: no cover - bootstrap de sys.path
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import validador_mensagem

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CAMINHO_TEMPLATES_PADRAO = _CONFIG_DIR / "templates_direta.json"
CAMINHO_APRESENTACAO_PADRAO = _CONFIG_DIR / "remetente_apresentacao.json"

_CHAVES_TEMPLATES_OBRIGATORIAS = ("templates", "elogio_template")


class ConfigTemplatesInvalidaError(Exception):
    """`config/templates_direta.json` ausente, ilegível ou incompleto."""


class ConfigApresentacaoInvalidaError(Exception):
    """`config/remetente_apresentacao.json` ausente, ilegível ou incompleto."""


def carregar_templates_direta(caminho: Path = CAMINHO_TEMPLATES_PADRAO) -> dict:
    caminho = Path(caminho)
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as e:
        raise ConfigTemplatesInvalidaError(f"Config de templates não encontrada em {caminho}: {e}") from e
    try:
        config = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ConfigTemplatesInvalidaError(f"Config de templates em {caminho} não é JSON válido: {e}") from e

    faltando = [c for c in _CHAVES_TEMPLATES_OBRIGATORIAS if c not in config]
    if faltando:
        raise ConfigTemplatesInvalidaError(f"Config de templates em {caminho} sem as chaves: {faltando}")
    return config


def carregar_apresentacao(caminho: Path = CAMINHO_APRESENTACAO_PADRAO) -> str:
    """Devolve a string `apresentacao` (pode ser vazia — é o padrão). O
    diretor edita este arquivo à mão; nunca escrito por código."""
    caminho = Path(caminho)
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as e:
        raise ConfigApresentacaoInvalidaError(
            f"Config de apresentação não encontrada em {caminho}: {e}"
        ) from e
    try:
        config = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ConfigApresentacaoInvalidaError(
            f"Config de apresentação em {caminho} não é JSON válido: {e}"
        ) from e
    if "apresentacao" not in config:
        raise ConfigApresentacaoInvalidaError(
            f"Config de apresentação em {caminho} sem a chave 'apresentacao'."
        )
    return config["apresentacao"]


def _hostname(site_url) -> Optional[str]:
    if not site_url:
        return None
    bruto = site_url if "://" in site_url else f"//{site_url}"
    host = urlsplit(bruto).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _nome_dominio(hostname: Optional[str], mapa_nomes: dict) -> str:
    if not hostname:
        return ""
    if hostname in mapa_nomes:
        return mapa_nomes[hostname]
    rotulo = hostname.split(".")[0]
    return rotulo.capitalize()


def _numero(valor):
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _formatar_nota(nota: float) -> str:
    return f"{nota:.1f}".replace(".", ",")


def _elogio(lead: dict, config_templates: dict, limiares_reputacao: dict) -> str:
    nota = _numero(lead.get("nota"))
    avaliacoes = _numero(lead.get("avaliacoes"))
    if nota is None or avaliacoes is None:
        return ""
    if nota >= limiares_reputacao["nota_google_minima"] and avaliacoes >= limiares_reputacao["avaliacoes_minimas"]:
        return config_templates["elogio_template"].format(
            nota=_formatar_nota(nota), avaliacoes=int(avaliacoes)
        )
    return ""


def montar_mensagem_direta(
    lead: dict,
    *,
    config_templates: dict,
    apresentacao: str,
    limiares_reputacao: dict,
) -> Optional[str]:
    """`lead` é um dict de colunas do CSV humano (`nome`, `classe_site`,
    `site`, `nota`, `avaliacoes`, ...). Devolve `None` quando não há
    template para a `classe_site` do lead (ex.: `proprio`)."""
    template = config_templates["templates"].get(lead.get("classe_site"))
    if not template:
        return None

    hostname = _hostname(lead.get("site"))
    mapa_nomes = config_templates.get("nomes_dominio", {})
    contexto = {
        "apresentacao": apresentacao,
        "elogio": _elogio(lead, config_templates, limiares_reputacao),
        "portal": _nome_dominio(hostname, mapa_nomes),
        "rede": _nome_dominio(hostname, mapa_nomes),
        "dominio": hostname or "",
    }
    return template.format(**contexto)


def validar_mensagem_direta(mensagem: str, lead: dict, *, config_validacao: Optional[dict] = None):
    """Roda `mensagem` pelo MESMO validador determinístico da Etapa E2
    (`validador_mensagem.validar_mensagem`) — saudação, preço, informalidade,
    termina em "?", número fora da entrada. A "entrada" aqui é só o que o
    template pode ter citado: nota/avaliações do lead (quando o elogio foi
    liberado) — nunca o CSV inteiro, que teria números não citáveis
    (telefone, place_id) misturados no cruzamento de número."""
    nota = _numero(lead.get("nota"))
    avaliacoes = _numero(lead.get("avaliacoes"))
    entrada = {}
    if nota is not None:
        entrada["nota_google"] = _formatar_nota(nota)
    if avaliacoes is not None:
        entrada["avaliacoes_google"] = int(avaliacoes)

    texto_resposta = json.dumps(
        {
            "estrategia": "direta",
            "canal_sugerido": "whatsapp",
            "mensagem_1": mensagem,
            "fato_usado": "template_direta",
        }
    )
    return validador_mensagem.validar_mensagem(
        texto_resposta, entrada, config=config_validacao, nome_negocio=lead.get("nome")
    )
