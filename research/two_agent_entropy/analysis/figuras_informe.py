#!/usr/bin/env python3
"""Figuras del informe E1–E8 (grado publicación) a partir de las tablas de `analisis_e1.py`.

Cada función recibe rutas de CSV y un destino PNG, y no calcula estadística: todo
lo que dibuja viene ya calculado en `E1_*.csv`, de modo que la figura y el texto
del informe no puedan discrepar. Se ejecutan cuando existan las tablas de E1:

    python3 figuras_informe.py <dir con E1_*.csv> --out <dir de figuras>

Reglas de figura aplicadas (checklist de estilo publicable)
    · un mensaje por figura, título en lenguaje llano que dice la comparación
    · n y unidad de réplica siempre visibles (n corridas por celda)
    · tres tamaños de letra como máximo; ejes sin marco superior/derecho
    · un color por condición, el mismo en todos los paneles y figuras
    · banda gris = región de equivalencia ±δ (tamaño de efecto mínimo de interés)
    · nunca rojo/verde como par opuesto; el señuelo usa naranja y el inerte ocre
    · sin barras sobre eje logarítmico, sin ceros implícitos: las celdas ausentes
      se marcan «n.d.»
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

COLORES = {"base": "#64748b", "placebo_inert": "#a16207", "placebo": "#c2410c", "switch": "#0b6e8a"}
ETIQUETAS = {"base": "base", "placebo_inert": "inerte", "placebo": "señuelo", "switch": "switch"}
ORDEN = ["base", "placebo_inert", "placebo", "switch"]
GRIS = "#888888"
PRIMARIA = "H_adj_delta"


def estilo(sizes=(8, 7, 6)) -> None:
    base, secundario, tick = sizes
    plt.rcParams.update({
        "font.family": "sans-serif", "font.size": base, "axes.labelsize": base,
        "axes.titlesize": base, "legend.fontsize": secundario, "xtick.labelsize": tick,
        "ytick.labelsize": tick, "axes.linewidth": 0.6, "axes.spines.top": False,
        "axes.spines.right": False, "axes.titleweight": "normal", "axes.titlelocation": "left",
        "axes.labelweight": "normal", "legend.frameon": False, "figure.dpi": 200,
        "savefig.dpi": 300, "savefig.bbox": "tight", "lines.linewidth": 1.2,
        "patch.linewidth": 0.6, "pdf.fonttype": 42, "ps.fonttype": 42,
        "xtick.direction": "out", "ytick.direction": "out",
    })


def letra_panel(ax, letra: str) -> None:
    ax.text(-0.12, 1.06, letra, transform=ax.transAxes, fontweight="bold", fontsize=9,
            va="bottom", ha="right")


def _presentes(df: pd.DataFrame, columna="condition") -> list[str]:
    vistos = set(df[columna])
    return [c for c in ORDEN if c in vistos] + sorted(vistos - set(ORDEN))


def _media_ic(v: np.ndarray) -> tuple[float, float]:
    if len(v) < 2:
        return (float(v.mean()) if len(v) else np.nan, np.nan)
    t = stats.t.ppf(0.975, len(v) - 1)
    return float(v.mean()), float(t * v.std(ddof=1) / math.sqrt(len(v)))


# --------------------------------------------------------------------------- figura 1

def figura_e1_principal(deltas_csv, contrastes_csv, destino, sesi=0.02) -> Path:
    """Δ de entropía ajustada por corrida y los seis contrastes primarios de E1."""
    estilo()
    d = pd.read_csv(deltas_csv)
    k = pd.read_csv(contrastes_csv)
    modelos = sorted(set(d.model))
    condiciones = _presentes(d)
    fig, axes = plt.subplots(2, len(modelos), figsize=(3.2 * len(modelos), 5.6), squeeze=False,
                             gridspec_kw={"height_ratios": [1.05, 1]})
    rng = np.random.default_rng(3)
    for j, m in enumerate(modelos):
        ax = axes[0][j]
        for x, c in enumerate(condiciones):
            v = d[(d.model == m) & (d.condition == c)][PRIMARIA].dropna().values
            if not len(v):
                ax.annotate("n.d.", (x, 0.5), xycoords=("data", "axes fraction"),
                            ha="center", va="center", fontsize=6, color=GRIS)
                continue
            ax.scatter(np.full(len(v), x) + rng.uniform(-0.14, 0.14, len(v)), v, s=7,
                       color=COLORES.get(c, GRIS), alpha=0.6, lw=0)
            media, ic = _media_ic(v)
            ax.errorbar(x + 0.32, media, yerr=ic, fmt="o", ms=3.5, color="black", capsize=2, lw=0.9)
            ax.annotate(f"n={len(v)}", (x, ax.get_ylim()[0]), xytext=(x, 0.02),
                        textcoords=("data", "axes fraction"), ha="center", fontsize=6, color=GRIS)
        ax.axhline(0, color=GRIS, lw=0.6)
        ax.set_xticks(range(len(condiciones)), [ETIQUETAS.get(c, c) for c in condiciones])
        ax.set_xlim(-0.55, len(condiciones) - 0.35)
        ax.set_title(m)
        ax.margins(y=0.06)
        if j == 0:
            ax.set_ylabel("Δ entropía ajustada por corrida\n(bits/token, post − pre)")
            letra_panel(ax, "a")
        ax = axes[1][j]
        sub = k[k.model == m].reset_index(drop=True)
        y = np.arange(len(sub))
        ax.axvspan(-sesi, sesi, color=GRIS, alpha=0.13, lw=0, zorder=0)
        for i, r in sub.iterrows():
            color = COLORES.get(r.condicion_a, GRIS)
            ax.errorbar(r.diferencia, i, xerr=[[r.diferencia - r.ic95_lo], [r.ic95_hi - r.diferencia]],
                        fmt="o", ms=4, color=color, capsize=2, lw=1.0, zorder=3)
            marca = "*" if r.p_holm < 0.05 else ""
            ax.text(r.ic95_hi, i, f" {r.diferencia:+.3f}{marca}", va="center", fontsize=6)
        ax.axvline(0, color=GRIS, lw=0.6)
        ax.set_yticks(y, sub.contraste.tolist())
        ax.invert_yaxis()
        ax.set_xlabel("diferencia de medias (bits/token)")
        ax.margins(x=0.22)
        if j == 0:
            letra_panel(ax, "b")
    fig.suptitle("E1 · entropía por token ajustada: cambio post−pre por corrida y los seis "
                 "contrastes preregistrados\n"
                 "(a) una marca por corrida, negro = media ± IC95 · (b) diferencia de medias; "
                 "banda gris = equivalencia ±%.2f bits/token; * = Holm < 0,05" % sesi,
                 x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(destino)
    plt.close(fig)
    return Path(destino)


# --------------------------------------------------------------------------- figura 2

def figura_e1_prediccion(prediccion_csv, contrastes_csv, destino) -> Path:
    """Veredicto por contraste y modelo frente a las dos predicciones registradas."""
    estilo()
    k = pd.read_csv(contrastes_csv)
    p = pd.read_csv(prediccion_csv)
    orden_contrastes = list(dict.fromkeys(k.contraste))
    modelos = sorted(set(k.model))
    codigo = {"mayor": 2, "menor": -2, "equivalente": 0, "indeterminado": 1, "sin datos": np.nan}
    matriz = np.full((len(orden_contrastes), len(modelos)), np.nan)
    for i, c in enumerate(orden_contrastes):
        for j, m in enumerate(modelos):
            fila = k[(k.model == m) & (k.contraste == c)]
            if len(fila):
                matriz[i, j] = codigo.get(fila.veredicto.iloc[0], np.nan)
    fig, ax = plt.subplots(figsize=(1.9 + 1.5 * len(modelos), 0.52 * len(orden_contrastes) + 2.0))
    cmap = matplotlib.colors.ListedColormap(["#1d4ed8", "#e5e7eb", "#f1f5f9", "#b91c1c"])
    norma = matplotlib.colors.BoundaryNorm([-2.5, -1.5, -0.5, 1.5, 2.5], cmap.N)
    ax.imshow(matriz, cmap=cmap, norm=norma, aspect="auto")
    for i in range(len(orden_contrastes)):
        for j, m in enumerate(modelos):
            fila = k[(k.model == m) & (k.contraste == orden_contrastes[i])]
            if not len(fila):
                ax.text(j, i, "n.d.", ha="center", va="center", fontsize=6, color=GRIS)
                continue
            r = fila.iloc[0]
            ax.text(j, i, f"{r.veredicto}\n{r.diferencia:+.3f} (Holm {r.p_holm:.3f})",
                    ha="center", va="center", fontsize=6,
                    color="white" if r.veredicto in ("mayor", "menor") else "black")
    ax.set_xticks(range(len(modelos)), modelos, rotation=12, ha="right")
    ax.set_yticks(range(len(orden_contrastes)), orden_contrastes)
    ax.set_title("E1 · veredicto de cada contraste primario\n"
                 "predicción A (contenido accionable): inerte−base equivalente, switch−base y "
                 "señuelo−base mayores, switch−señuelo equivalente\n"
                 "predicción B (texto ajeno): inerte−base mayor, switch−inerte y inerte−señuelo "
                 "equivalentes")
    texto = "  ·  ".join(f"{r.model}: {r.veredicto}" for _, r in p.iterrows())
    ax.set_xlabel("veredicto global — " + texto, fontsize=6)
    fig.tight_layout()
    fig.savefig(destino)
    plt.close(fig)
    return Path(destino)


# --------------------------------------------------------------------------- figura 3

def figura_e1_secundarios(deltas_csv, secundarios_csv, destino) -> Path:
    """Las cinco medidas secundarias declaradas, por condición y modelo."""
    estilo()
    d = pd.read_csv(deltas_csv)
    s = pd.read_csv(secundarios_csv) if Path(secundarios_csv).exists() else pd.DataFrame()
    metricas = [("H_decision_delta", "Δ entropía de decisión (bits)"),
                ("frac_informes_completos", "fracción de informes completos"),
                ("comunicacion_verificada", "comunicación verificada"),
                ("mezcla_read_post", "proporción de READ_LOG (post)"),
                ("mezcla_submit_post", "proporción de SUBMIT (post)"),
                ("turno_primera_entrega", "turno de la primera entrega")]
    metricas = [(k, t) for k, t in metricas if k in d.columns]
    modelos = sorted(set(d.model))
    condiciones = _presentes(d)
    fig, axes = plt.subplots(len(metricas), len(modelos),
                             figsize=(2.6 * len(modelos), 1.65 * len(metricas)), squeeze=False,
                             sharey="row")
    for i, (k, titulo) in enumerate(metricas):
        for j, m in enumerate(modelos):
            ax = axes[i][j]
            for x, c in enumerate(condiciones):
                v = d[(d.model == m) & (d.condition == c)][k].dropna().values
                if not len(v):
                    ax.annotate("n.d.", (x, 0.5), xycoords=("data", "axes fraction"),
                                ha="center", va="center", fontsize=5.5, color=GRIS)
                    continue
                media, ic = _media_ic(v)
                ax.errorbar(x, media, yerr=ic, fmt="o", ms=3.2, color=COLORES.get(c, GRIS),
                            capsize=2, lw=0.9)
                ax.text(x, media, f"  {media:.2f}", fontsize=5.5, va="center", ha="left")
            ax.set_xlim(-0.55, len(condiciones) - 0.35)
            ax.set_xticks(range(len(condiciones)),
                          [ETIQUETAS.get(c, c) for c in condiciones] if i == len(metricas) - 1
                          else [""] * len(condiciones), rotation=20, ha="right")
            ax.margins(y=0.25)
            if i == 0:
                ax.set_title(m)
            if j == 0:
                ax.set_ylabel(titulo, fontsize=6.5)
    censura = int(d.entrega_censurada.sum()) if "entrega_censurada" in d.columns else 0
    nota = (f"corridas sin entrega (turno censurado, excluidas del último panel): {censura}"
            if censura else "")
    fig.suptitle("E1 · medidas secundarias declaradas: media por celda ± IC95 sobre corridas\n" + nota,
                 x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(destino)
    plt.close(fig)
    return Path(destino)


# --------------------------------------------------------------------------- figura 4

def figura_e1_potencia(potencia_csv, destino, sesi=0.02) -> Path:
    """Potencia alcanzada y n por celda necesaria para detectar δ bits/token."""
    estilo()
    p = pd.read_csv(potencia_csv)
    modelos = sorted(set(p.model))
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.2), gridspec_kw={"width_ratios": [1.25, 1]})
    ax = axes[0]
    ns = np.arange(5, 401)
    colores_modelo = dict(zip(modelos, ["#0b6e8a", "#a16207", "#7c3aed", "#16a34a"]))
    for m in modelos:
        sp = float(p[p.model == m].de_agrupada.median())
        pot = []
        for n in ns:
            gl, ee = 2 * n - 2, sp * math.sqrt(2 / n)
            tc = stats.t.ppf(0.975, gl)
            pot.append(stats.nct.sf(tc, gl, sesi / ee) + stats.nct.cdf(-tc, gl, sesi / ee))
        ax.plot(ns, pot, color=colores_modelo[m], label=f"{m} (DE={sp:.3f})")
        n_real = int(p[p.model == m].n_a.median())
        pot_real = float(p[p.model == m].potencia_alcanzada.median())
        ax.scatter([n_real], [pot_real], color=colores_modelo[m], s=22, zorder=3)
        ax.annotate(f"n={n_real}: {pot_real:.2f}", (n_real, pot_real), textcoords="offset points",
                    xytext=(6, -2), fontsize=6, color=colores_modelo[m])
    ax.axhline(0.8, color=GRIS, ls="--", lw=0.8)
    ax.text(ns[-1], 0.81, "0,80", ha="right", fontsize=6, color=GRIS)
    ax.set_xscale("log")
    ax.set_xticks([5, 10, 20, 40, 80, 160, 320], ["5", "10", "20", "40", "80", "160", "320"])
    ax.set_xlabel("corridas por celda")
    ax.set_ylabel(f"potencia para δ = {sesi:.2f} bits/token")
    ax.set_title("a  Potencia frente a corridas por celda")
    ax.legend(loc="upper left")
    ax = axes[1]
    resumen = (p.groupby("model").agg(n_actual=("n_a", "median"),
                                      n_080=("n_por_celda_para_080", "median"),
                                      dmd=("dmd_80_con_n_actual", "median")).reset_index())
    y = np.arange(len(resumen))
    ax.hlines(y, resumen.n_actual, resumen.n_080, color=GRIS, lw=0.8)
    ax.scatter(resumen.n_actual, y, color="black", s=18, label="n realizada", zorder=3)
    ax.scatter(resumen.n_080, y, facecolors="none", edgecolors="black", s=26,
               label="n para potencia 0,80", zorder=3)
    for i, r in resumen.iterrows():
        ax.text(r.n_080, i, f"  {int(r.n_080)}", va="center", fontsize=6)
    ax.set_yticks(y, resumen.model.tolist())
    ax.set_xscale("log")
    marcas = [10, 20, 40, 80, 160, 320, 640]
    ax.set_xticks(marcas, [str(t) for t in marcas], minor=False)
    ax.set_xticks([], minor=True)
    ax.set_xlabel("corridas por celda (escala log)")
    ax.set_title("b  Lo que haría falta para δ declarado")
    ax.legend(loc="lower right")
    fig.suptitle("E1 · potencia: con la dispersión observada por corrida, δ = %.2f bits/token exige "
                 "muchas más corridas de las ejecutadas" % sesi, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(destino)
    plt.close(fig)
    return Path(destino)


# --------------------------------------------------------------------------- todas

def todas(dir_tablas: Path, dir_salida: Path, sesi=0.02) -> list[Path]:
    dir_salida.mkdir(parents=True, exist_ok=True)
    d = dir_tablas / "E1_deltas_por_corrida.csv"
    k = dir_tablas / "E1_contrastes_primario.csv"
    hechas = []
    if d.exists() and k.exists():
        hechas.append(figura_e1_principal(d, k, dir_salida / "E1_principal.png", sesi=sesi))
        hechas.append(figura_e1_prediccion(dir_tablas / "E1_prediccion.csv", k,
                                           dir_salida / "E1_prediccion.png"))
        hechas.append(figura_e1_secundarios(d, dir_tablas / "E1_contrastes_secundarios.csv",
                                            dir_salida / "E1_secundarios.png"))
    pot = dir_tablas / "E1_potencia.csv"
    if pot.exists():
        hechas.append(figura_e1_potencia(pot, dir_salida / "E1_potencia.png", sesi=sesi))
    return hechas


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tablas", type=Path, help="directorio con E1_*.csv (salida de analisis_e1.py)")
    ap.add_argument("--out", type=Path, default=None, help="directorio de figuras")
    ap.add_argument("--sesi", type=float, default=0.02)
    args = ap.parse_args(argv)
    salida = args.out or args.tablas / "figuras"
    for p in todas(args.tablas, salida, sesi=args.sesi):
        print(p)


if __name__ == "__main__":
    main()
