"""Salvaguarda estática: nenhum módulo deste sistema chama LLM. Julgamento é trabalho do
Sistema 2. Olha só as linhas de import (não o módulo inteiro) pra não disparar em comentários
que mencionam a própria regra."""
import inspect

import agent_coletor
import contrato
import gbp_diagnostic
import lead_qualification
import output_json
import psi_client
import telefone_utils
import wave2_scoring
import website_analyzer

_PROIBIDOS = ("anthropic", "openai", "claude_client", "langchain", "google.generativeai", "cohere")


def test_nenhum_modulo_importa_cliente_de_llm():
    for modulo in (agent_coletor, contrato, gbp_diagnostic, lead_qualification, output_json,
                   psi_client, telefone_utils, wave2_scoring, website_analyzer):
        linhas_import = [l for l in inspect.getsource(modulo).splitlines()
                         if l.strip().startswith(("import ", "from "))]
        for linha in linhas_import:
            for termo in _PROIBIDOS:
                assert termo not in linha.lower(), f"{modulo.__name__}: import proibido -> {linha!r}"
