"""Shares of palm area that were forest before planting, by product, with bootstrap intervals (PREREGISTRATION.md items 3-5).

Pixels are on a geographic 30 m grid, so each sampled pixel is weighted by cos(latitude) to turn pixel counts into area.
USE: python scripts/analyze.py  ->  data/results.csv, data/results.txt
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from palmforest.rules import TMF_FIRST, TMF_LAST, hansen_forest, tmf_forest  # noqa: E402

B, SEED = 2000, 0
TYPES = {1: "industrial", 2: "smallholder"}


def flags(d, threshold=30):
    tmf = d[[f"Dec{y}" for y in range(TMF_FIRST, TMF_LAST + 1)]].to_numpy().astype(int)
    h = hansen_forest(d.treecover2000.to_numpy(), d.lossyear.to_numpy(), d.planting_year.to_numpy(), threshold)
    t = tmf_forest(tmf, d.planting_year.to_numpy())
    return h, t


def shares(h, t, w):
    w = w / w.sum()
    return {"hansen": (w * h).sum(), "tmf": (w * t).sum(), "both": (w * (h & t)).sum(),
            "disagree": (w * (h ^ t)).sum(), "hansen_only": (w * (h & ~t)).sum(), "tmf_only": (w * (~h & t)).sum()}


def boot(h, t, w, rng):
    est = shares(h, t, w); reps = {k: [] for k in est}
    n = len(h)
    for _ in range(B):
        i = rng.integers(0, n, n)
        for k, v in shares(h[i], t[i], w[i]).items():
            reps[k].append(v)
    return {k: (est[k], *np.percentile(reps[k], [2.5, 97.5])) for k in est}


def main():
    f = ROOT / "data" / "sample.csv"; d = pd.read_csv(f)
    print("read", f, d.shape)
    assert len(d) >= 19000, "sample smaller than expected"
    assert d.planting_year.between(2001, 2018).all() and d.classification.isin([1, 2]).all()
    w = np.cos(np.radians(d.lat.to_numpy()))
    rows = []
    h, t = flags(d)
    groups = [("all", np.ones(len(d), bool))] + [(TYPES[c], d.classification.to_numpy() == c) for c in TYPES]
    for name, m in groups:
        for k, (e, lo, hi) in boot(h[m], t[m], w[m], np.random.default_rng(SEED)).items():
            rows.append(dict(group=name, threshold=30, measure=k, estimate=e, lo95=lo, hi95=hi, n=int(m.sum())))
    for thr in (10, 50):
        hs, ts = flags(d, thr)
        for k, (e, lo, hi) in boot(hs, ts, w, np.random.default_rng(SEED)).items():
            rows.append(dict(group="all", threshold=thr, measure=k, estimate=e, lo95=lo, hi95=hi, n=len(d)))
    R = pd.DataFrame(rows); R.to_csv(ROOT / "data" / "results.csv", index=False)

    dep = []
    for name, g in d.assign(h=h, t=t, w=w).groupby("department"):
        s = shares(g.h.to_numpy(), g.t.to_numpy(), g.w.to_numpy())
        dep.append(dict(department=name, n=len(g), **{k: round(v, 3) for k, v in s.items()}))
    D = pd.DataFrame(dep).sort_values("n", ascending=False); D.to_csv(ROOT / "data" / "results_department.csv", index=False)

    a = R[(R.group == "all") & (R.threshold == 30)].set_index("measure")
    dis = a.loc["disagree"]
    material = dis.estimate >= 0.20 and dis.lo95 > 0.10
    lines = [R[R.threshold == 30].round(3).to_string(index=False), "",
             "Sensitivity, Hansen tree cover threshold:", R[R.threshold != 30].round(3).to_string(index=False), "",
             "By department (n >= 100):", D[D.n >= 100].to_string(index=False), "",
             "Decision rule: disagreement %.3f [%.3f, %.3f] -> %s" % (
                 dis.estimate, dis.lo95, dis.hi95, "products DISAGREE MATERIALLY" if material else "answer does not depend on the product"),
             "Expectation (Hansen > TMF): %s" % ("met" if a.loc["hansen"].estimate > a.loc["tmf"].estimate else "NOT met")]
    (ROOT / "data" / "results.txt").write_text("\n".join(lines), encoding="utf-8"); print("\n".join(lines))


if __name__ == "__main__":
    main()
