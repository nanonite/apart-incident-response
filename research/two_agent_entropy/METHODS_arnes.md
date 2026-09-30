# methods.md — track «Arnés» (E2, E2b, smoke)

**Código.** Copia de `research/two_agent_entropy/` (rama `research/exp1-entropy-analysis`, clon del 2026-09-14) modificada sin
commit ni push; sólo biblioteca estándar en el arnés. Diff conceptual fichero por fichero en `CAMBIOS.md`. Tests: 32 (18 originales
intactos + 14 nuevos), `PYTHONSAFEPATH= python3 test_two_agent_entropy.py` → OK.

**E2 · compuerta de integridad de logprobs** (`checker.logprob_integrity`). Para cada llamada real (acción ≠ None/done, sin
api_error) se toma el flujo de tokens de `logprobs_raw.jsonl` (o `api_raw/*.json`), se descartan tokens de control
(`<|im_end|>`, `<|eot_id|>`, `</s>`…), se reconstruye el texto (por bytes UTF-8 cuando cada token trae `bytes`, como OpenAI; si no,
concatenando cadenas) y se calcula `difflib.SequenceMatcher(autojunk=False).ratio()` frente a `completion_text`. Además se comprueba
que entre los 5 primeros tokens con letras hay uno cuyo prefijo clasifica (`entropy.classify_action_token`) a la acción registrada.
Llamada marcada si similitud < 0,99 o token de acción ausente; corrida marcada (`LOGPROB_STREAM_INCOMPLETE`, `entropy_valid=False`)
si la fracción de llamadas marcadas > 0,05. La bandera no altera `valid` ni `task_success`. Calibración sobre las 180 corridas
reales del Exp1 (`E2_compuerta_integridad_exp1.csv`): gpt-4o-mini 60/60 válidas (similitud 1,000), qwen3-235b 60/60 (1,000 tras
descartar `<|im_end|>`; sin ese descarte el 16 % de llamadas cortas caía a < 0,99, un falso positivo de tokenización, no de captura),
llama-3.3-70b/Novita 0/60 (99,8 % de llamadas marcadas, similitud media 0,38, razón logprob/token 0,40). La razón
`tokens_con_logprob / completion_tokens` de qwen es 0,78 porque Vertex cuenta en `completion_tokens` tokens no devueltos en el
flujo (EOS/plantilla); es informativa y no entra en la bandera.

**E2b · sondeo de proveedores para Llama** (`probe_llama_providers.py`, `E2b_sondeo_proveedores_llama.csv`, 72 filas, 0,0034 USD).
`meta-llama/llama-3.3-70b-instruct` vía OpenRouter con `provider.order=[X]`, `allow_fallbacks=false`, `logprobs=true`,
`top_logprobs=20`, `temperature=1`, `max_tokens=120`, 3 prompts (~60 tokens de salida: acción+nota, prosa, código), semilla fija.
Proveedores probados: los 12 endpoints listados por `/models/…/endpoints` más 24 nombres conocidos (24 devuelven 404 «No endpoints»).
Resultado: SambaNova (`sambanova-turbo`) similitud 1,000 y un logprob por token en los 3 prompts, top-20 presente; CoreWeave 0,945-0,98,
AkashML 0,944-0,975, Parasail 0,917-0,978, Novita 0,83-0,96 (el proveedor del Exp1, reproduce el defecto); DeepInfra, Groq, Together,
Crusoe y Cloudflare no devuelven logprobs. Verificación adicional (3 filas `long_verify_*`): con `harness.call_openrouter`
(`require_parameters=true`, `max_tokens=700`) SambaNova mantiene 1,000 en completions de 239 y 297 tokens. SambaNova no declara el
parámetro `seed` (OpenRouter lo filtra con `require_parameters`), por lo que se añadió `ModelSpec.supports_seed=False` y el modelo
`llama-3.3-70b-sambanova`; el muestreo deja de ser reproducible por semilla (la `api_seed` se registra igualmente).
**Recomendación:** usar `llama-3.3-70b-sambanova` para las medidas entrópicas de Llama en E1/E5/E8; las 60 corridas Llama/Novita del
Exp1 quedan fuera de las medidas entrópicas (verdad-terreno intacta). Límite: 3+3 prompts cortos y una sesión; la compuerta E2 debe
seguir activa en la matriz para confirmarlo corrida a corrida.

**Smoke en vivo** (`smoke_runs.py`, `E7smoke_corridas_gpt4omini.csv`; 6 corridas gpt-4o-mini, `max_turns=12`,
`early_stop_turn=10`, presupuesto 0,20 USD, gasto 0,0176 USD): base, switch (turno 8), placebo (donor_log real del Exp1 gpt-4o-mini),
placebo_inert (calendario del mismo donante: 8 entradas inertes mostradas), switch aleatorizado rango 4-7 + cierre +3 (sorteo →
abre 5, cierra 8; ventana observada turnos 5-7 en ambos agentes), tres agentes switch turno 6 (36 llamadas; A3 sin contraseña,
`provenance_ok=True`). 0 errores API en 155 llamadas; ficheros alineados (turns ↔ logprobs_raw ↔ entropy_tokens ↔ api_raw) en
las 6 corridas; compuerta en verde (0 llamadas marcadas, similitud 1,000). `analyze.py` **original** del repo procesa las 6
corridas (runs.csv/calls.csv/system_entropy.csv/report_full.html). `analysis/entropy_analysis.py` original **no** procesa el smoke:
está cableado a la matriz exacta del Exp1 (`MODELS` = 3 modelos, `CONDITIONS` = base/switch/placebo, `SWITCH = 8`) y falla con
`.item()` cuando falta una celda modelo×condición; no es un problema del esquema de corridas sino un punto a adaptar en el track de
análisis (placebo_inert, `switch_turn_effective` por corrida, A3). Escenario del smoke generado nuevo (`smoke-main`/`smoke-donor`);
el donor_log real pertenece al donante del Exp1, así que la comprobación de contaminación del placebo no es interpretable en el smoke.
Con 12 turnos ningún agente entregó informe completo (esperado: en el Exp1 los COMPLETE llegan en los turnos 9-30).
