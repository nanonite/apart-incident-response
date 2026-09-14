# Free-Model Reasoning Floor

The optional `reasoning_baseline` module measures a minimal capability floor,
not communication or entropy science. It uses three independent closed-world
cases: arithmetic, conjunction, and a short fictional rule chain.

The default model is `inclusionai/ling-3.0-flash-vl:free`. The catalog also
contains the supplied Nex-AGI, Ling Sante/Fin, and Liquid free candidates.
Models must use an OpenRouter `:free` slug. The live path is capped at three
requests and 96 output tokens per request.

Plan without network access:

```bash
PYTHONPATH=src uv run python -m apart_incident_response.reasoning_baseline
```

Opt-in free smoke, after capability approval:

```bash
PYTHONPATH=src uv run python -m apart_incident_response.reasoning_baseline --live
```

The provider reads `OPENROUTER_API_KEY` or `OPEN_ROUTER_API_KEY` from the
controller environment, then falls back to the repository `.env` and the
existing local `~/.config/apart-incident-response/openrouter.env` convention.
The key is only used in the authorization header.

The report records correct/incorrect/invalid/unavailable outcomes, response
hashes, timing, and logprob coverage. It does not retain raw responses or
credentials and is not included in ISO/FULL/COMM outcome estimates.
