# COMERCIAL — first outreach message

The COMERCIAL module takes the leads already qualified by the QUALIFICADOR and turns
them into an **outreach sheet**: for each lead, the most relevant angle, a ready-to-send
first message and the channel to send it through. Messages are sent by hand, a few per
day — never in bulk. Afterwards, one command logs who was contacted, so future sheets
leave them out.

The first message **does not use an LLM**: the angle is chosen by explicit rules and the
text comes from fixed templates that can be edited without touching the code.

## Flow

```
JSON hand-off + human CSV from the QUALIFICADOR
  → contrato_loader     (validates against the JSON Schema, pins the contract version)
  → angulo_mensagem     (picks the angle by rule, fills the template)
  → validador_mensagem  (rejects anything that asserts what was not measured)
  → planilha_envio      (.xlsx with three tabs: Geral, Nata, Como usar)
  → registro_abordagens (after sending: who was contacted or skipped)
```

## How the angle is chosen

- **Leads with their own website:** the first angle the lead fits, in this order — a
  template e-mail address left on the site, a phone number that cannot be tapped on a
  phone, or a slow site on mobile (Google's speed test, at least 10 seconds, measured
  twice). No angle, no message. Other angles (few reviews, moderately slow, slow measured
  only once) exist in the templates but are switched off in `config/angulo_regras.json`.
- **Leads without their own website** (none, a directory portal, a social network, a
  free site builder): one template per situation; the "no website" text depends on the
  niche of the lead's campaign (psychologists, lawyers, architects).

Every message follows *greeting and who is writing → measured fact → plausible
consequence → small question*. A deterministic validator blocks, among other things, any
number that did not come from a measurement, prices, links and any domain or address (even
without "http"/"www" — a platform that is not on the known list is named generically, e.g.
"una plataforma externa"; the only exception is the template e-mail that the "template e-mail"
message quotes as evidence), the business name, and
sentences that state an unmeasured outcome ("you are losing patients") rather than a
hedged one ("this can add friction").

## Running it

```bash
# build the outreach sheet from the latest QUALIFICADOR batch
python ferramentas/planilha_envio.py --saida-dir "<output folder>"

# after sending: log who was contacted -- run it again whenever a "Resultado" changes
python ferramentas/registro_abordagens.py "<filled-in sheet>"

# check whether any sent message or result change is still missing from the log (read-only)
python ferramentas/pendencias_registro.py "<filled-in sheet>"

# the funnel of each lead, from the log (read-only)
python ferramentas/registro_abordagens.py --funil
python ferramentas/registro_abordagens.py --funil --place-id "<place_id>"
```

The contact log only ever appends. The first row of a lead is its send (`evento` =
`envio`); each later change of "Resultado" in the sheet (e.g. *pediu exemplo* →
*proposta* → *cliente*) becomes a new row (`evento` = `resultado`) dated with the computer's
**local** date and time of the moment the log was updated (no time-zone suffix), not the
moment the change happened. A lead that is new in two tabs of the same sheet is logged once.
Running it again with the same result adds nothing. `--funil` prints each lead's sequence and how many leads reached each
result; it never writes.

The contract location is resolved automatically; optional variables are listed in
[`.env.example`](.env.example).

## Layout

```
comercial/
├── config/        message templates, angle rules and validator word lists (JSON)
├── ferramentas/   code (Python)
├── prompts/       prompt for an LLM-written variant, not used in the current flow
└── tests/         pytest suite
```

`ferramentas/llm_cliente.py`, `pipeline_estrategia_mensagem.py` and related pieces are an
LLM-written version of the message, **outside the current flow**: testing showed that the
angle matters, not who writes the sentence.

## Tests

```bash
python -m pytest -q
```

Every lead in tests and examples is **fictitious** (e.g. "Fisioficticia Salud", phone
`+34 600 000 000`). Real data — batches, sheets, the contact log — stays off this
repository.
