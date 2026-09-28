"""Carregador mínimo de .env -- só stdlib, sem dependência nova (nada de python-dotenv).

Motivo: o resto do código lê `os.environ` direto (psi_client, contrato). Sem isto, pôr a
chave num arquivo .env não teria efeito nenhum -- as variáveis precisariam ser exportadas à
mão no shell/CI. Este loader fecha esse buraco sem trazer dependência.

Regras:
- Lê `prospeccao_ia/.env` (ao lado deste arquivo) se existir.
- Variáveis de ambiente REAIS têm precedência: nunca sobrescreve o que já está em os.environ.
- Ausência do .env não é erro -- segue silencioso.
- Formato: `CHAVE=VALOR` por linha. Linhas vazias e as que começam com `#` são ignoradas.
  Aspas simples ou duplas em volta do valor são removidas. Sem interpolação, sem `export`.
"""
import os

_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")


def _parse(texto):
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave = chave.strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ("'", '"'):
            valor = valor[1:-1]
        if chave:
            yield chave, valor


def carregar_env(path=_ENV_PATH):
    """Aplica o .env a os.environ sem sobrescrever variáveis já definidas. Idempotente.
    Devolve a lista de chaves que passou a definir (vazia se não havia .env ou nada novo)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            texto = f.read()
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        return []

    definidas = []
    for chave, valor in _parse(texto):
        if chave not in os.environ:
            os.environ[chave] = valor
            definidas.append(chave)
    return definidas
