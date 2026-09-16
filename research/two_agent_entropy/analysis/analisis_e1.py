#!/usr/bin/env python3
"""E1 — placebo en dos niveles: análisis PREREGISTRADO con una sola vía de inferencia.

Registro del análisis (fijado antes de ver las tablas nuevas; véase también
`../../../METHODS_E1.md` si existe en el árbol de resultados)
=============================================================================

Unidad de inferencia
    La corrida. Ninguna prueba trata las llamadas como observaciones
    independientes. Los modelos por llamada (mixto, OLS agrupado) NO se
    calculan aquí: fueron la fuente del error de selección de estimador del
    Exp1. Si se desean como robustez, `entropy_analysis.py` los reporta con
    todas sus p en `stats/E_mixed_model.csv`.

Medida primaria
    Δ por corrida = media(post) − media(pre) de la **entropía por token
    ajustada**, donde el ajuste es el residuo de
        H ~ C(action) + log1p(n_tokens)
    estimado por modelo sobre todas sus condiciones (misma definición que
    `entropy_analysis.adjust`, reutilizada por importación, no reimplementada).
    El corte pre/post es el turno de switch **de cada corrida**
    (`switch_turn_effective`), no una constante.

Contrastes primarios (por modelo, en este orden)
    1. inerte − base           4. switch − inerte
    2. switch − base           5. switch − señuelo
    3. señuelo − base          6. inerte − señuelo
    Prueba: permutación de dos colas sobre la diferencia de medias entre
    corridas, 20 000 réplicas. Corrección de Holm sobre **toda** la familia
    primaria (modelos × contrastes), no dentro de cada modelo.

Predicción registrada (se evalúa explícitamente, sección `prediccion`)
    A. «la entropía sigue contenido accionable»:  base ≈ inerte < switch ≈ señuelo
    B. «la entropía sigue texto ajeno»:           base < inerte ≈ switch ≈ señuelo
    Regla de decisión, con un tamaño de efecto mínimo de interés
    δ = 0,02 bits/token (`--sesi`):
      «mayor»        p_holm < 0,05 y diferencia > 0
      «menor»        p_holm < 0,05 y diferencia < 0
      «equivalente»  IC95 de la diferencia contenido en [−δ, +δ]
      «indeterminado» en cualquier otro caso (ni efecto ni equivalencia)
    A se sostiene si (1) es equivalente, (2) y (3) son mayores y (4) es
    equivalente. B se sostiene si (1) es mayor y (4) y (6) son equivalentes.

Medidas secundarias declaradas (misma unidad y misma prueba; Holm aparte,
sobre toda la familia secundaria)
    · entropía de decisión H(q), Δ post−pre por corrida
    · fracción de informes completos (agentes COMPLETE / agentes de la corrida)
    · comunicación verificada (0/1 por corrida)
    · mezcla de acciones: proporción de READ_LOG y de SUBMIT en la ventana post,
      y Δ post−pre de la proporción de READ_LOG
    · turno de la primera entrega (censurado en el último turno ejecutado;
      se reporta n censuradas y la prueba se hace sobre las corridas con entrega)

Potencia
    DE observada de Δ por corrida y celda, potencia alcanzada para
    δ = 0,02 bits/token con las n realizadas, y n por celda necesaria para
    potencia 0,80 (prueba t de dos muestras, dos colas, α = 0,05).

Salidas (en `--out`, por defecto `<dir de las tablas>/analisis_e1`)
    E1_deltas_por_corrida.csv      una fila por corrida: Δ primario y secundarios
    E1_contrastes_primario.csv     6 contrastes × modelo, con IC, p y p_holm
    E1_contrastes_secundarios.csv  ídem para las medidas secundarias
    E1_prediccion.csv              veredicto A / B / indeterminado por modelo
    E1_potencia.csv                DE, n, potencia alcanzada y n para 0,80
    E1_resumen.json                todo lo anterior más los metadatos de carga
    E1_diagnostico.png             figura de control (no es la del informe)

Uso
    python3 analisis_e1.py --calls exp_e1_calls.csv.gz --runs exp_e1_runs.csv \
        [--out DIR] [--n-perm 20000] [--sesi 0.02] [--post-len 13]
    python3 analisis_e1.py <dir del experimento>          # usa tables_full/
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import entropy_analysis as EA  # noqa: E402

# --------------------------------------------------------------------------- registro

N_PERM = 20_000
SESI = 0.02                       # bits/token: tamaño de efecto mínimo de interés
ALPHA = 0.05
PRIMARIA = "H_adj_delta"

ETIQUETAS = {"base": "base", "placebo_inert": "inerte", "placebo": "señuelo", "switch": "switch"}
CONTRASTES_E1 = [("placebo_inert", "base"), ("switch", "base"), ("placebo", "base"),
                 ("switch", "placebo_inert"), ("switch", "placebo"), ("placebo_inert", "placebo")]
SECUNDARIAS = {
    "H_decision_delta": "entropía de decisión H(q), Δ post−pre",
    "frac_informes_completos": "fracción de informes completos",
    "comunicacion_verificada": "comunicación verificada (0/1)",
    "mezcla_read_post": "proporción de READ_LOG en la ventana post",
    "mezcla_submit_post": "proporción de SUBMIT en la ventana post",
    "mezcla_read_delta": "Δ post−pre de la proporción de READ_LOG",
    "turno_primera_entrega": "turno de la primera entrega (censurado)",
}


def estilo() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif", "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8,
        "legend.fontsize": 7, "xtick.labelsize": 6, "ytick.labelsize": 6,
        "axes.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
        "axes.titleweight": "normal", "axes.titlelocation": "left", "legend.frameon": False,
        "figure.dpi": 200, "savefig.dpi": 300, "savefig.bbox": "tight",
        "lines.linewidth": 1.2, "pdf.fonttype": 42, "ps.fonttype": 42,
    })


# --------------------------------------------------------------------------- datos

def tabla_por_corrida(calls_path: Path, runs_path: Path, *, post_len: int,
                      switch_turn: int) -> tuple[pd.DataFrame, dict]:
    """Una fila por corrida con el Δ primario y todas las secundarias."""
    calls, active, runs, meta = EA.load(calls_path, runs_path, switch_turn_default=switch_turn,
                                        post_len=post_len)
    active = EA.adjust(active)
    base = EA.run_level_deltas(active, {})          # Δ primario y entropía de decisión

    llaves = ["model", "condition", "seed"]
    n_agentes = (runs.set_index(llaves)["n_agents"] if "n_agents" in runs.columns
                 else pd.Series(dtype=float))
    filas = []
    for (m, c, s), df in calls.groupby(llaves):
        ventana = df[(df.turn >= df.switch_turn_eff) & (df.turn < df.switch_turn_eff + post_len)]
        previa = df[df.turn < df.switch_turn_eff]
        acciones_post = ventana[ventana.action.isin(EA.ACTIONS + ["submit"])]
        acciones_pre = previa[previa.action.isin(EA.ACTIONS + ["submit"])]
        entregas = df[df.action == "submit"]
        filas.append({
            "model": m, "condition": c, "seed": s,
            "mezcla_read_post": (acciones_post.action == "read_log").mean() if len(acciones_post) else np.nan,
            "mezcla_submit_post": (acciones_post.action == "submit").mean() if len(acciones_post) else np.nan,
            "mezcla_read_delta": (((acciones_post.action == "read_log").mean() if len(acciones_post) else np.nan)
                                  - ((acciones_pre.action == "read_log").mean() if len(acciones_pre) else np.nan)),
            "turno_primera_entrega": float(entregas.turn.min()) if len(entregas) else np.nan,
            "entrega_censurada": int(len(entregas) == 0),
            "n_llamadas": int(len(df)),
        })
    comportamiento = pd.DataFrame(filas)

    r = runs.copy()
    completos = pd.to_numeric(EA.column(r, "n_complete"), errors="coerce")
    n_ag = pd.to_numeric(r.get("n_agents", pd.Series(2, index=r.index)), errors="coerce").fillna(2)
    r["frac_informes_completos"] = completos / n_ag
    r["comunicacion_verificada"] = (EA.as_bool(r["communication_verified"]).astype(float)
                                    if "communication_verified" in r.columns else np.nan)
    r["exito_tarea"] = (EA.as_bool(r[EA.resolve(r, "task_success")]).astype(float)
                        if EA.resolve(r, "task_success") else np.nan)
    cols_r = llaves + ["switch_turn_eff", "frac_informes_completos", "comunicacion_verificada",
                       "exito_tarea", "tau_read_eff"]

    porcorrida = (base.merge(comportamiento, on=llaves, how="outer")
                  .merge(r[cols_r], on=llaves, how="left"))
    porcorrida["etiqueta"] = porcorrida.condition.map(lambda c: ETIQUETAS.get(c, c))
    meta["n_agents_por_corrida"] = sorted(set(n_ag.astype(int))) if len(n_ag) else []
    return porcorrida, meta


# --------------------------------------------------------------------------- inferencia

def contrastes(porcorrida: pd.DataFrame, metrica: str, familia: str, *, n_perm: int,
               sesi: float) -> pd.DataFrame:
    """Los contrastes de E1 para una métrica, con permutación y IC bootstrap."""
    filas = []
    presentes = set(porcorrida.condition)
    modelos = sorted(set(porcorrida.model))
    for m in modelos:
        sub = porcorrida[porcorrida.model == m]
        for a, b in CONTRASTES_E1:
            if a not in presentes or b not in presentes:
                continue
            va = EA._clean(sub[sub.condition == a][metrica])
            vb = EA._clean(sub[sub.condition == b][metrica])
            fila = {"model": m, "familia": familia, "metrica": metrica,
                    "contraste": f"{ETIQUETAS.get(a, a)} − {ETIQUETAS.get(b, b)}",
                    "condicion_a": a, "condicion_b": b,
                    "n_a": len(va), "n_b": len(vb),
                    "media_a": float(va.mean()) if len(va) else np.nan,
                    "media_b": float(vb.mean()) if len(vb) else np.nan}
            if len(va) < 2 or len(vb) < 2:
                fila.update({"diferencia": np.nan, "ic95_lo": np.nan, "ic95_hi": np.nan,
                             "hedges_g": np.nan, "p_perm": np.nan, "n_perm": n_perm})
                filas.append(fila)
                continue
            dif, p = EA.perm_test(va, vb, n=n_perm, label=("e1", familia, metrica, m, a, b))
            rng = EA._rng(("e1ci", familia, metrica, m, a, b))
            boots = (rng.choice(va, (10_000, len(va))).mean(1)
                     - rng.choice(vb, (10_000, len(vb))).mean(1))
            lo, hi = np.percentile(boots, [2.5, 97.5])
            fila.update({"diferencia": dif, "ic95_lo": float(lo), "ic95_hi": float(hi),
                         "hedges_g": EA.hedges_g(va, vb), "p_perm": p, "n_perm": n_perm})
            filas.append(fila)
    tabla = pd.DataFrame(filas)
    if tabla.empty:
        return tabla
    tabla["p_holm"] = EA.holm(tabla.p_perm.values)          # Holm sobre TODA la familia
    tabla["veredicto"] = [clasificar(r, sesi) for _, r in tabla.iterrows()]
    tabla["sesi"] = sesi
    return tabla


def clasificar(fila, sesi: float) -> str:
    if pd.isna(fila.p_holm):
        return "sin datos"
    if fila.p_holm < ALPHA:
        return "mayor" if fila.diferencia > 0 else "menor"
    if not pd.isna(fila.ic95_lo) and fila.ic95_lo > -sesi and fila.ic95_hi < sesi:
        return "equivalente"
    return "indeterminado"


def prediccion(primarios: pd.DataFrame) -> pd.DataFrame:
    """Evalúa las dos predicciones registradas, por modelo."""
    filas = []
    for m in sorted(set(primarios.model)):
        sub = primarios[primarios.model == m].set_index(["condicion_a", "condicion_b"])

        def ver(a, b):
            try:
                return sub.loc[(a, b), "veredicto"]
            except KeyError:
                return "sin datos"

        v = {"inerte_base": ver("placebo_inert", "base"), "switch_base": ver("switch", "base"),
             "senuelo_base": ver("placebo", "base"), "switch_inerte": ver("switch", "placebo_inert"),
             "switch_senuelo": ver("switch", "placebo"), "inerte_senuelo": ver("placebo_inert", "placebo")}
        a_ok = (v["inerte_base"] == "equivalente" and v["switch_base"] == "mayor"
                and v["senuelo_base"] == "mayor" and v["switch_senuelo"] == "equivalente")
        b_ok = (v["inerte_base"] == "mayor" and v["switch_inerte"] == "equivalente"
                and v["inerte_senuelo"] == "equivalente")
        nulo = all(v[k] in ("equivalente",) for k in ("inerte_base", "switch_base", "senuelo_base"))
        if a_ok and not b_ok:
            veredicto = "A: la entropía sigue contenido accionable (base ≈ inerte < switch ≈ señuelo)"
        elif b_ok and not a_ok:
            veredicto = "B: la entropía sigue texto ajeno (base < inerte ≈ switch ≈ señuelo)"
        elif nulo:
            veredicto = "ninguna: los tres brazos son equivalentes a base para δ declarado"
        else:
            veredicto = "indeterminado"
        filas.append({"model": m, **v, "A_contenido_accionable": a_ok, "B_texto_ajeno": b_ok,
                      "equivalente_a_base_los_tres": nulo, "veredicto": veredicto})
    return pd.DataFrame(filas)


def potencia(porcorrida: pd.DataFrame, primarios: pd.DataFrame, *, sesi: float) -> pd.DataFrame:
    """DE observada, potencia alcanzada y n por celda para potencia 0,80."""
    filas = []
    for m in sorted(set(porcorrida.model)):
        sub = porcorrida[porcorrida.model == m]
        de_celda = {c: float(EA._clean(g[PRIMARIA]).std(ddof=1))
                    for c, g in sub.groupby("condition") if len(EA._clean(g[PRIMARIA])) > 1}
        for _, r in primarios[primarios.model == m].iterrows():
            na, nb = int(r.n_a), int(r.n_b)
            if na < 2 or nb < 2:
                continue
            sa, sb = de_celda.get(r.condicion_a, np.nan), de_celda.get(r.condicion_b, np.nan)
            sp = math.sqrt(((na - 1) * sa ** 2 + (nb - 1) * sb ** 2) / (na + nb - 2))
            ee = sp * math.sqrt(1 / na + 1 / nb)
            gl = na + nb - 2
            tc = stats.t.ppf(1 - ALPHA / 2, gl)
            ncp = sesi / ee
            pot = float(stats.nct.sf(tc, gl, ncp) + stats.nct.cdf(-tc, gl, ncp))
            n_req = np.nan
            for n in range(3, 4001):
                gl_n, ee_n = 2 * n - 2, sp * math.sqrt(2 / n)
                tc_n = stats.t.ppf(1 - ALPHA / 2, gl_n)
                p_n = stats.nct.sf(tc_n, gl_n, sesi / ee_n) + stats.nct.cdf(-tc_n, gl_n, sesi / ee_n)
                if p_n >= 0.80:
                    n_req = n
                    break
            filas.append({"model": m, "contraste": r.contraste, "condicion_a": r.condicion_a,
                          "condicion_b": r.condicion_b, "n_a": na, "n_b": nb,
                          "de_a": sa, "de_b": sb, "de_agrupada": sp, "error_estandar": ee,
                          "sesi_bits": sesi, "potencia_alcanzada": pot,
                          "n_por_celda_para_080": n_req,
                          "dmd_80_con_n_actual": float(ee * (tc + stats.norm.ppf(0.80)))})
    return pd.DataFrame(filas)


# --------------------------------------------------------------------------- figura de control

def figura_diagnostico(porcorrida: pd.DataFrame, primarios: pd.DataFrame, destino: Path,
                       *, sesi: float) -> None:
    estilo()
    modelos = sorted(set(porcorrida.model))
    condiciones = [c for c in ("base", "placebo_inert", "placebo", "switch")
                   if c in set(porcorrida.condition)]
    colores = EA.condition_colours(condiciones)
    fig, axes = plt.subplots(2, max(len(modelos), 1), figsize=(3.4 * max(len(modelos), 1), 5.4),
                             squeeze=False)
    rng = np.random.default_rng(11)
    for j, m in enumerate(modelos):
        ax = axes[0][j]
        for x, c in enumerate(condiciones):
            v = EA._clean(porcorrida[(porcorrida.model == m) & (porcorrida.condition == c)][PRIMARIA])
            if not len(v):
                ax.text(x, 0, "n.d.", ha="center", va="center", fontsize=6, color="#94a3b8")
                continue
            ax.scatter(np.full(len(v), x) + rng.uniform(-0.13, 0.13, len(v)), v, s=7,
                       color=colores[c], alpha=0.65, lw=0)
            media = v.mean()
            ee = v.std(ddof=1) / math.sqrt(len(v)) if len(v) > 1 else 0.0
            t = stats.t.ppf(0.975, max(len(v) - 1, 1))
            ax.errorbar(x + 0.3, media, yerr=t * ee, fmt="o", ms=3.5, color="black", capsize=2, lw=0.9)
        ax.axhline(0, color="#888888", lw=0.6)
        ax.set_xticks(range(len(condiciones)), [ETIQUETAS.get(c, c) for c in condiciones])
        ax.set_title(m)
        if j == 0:
            ax.set_ylabel("Δ entropía ajustada (bits/token)\npost − pre por corrida")
        ax = axes[1][j]
        sub = primarios[primarios.model == m]
        y = np.arange(len(sub))
        ax.errorbar(sub.diferencia, y, xerr=[sub.diferencia - sub.ic95_lo, sub.ic95_hi - sub.diferencia],
                    fmt="o", ms=3.5, color="#0b6e8a", capsize=2, lw=0.9)
        ax.axvspan(-sesi, sesi, color="#888888", alpha=0.12, lw=0)
        ax.axvline(0, color="#888888", lw=0.6)
        ax.set_yticks(y, sub.contraste.tolist())
        ax.invert_yaxis()
        ax.set_xlabel("diferencia de medias (bits/token)")
        if j == 0:
            ax.set_ylabel("contraste primario")
    fig.suptitle("E1 · control: Δ por corrida y contrastes primarios (banda gris: ±δ)", x=0.01,
                 ha="left")
    fig.tight_layout()
    fig.savefig(destino)
    plt.close(fig)


# --------------------------------------------------------------------------- principal

def ejecutar(calls_path: Path, runs_path: Path, out: Path, *, n_perm=N_PERM, sesi=SESI,
             post_len=EA.POST_LEN_DEFAULT, switch_turn=EA.SWITCH_DEFAULT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    porcorrida, meta = tabla_por_corrida(calls_path, runs_path, post_len=post_len,
                                         switch_turn=switch_turn)
    porcorrida.to_csv(out / "E1_deltas_por_corrida.csv", index=False)

    primarios = contrastes(porcorrida, PRIMARIA, "primaria", n_perm=n_perm, sesi=sesi)
    primarios.to_csv(out / "E1_contrastes_primario.csv", index=False)

    secundarios = [contrastes(porcorrida, k, "secundaria", n_perm=n_perm, sesi=sesi)
                   for k in SECUNDARIAS if k in porcorrida.columns]
    secundarios = [t for t in secundarios if len(t)]
    if secundarios:
        sec = pd.concat(secundarios, ignore_index=True)
        sec["p_holm"] = EA.holm(sec.p_perm.values)          # Holm sobre toda la familia secundaria
        sec["veredicto"] = [clasificar(r, sesi) for _, r in sec.iterrows()]
        sec["descripcion"] = sec.metrica.map(SECUNDARIAS)
    else:
        sec = pd.DataFrame()
    sec.to_csv(out / "E1_contrastes_secundarios.csv", index=False)

    pred = prediccion(primarios) if len(primarios) else pd.DataFrame()
    pred.to_csv(out / "E1_prediccion.csv", index=False)
    pot = potencia(porcorrida, primarios, sesi=sesi) if len(primarios) else pd.DataFrame()
    pot.to_csv(out / "E1_potencia.csv", index=False)
    if len(primarios):
        figura_diagnostico(porcorrida, primarios, out / "E1_diagnostico.png", sesi=sesi)

    censura = (porcorrida.groupby(["model", "condition"]).entrega_censurada.agg(["sum", "size"])
               .rename(columns={"sum": "sin_entrega", "size": "corridas"}).reset_index())
    censura.to_csv(out / "E1_censura_entregas.csv", index=False)

    resumen = {
        "registro": {"unidad": "corrida", "metrica_primaria": PRIMARIA,
                     "ajuste": "H ~ C(action) + log1p(n_tokens), por modelo",
                     "corte_pre_post": "switch_turn_effective de cada corrida",
                     "ventana_post_turnos": post_len, "n_perm": n_perm, "alfa": ALPHA,
                     "sesi_bits": sesi, "correccion": "Holm sobre toda la familia primaria",
                     "contrastes": [f"{a} - {b}" for a, b in CONTRASTES_E1],
                     "secundarias": SECUNDARIAS},
        "datos": meta,
        "celdas": {f"{m}|{c}": int(n) for (m, c), n in
                   porcorrida.groupby(["model", "condition"]).size().items()},
        "primario": primarios.to_dict("records"),
        "secundario": sec.to_dict("records") if len(sec) else [],
        "prediccion": pred.to_dict("records") if len(pred) else [],
        "potencia": pot.to_dict("records") if len(pot) else [],
        "censura_entregas": censura.to_dict("records"),
    }
    (out / "E1_resumen.json").write_text(json.dumps(resumen, indent=1, default=float))
    return {"salidas": sorted(p.name for p in out.iterdir()),
            "celdas": resumen["celdas"],
            "veredictos": pred.set_index("model").veredicto.to_dict() if len(pred) else {}}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("exp", nargs="?", type=Path, help="directorio del experimento (usa tables_full/)")
    ap.add_argument("--phase", default="full")
    ap.add_argument("--calls", type=Path, help="tabla de llamadas (csv o csv.gz)")
    ap.add_argument("--runs", type=Path, help="tabla de corridas")
    ap.add_argument("--out", type=Path, help="directorio de salida")
    ap.add_argument("--n-perm", type=int, default=N_PERM)
    ap.add_argument("--sesi", type=float, default=SESI,
                    help="tamaño de efecto mínimo de interés en bits/token")
    ap.add_argument("--post-len", type=int, default=EA.POST_LEN_DEFAULT)
    ap.add_argument("--switch-turn", type=int, default=EA.SWITCH_DEFAULT,
                    help="turno de switch de reserva si las tablas no traen switch_turn_effective")
    args = ap.parse_args(argv)

    if args.calls and args.runs:
        calls_path, runs_path = args.calls, args.runs
        out = args.out or calls_path.parent / "analisis_e1"
    elif args.exp:
        tablas = args.exp / f"tables_{args.phase}"
        calls_path, runs_path = tablas / "calls.csv", tablas / "runs.csv"
        out = args.out or args.exp / "analisis_e1"
    else:
        ap.error("dé un directorio de experimento o --calls y --runs")
    print(json.dumps(ejecutar(calls_path, runs_path, out, n_perm=args.n_perm, sesi=args.sesi,
                              post_len=args.post_len, switch_turn=args.switch_turn),
                     indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
