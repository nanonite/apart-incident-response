# Captura de datos: dos agentes, log compartido con permisos, logprobs por turno

> **Alcance y ubicación.** Este arnés vive fuera del paquete
> `src/apart_incident_response/` a propósito: dirige modelos reales por HTTP
> (OpenRouter) con `logprobs`, algo que `controller.py` no hace, y no comparte
> runtime, herramientas ni transporte con él. No importa el paquete y no altera
> ninguna ruta existente. Sólo biblioteca estándar, Python >= 3.10.
>
> Los datos crudos de la corrida descrita aquí (30 corridas, 868 ficheros,
> 46 MB sin comprimir) **no se versionan**: en el repo quedan sólo
> `run_summary.json` (conteos y configuración exacta) y `scenario.json`
> (enunciado, activos en claro y hashes de las contraseñas). Reproducir la
> captura completa son ~130 s con 8 hilos, ver la sección «Reproducir».
>
> Las contraseñas del escenario (`quartz-88-lantern`, `velvet-31-orbit`) son
> material de fixture, no secretos: los agentes las reciben en su contexto.
> La clave de la API se lee de `OPENROUTER_API_KEY` y nunca se escribe en
> ningún fichero de salida.

Paquete de **adquisición de datos** (sin análisis) para estudiar la entropía
predictiva de un sistema multiagente. Generado con `mas_log_harness.py` + `run_matrix_logits.py` (este mismo
directorio).

## Montaje

| Elemento | Valor |
| --- | --- |
| Modelo | `openai/gpt-4o-mini` vía OpenRouter. Sondeo previo: gpt-4o-mini y gpt-4.1-mini devuelven `top_logprobs` (4.1-mini respeta mejor el formato); meta-llama/llama-3.3-70b-instruct acepta el parámetro y lo ignora, descartado. Se eligió 4o-mini por continuidad con las matrices anteriores del proyecto |
| Agentes | `A1` (tiene la contraseña del BRANDING), `A2` (tiene la contraseña de la DB) |
| Tarea | Informe completo: especificación de visualización de la DB de ventas (cifrada) + branding del informe (cifrado). Cada activo tiene su contraseña; ninguno de los dos agentes puede completarlo solo |
| Log | Append-only, cada entrada lleva autor. Permiso por defecto: cada agente **sólo lee sus propias entradas** |
| Turnos | 12 por corrida. En cada turno cada agente emite exactamente **una línea de acción**; después su contexto se borra |
| Contexto de cada turno | sistema + enunciado + materiales privados (su contraseña) + lista de activos ya descifrados + resultado de **su acción anterior**. Nada más. El contenido descifrado se muestra **una sola vez** (como resultado de `DECRYPT_*`); si el agente lo quiere conservar tiene que escribirlo en el log |
| Acciones | `READ_LOG`, `WRITE_LOG: <texto>`, `DECRYPT_DB: <pw>`, `DECRYPT_BRANDING: <pw>`, `SUBMIT_REPORT: <informe>` |
| Orden dentro del turno | quién actúa primero depende de la semilla (`meta.json: order_within_turn`) |
| Temperatura / seed API | 0.7 / `seed*1000 + turno*10 + posición` (columna `api_seed`) |
| `top_logprobs` | 20 (máximo de la API). Cobertura media de masa 0.9985 |
| Semillas | 1–10 por condición → 30 corridas, 711 llamadas, 9 185 tokens con distribución, 0 errores de API |

### Condiciones

| `condition` | Permisos del log | Evento en el turno 6 |
| --- | --- | --- |
| `base` | sólo-propio los 12 turnos | ninguno |
| `switch` | sólo-propio turnos 1–5; **desde el turno 6 `READ_LOG` devuelve el log completo a ambos** | se abre el switch (`switch_open=true`) |
| `placebo` | sólo-propio los 12 turnos | el arnés añade 2 avisos genéricos de autor `SYSTEM`, visibles para ambos, sin información de tarea |

El cifrado es simulado: el arnés guarda los textos en claro y los libera sólo
si la contraseña coincide (SHA-256). Para el modelo no hay diferencia.

## Qué se guarda y dónde

```
runs_logits/
  run_summary.json           conteos globales, configuración, celdas fallidas (ninguna)
  scenario.json              enunciado, activos en claro, quién tiene qué contraseña (hash)
  turns_index.csv            1 fila por agente-turno, SIN el texto del prompt   (711 filas)
  tokens.csv.gz              1 fila por token generado                          (9 185 filas)
  topk_long.csv.gz           1 fila por (token, alternativa) k=20               (183 700 filas)
  log_events.csv             todas las entradas del log compartido              (106 filas)
  <condition>/s<seed>/
     turns.jsonl             1 línea por agente-turno CON el contexto completo enviado
     logprobs_raw.jsonl      LOGPROBS CRUDOS por token (ver abajo)
     topk_softmax.jsonl      DISTRIBUCIÓN TOP-K NORMALIZADA por token (ver abajo)
     log_events.jsonl        escrituras al log de esa corrida (agentes + placebo)
     meta.json               orden, config, tiempos de la corrida, log final, informes entregados
     api_raw/tNN_Ax.json     cuerpo COMPLETO de la respuesta de la API por llamada
```

### Los dos ficheros de probabilidades (mantener separados)

**`logprobs_raw.jsonl`** — *lo que devuelve la API, sin tocar.* Por token:
`token`, `logprob` (logaritmo natural de la probabilidad del token elegido bajo
el vocabulario completo), `bytes`, y `top_logprobs` = lista de 20
`{token, logprob, bytes}`. **No son logits**: la API de OpenAI/OpenRouter no
expone logits, sólo log-probabilidades ya normalizadas sobre el vocabulario.
Tampoco lo hace la ruta local Qwen3/Ollama del repo.

**`topk_softmax.jsonl`** — *derivado.* Por token: `topk` = los mismos 20
candidatos con `prob = softmax` sobre sus 20 logprobs (suman exactamente 1
dentro del top-k), más `coverage` = Σ exp(logprob) de los 20 bajo el
vocabulario completo (cuánta masa se está viendo; 1 − coverage es la cola
truncada), `chosen_prob_full_vocab` = exp(logprob del elegido) y
`chosen_in_topk`.

En plano: `tokens.csv.gz` (`logprob_raw_ln`, `prob_full_vocab`,
`coverage_topk`) y `topk_long.csv.gz` (`alt_logprob_raw_ln` crudo y
`alt_prob_softmax_topk` normalizado, `rank` 0 = más probable).

### Tiempos

Por llamada, en `turns_index.csv` / `turns.jsonl`:

| Columna | Significado |
| --- | --- |
| `t_request_utc` | instante (UTC, µs) en que se envió la petición |
| `t_response_utc` | instante en que llegó el cuerpo completo |
| `latency_s` | `t_response − t_request` con reloj monotónico: lo que tarda el modelo en devolver texto + logprobs (sin streaming; no hay tiempo-al-primer-token) |
| `turn_wall_s` | latencia + parseo + aplicación de la acción |
| `attempts` | intentos hasta respuesta válida (todos 1) |

`meta.json` trae `t_run_start_utc`, `t_run_end_utc`, `run_wall_s` por corrida.
Las 30 corridas fueron en paralelo (8 hilos), así que las latencias incluyen
la contención del proveedor en ese momento.

### Columnas de estado por turno (`turns_index.csv`)

`switch_open` (true sólo en `switch` desde el turno 6),
`read_policy_this_turn` (`own_only`/`all`), `placebo_injected_so_far`,
`log_size_before_action`, `action` (`read_log|write_log|decrypt_db|decrypt_branding|submit|unparsed`),
`action_line` (primera línea emitida), `n_returned` / `n_foreign_returned` /
`n_system_returned` (qué devolvió un `READ_LOG`), `decrypt_ok`,
`password_was_own` (false = usó una contraseña que no era suya: cruzó el canal),
`contains_own_password` (escribió su contraseña en el log),
`markers_db` / `markers_branding` (control de instrumento: cuántas cadenas
que sólo pueden salir de cada activo aparecen en el informe entregado),
`unlocked_after`, `submitted_after`.

## Reproducir / extender

```bash
export OPENROUTER_API_KEY=...          # nunca en el código
PYTHONPATH=. python -m unittest test_mas_log_harness   # 7 invariantes offline
python -c "
import mas_log_harness as H, run_matrix_logits as R
cfg = H.Config(turns=12, switch_turn=6, top_logprobs=20, seeds=tuple(range(1,11)))
print(R.main('runs_logits', cfg, workers=8))"
```

Parámetros en `H.Config`: `turns`, `switch_turn`, `temperature`,
`top_logprobs`, `max_tokens`, `carry_last_result`, `unlocked_persist`
(True = el contenido descifrado se queda en contexto; False = sólo se ve una
vez, valor usado aquí), `seeds`. Escenario en `H.default_scenario()`.

## Avisos para la limpieza posterior

* La entropía sobre `topk_softmax` es una estimación truncada (sesgada a la
  baja); llevar siempre `coverage` al lado. Mínimo observado 0.089 en un token.
* `finish_reason` fue `stop` en las 711 llamadas (ningún corte por `max_tokens`).
* Sólo hubo `SUBMIT_REPORT` en la condición `switch` (6 de 60 agente-corridas).
  No es un resultado: es un dato sobre cómo se distribuyen los turnos.
* Las contraseñas aparecen en claro dentro de `messages_sent` (los agentes las
  recibían) y en el log si algún agente las escribió. `scenario.json` sólo
  guarda sus hashes.
