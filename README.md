# LeadFarm

*[English](#english) · [Español](#español)*

---

## English

LeadFarm is a lead-qualification and first-contact pipeline for small professional
businesses (the current focus is independent healthcare practices in Spain). It turns a
list of businesses exported from Google Maps into a qualified lead file and a
ready-to-review outreach sheet — without ever asserting anything it did not measure.

### How it is organised

The system is split into modules that talk to each other **only through files**, each
boundary described by a versioned contract:

```
CSV (Google Maps export) ──▶ QUALIFICADOR ──(JSON + contract)──▶ COMERCIAL ──▶ outreach sheet (.xlsx)
```

| Module | What it does |
|---|---|
| **`qualificador/`** | Deterministic pre-processing, no LLM: cleans, de-duplicates, filters, classifies each business's web presence (own site, portal, social network, site builder, none) and measures observable signals (mobile speed via PageSpeed, clickable phone, reviews). Emits a versioned JSON hand-off. |
| **`EQC/`** | The shared layer: the formal contract (JSON Schema + human-readable spec) between the two modules. |
| **`comercial/`** | Consumes the hand-off, picks one message angle per lead by explicit rules, builds the first message and writes the outreach sheet and a permanent contact log. |

The CSV extractor that produces the input is a separate tool and **is not included** in
this repository.

### Ideas worth looking at

- **Facts vs. interpretation.** The qualifier only records what it observed
  (`CONFIRMADO_PRESENTE`, `NAO_VERIFICADO`, …) and never turns "not verified" into "absent".
- **Plausible consequence, never a claimed outcome.** Each message is built as
  *fact → plausible consequence → small question*. A deterministic classifier
  (`comercial/ferramentas/afirmacao.py`) blocks sentences that state an unmeasured result
  ("you are losing patients") while allowing hedged ones ("this can add friction").
- **Validators as the source of truth.** Every message passes a rule-based validator
  (length, no prices, formal register, every number must come from the input, …);
  templates that break the structure are rejected at load time.
- **Early, controlled A/B testing.** The opening line is tested in two variants with an
  identical message body, balanced by angle and channel, so only one variable changes.
- **Tests as evidence.** Both modules have extensive `pytest` suites, including negative
  controls that prove each check fails when it should.
- **AI-assisted development under a documented process.** The project was built with AI
  coding assistants working inside explicit roles, decision records and validation gates.
  Those internal operating documents are not published here.

### Running the tests

Tested with Python 3.14.

```bash
pip install -r qualificador/prospeccao_ia/requirements.txt -r comercial/ferramentas/requirements.txt
cd qualificador/prospeccao_ia && python -m pytest -q
cd ../../comercial && python -m pytest -q
```

Some integration tests are skipped automatically when their local data (never versioned)
is not present.

### Data and privacy

No real lead data is stored in this repository. Every name, phone number, address,
domain and Google place ID in tests and examples is **fictitious**. Operational data
(lead lists, sheets, logs, `.env` files) stays on the author's machine and is excluded by
`.gitignore`.

### Licence

All rights reserved. The code is published for portfolio and reading purposes.

---

## Español

LeadFarm es un pipeline de cualificación de leads y primer contacto para pequeños negocios
de profesionales (el foco actual son consultas de salud independientes en España).
Convierte una lista de negocios exportada de Google Maps en un archivo de leads
cualificados y una hoja de contacto lista para revisar, sin afirmar nunca algo que no haya
medido.

### Cómo está organizado

El sistema se divide en módulos que se comunican **solo mediante archivos**, con cada
frontera descrita por un contrato versionado:

```
CSV (exportación de Google Maps) ──▶ QUALIFICADOR ──(JSON + contrato)──▶ COMERCIAL ──▶ hoja de contacto (.xlsx)
```

| Módulo | Qué hace |
|---|---|
| **`qualificador/`** | Preprocesamiento determinista, sin LLM: limpia, elimina duplicados, filtra, clasifica la presencia web de cada negocio (web propia, portal, red social, constructor de webs, ninguna) y mide señales observables (velocidad en móvil con PageSpeed, teléfono pulsable, reseñas). Emite un JSON de traspaso versionado. |
| **`EQC/`** | La capa compartida: el contrato formal (JSON Schema + especificación legible) entre los dos módulos. |
| **`comercial/`** | Consume el traspaso, elige un ángulo de mensaje por lead con reglas explícitas, construye el primer mensaje y genera la hoja de contacto y un registro permanente. |

El extractor que genera el CSV de entrada es una herramienta aparte y **no está incluido**
en este repositorio.

### Ideas destacables

- **Hechos frente a interpretación.** El cualificador solo registra lo que observó
  (`CONFIRMADO_PRESENTE`, `NAO_VERIFICADO`, …) y nunca convierte "no verificado" en "ausente".
- **Consecuencia plausible, nunca un resultado afirmado.** Cada mensaje sigue la
  estructura *hecho → consecuencia plausible → pregunta pequeña*. Un clasificador
  determinista (`comercial/ferramentas/afirmacao.py`) bloquea frases que afirman un
  resultado no medido ("está perdiendo pacientes") y permite las condicionales ("puede
  resultar una fricción").
- **Los validadores mandan.** Cada mensaje pasa por un validador de reglas (longitud, sin
  precios, trato de usted, todo número debe venir de los datos de entrada…); las
  plantillas que rompen la estructura se rechazan al cargarlas.
- **Tests A/B tempranos y controlados.** La frase de apertura se prueba en dos variantes
  con el mismo cuerpo de mensaje, equilibradas por ángulo y canal, para que solo cambie
  una variable.
- **Los tests como evidencia.** Ambos módulos tienen suites amplias de `pytest`, con
  controles negativos que demuestran que cada comprobación falla cuando debe.
- **Desarrollo asistido por IA con un proceso documentado.** El proyecto se construyó con
  asistentes de programación con IA trabajando dentro de roles, registros de decisiones y
  puntos de validación explícitos. Esos documentos internos no se publican aquí.

### Ejecutar los tests

Probado con Python 3.14.

```bash
pip install -r qualificador/prospeccao_ia/requirements.txt -r comercial/ferramentas/requirements.txt
cd qualificador/prospeccao_ia && python -m pytest -q
cd ../../comercial && python -m pytest -q
```

Algunos tests de integración se omiten automáticamente cuando sus datos locales (nunca
versionados) no están presentes.

### Datos y privacidad

Este repositorio no contiene datos de leads reales. Todos los nombres, teléfonos,
direcciones, dominios e identificadores de Google de los tests y ejemplos son
**ficticios**. Los datos operativos (listas de leads, hojas, registros, archivos `.env`)
se quedan en la máquina del autor y están excluidos por `.gitignore`.

### Licencia

Todos los derechos reservados. El código se publica con fines de portafolio y lectura.
