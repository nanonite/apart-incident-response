# CAMBIOS — arnés extendido del Exp1 (`research/two_agent_entropy/`)

Rama base: `research/exp1-entropy-analysis`. Sólo biblioteca estándar. `schema_version` pasa de 1 a 2; **todos los
ficheros de salida conservan las claves de la versión 1** (turns.jsonl, logprobs_raw.jsonl, entropy_tokens.jsonl,
log.jsonl, check.json, meta.json, api_raw/), de modo que `analyze.py` y `analysis/entropy_analysis.py` originales
siguen leyendo las corridas nuevas; las claves nuevas son adicionales. Con la configuración por defecto
(`RunConfig()` sin extensiones, `n_agents=2`) el comportamiento es byte-idéntico al original: mismos prompts, mismo
orden por semilla, misma política de lectura, mismas filas.

## scenario.py
- `OBSERVER = "A3"`, `MAX_AGENTS = 3`, `agents_for(n)`, `is_holder(a)`, `own_asset(a)` (None para A3).
- `Scenario.private_note("A3")`: texto explícito «no tienes ninguna contraseña; todo lo que sepas debe venir del log».
  Las notas de A1/A2 y `STATEMENT` no cambian.

## harness.py
- `CONDITIONS = ("base", "switch", "placebo", "placebo_inert")`; `FOREIGN_CONDITIONS` = las tres con «momento switch».
- `SYSTEM_PROMPT_OBSERVER`: idéntico a `SYSTEM_PROMPT` salvo que faltan las dos líneas `DECRYPT_*` (aserción en carga).
- `INERT_SENTENCES` + `make_inert_entries(seed, agents, cfg, schedule)`: entradas genéricas sin forma de tarea,
  determinísticas por semilla, con el mismo calendario (turno, posición, autor) que el donante cuando se pasa
  `donor_entries`, y longitud objetivo `cfg.inert_target_chars` (por defecto 330 = media medida en exp1-donor, n = 43,
  mediana 316; cada entrada sortea 0,6×–1,4×). `inert_text_is_clean(text, *scenarios)` valida en tiempo de ejecución
  (aserción) que ninguna entrada contiene `tbl_`, `_id_`, `mark_`, `#`, dígitos, fuentes, títulos ni marcador alguno
  de los activos de los escenarios (principal y donante) y que `grade_report` la puntúa `NONE`.
- `RunConfig`: nuevos campos `switch_turn_range=(lo, hi) | None`, `close_turn_offset | None`, `n_agents=2`,
  `inert_target_chars=330`; validación en `__post_init__` (acepta listas del JSON de `experiment.json`).
- `effective_switch_turn(cfg, seed)` (sorteo `random.Random(f"switch:{seed}")`, uniforme en el rango, igual para
  todos los agentes y condiciones de esa semilla), `close_turn(cfg, seed)`, `foreign_window_open(condition, turn, cfg, seed)`.
- `read_policy(condition, turn, cfg, seed=None)`: «all» sólo en switch y dentro de la ventana
  `[switch_eff, switch_eff + offset)`; sin `seed` reproduce la semántica v1.
- `ModelSpec.supports_seed` (False ⇒ se omite `seed` del payload manteniendo `require_parameters`). Modelo nuevo
  `llama-3.3-70b-sambanova` (proveedor `sambanova-turbo`), resultado del sondeo E2b.
- `build_messages`: rama observador (prompt de sistema sin DECRYPT, bloque de materiales sin contraseña, sin lista de
  activos descifrados). Para A1/A2 el mensaje es idéntico al original.
- `run_one`:
  - orden dentro del turno: 2 agentes → igual que v1 (`random() < 0.5` invierte); 3 agentes → `shuffle` por semilla.
  - `base_row` añade `role`, `read_policy_this_turn`, `switch_open`, `foreign_window_open`, `switch_turn_effective`,
    `switch_closed_turn` en **cada** fila de turns.jsonl.
  - READ_LOG: `placebo` intacto (usa la ventana en vez de `turn >= switch_turn`, equivalente con la config v1);
    `placebo_inert` muestra las entradas inertes con autor = compañero, registra en log.jsonl
    `source="placebo_inert"` (+ `revealed_turn`, `shown_as_author`) y en turns.jsonl `returned_inert_seqs` (`I<n>`).
    `returned_placebo_seqs` sigue existiendo (vacío en inert).
  - DECRYPT del observador: registrado como `action="decrypt"`, `decrypt_ok=False`, `denied=True`, `password_source`
    (permite saber si A3 llegó a ver una contraseña en el log) — nunca descifra.
  - `contains_own_password` tolera agentes sin activo.
  - meta.json añade `agents`, `n_agents`, `switch_turn_effective`, `switch_closed_turn`, `inert_entries`.
  - `checker.check_run(..., agents=, raw_tokens=logprobs_raw)`.

## checker.py
- Constantes de la compuerta: `SIMILARITY_MIN = 0.99`, `FLAGGED_FRACTION_MAX = 0.05`, `ACTION_TOKEN_WINDOW = 5`,
  `LOGPROB_FLAG = "LOGPROB_STREAM_INCOMPLETE"`.
- `is_control_token`, `tokens_text` (concatenación sin tokens de control `<|im_end|>`, `<|eot_id|>`, `</s>`…),
  `stream_similarity` (difflib, autojunk=False), `action_token_present`, `call_integrity`, `logprob_integrity(turns,
  raw_tokens, run_dir)` (lee logprobs_raw.jsonl o, en su defecto, api_raw/*.json). `check.json["logprob_integrity"]` =
  `{n_calls, frac_flagged, frac_low_similarity, frac_action_token_missing, mean_similarity, mean_logprob_ratio,
  thresholds, entropy_valid, flagged_calls}`. La bandera se añade a `flags` pero **no** entra en `valid` ni en
  `task_success`. CLI: `python3 checker.py <run_dir>` recalcula la compuerta de una corrida existente.
  Calibración sobre las 180 corridas reales del Exp1: gpt-4o-mini 60/60 `entropy_valid`, qwen3-235b 60/60 (tras
  descartar `<|im_end|>`; sin descartarlo el 16 % de llamadas cortas caía por debajo de 0,99), llama-3.3-70b 0/60
  (99,8 % de llamadas marcadas, similitud media 0,38).
- `check_run(turns, log, sc, *, condition, donor=None, agents=None, raw_tokens=None, run_dir=None)`:
  - `agents` se infiere de las filas si no se pasa (A1, A2 + cualquier otro id visto).
  - direcciones de comunicación `holder -> cada otro agente` (`A1->A2`, `A2->A1`, y con 3 agentes `A1->A3`, `A2->A3`).
  - `asset_carriers` por activo incluye relevos por terceros; `IMPOSSIBLE_KNOWLEDGE` usa como «legible» toda entrada
    ajena con marcadores del activo (en el caso de 2 agentes coincide exactamente con v1) y para el observador se
    evalúan los dos activos.
  - bloque `observers[A3] = {grade, submitted_turn, provenance{asset: {carrier_seqs_readable, tau_first_carrier_read,
    markers_in_report, traceable}}, provenance_ok, decrypt_attempts_denied, received_password=False}`.
  - `LEAK` se comprueba también en `placebo_inert`. `complete_via_verified_channel` recorre holders × agentes.
  - claves nuevas en check.json: `agents`, `observers`, `logprob_integrity`.

## run.py
- `init`: `--max-turns`, `--early-stop-turn`, `--switch-turn`, `--switch-range LO,HI`, `--close-offset K`,
  `--n-agents {2,3}` (se congelan en `experiment.json["config"]`).
- `full`: acepta `placebo_inert` (usa el donor_log como calendario si existe; si no, calendario por defecto) y
  `--seed-start`; valida los nombres de condición. Resumen añade `entropy_valid`; `both_complete` usa `>= 2`.

## analyze.py (cambios mínimos, compatibles)
- Colour de `placebo_inert`; la condición aparece en el informe HTML.
- runs.csv añade `switch_turn_effective`, `switch_closed_turn`, `n_agents`, `entropy_valid`, `logprob_frac_flagged`,
  `logprob_mean_similarity`, `grade_A3`, `A3_provenance_ok`; calls.csv añade `n_inert_returned`, `switch_open`, `role`.
  Corridas v1 obtienen None en esas columnas. La descomposición de sistema sigue sobre (A1, A2).

## test_two_agent_entropy.py (18 → 32 tests, todos verdes)
- `fake_tokens` ahora reproduce el texto exactamente (necesario para la compuerta); los 18 tests originales no cambian.
- `PlaceboInertTests`: material limpio en 20 semillas × 2 escenarios, determinismo, longitud calibrada, la corrida
  nunca devuelve entradas reales ajenas ni cadenas de hecho, log.jsonl con `placebo_inert`, decoy `placebo` intacto.
- `RandomisedSwitchTests`: cobertura del rango, determinismo, ida y vuelta JSON, apertura/cierre correctos para ambos
  agentes (`switch_open`, `read_policy_this_turn`, `returned_real_foreign_seqs`), ventana del placebo/inert sigue al sorteo.
- `LogprobIntegrityTests`: flujo íntegro no marcado; flujo sintético al 40 % (sin el primer token) marcado, con
  `valid`/`task_success`/`communication` idénticos al caso limpio; el bloque aparece en una corrida del arnés.
- `ThreeAgentTests`: A3 no recibe contraseña ni acción DECRYPT (prompts de A1/A2 byte-idénticos), DECRYPT denegado,
  procedencia evaluada (VERIFIED `A1->A3`, `A2->A3`, `tau_first_carrier_read`), conocimiento imposible del observador
  marcado, base sin fugas, caso de dos agentes sin cambios.

## Ficheros nuevos
- `probe_llama_providers.py`: sondeo E2b (3 prompts × proveedor, logprobs/top_logprobs=20, proveedor fijado).
- `smoke_runs.py`: smoke en vivo (una corrida por condición, presupuesto acotado) + `analyze.main`.
- `README.md`: sección «Extensiones (v2)».
