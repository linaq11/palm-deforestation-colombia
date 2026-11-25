"""Same sample and wall-to-wall sums as sample.py and wall_to_wall.py, computed on 0.5 degree cells.

The single-task versions over the whole country timed out in Earth Engine after about two hours. Here each cell is a
small interactive request run in parallel. The design does not change (PREREGISTRATION.md, implementation note):
  1. wall-to-wall sums per cell, added up -> data/wall_to_wall.json and data/cells_w2w.csv
  2. Bernoulli sample of palm pixels with p = 30,000 / total palm pixels, same p in every cell (seed 0)
  3. a simple random sample of exactly 20,000 drawn from the Bernoulli units with numpy (seed 0) -> data/sample.csv
A fixed-size simple random draw from a Bernoulli sample is a simple random sample of the population.
Cells are aligned to the Hansen grid (0.5 deg = 2,000 pixels), so no pixel centre falls on a cell edge.
USE: python scripts/tiled.py --project P
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ee
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample import N, SEED, layers  # noqa: E402
from wall_to_wall import forest_images  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STEP = 0.5
TARGET = 30000          # expected Bernoulli units; 20,000 are then drawn from them
MISSING = -1            # value written where an input band has no data under a palm pixel


def retry(f, tries=4):
    for k in range(tries):
        try:
            return f()
        except Exception as e:  # Earth Engine quota or transient errors
            if k == tries - 1:
                raise
            time.sleep(5 * (k + 1)); print("  retry:", str(e)[:120])


def grid(colombia):
    b = colombia.geometry().bounds().getInfo()["coordinates"][0]
    x0, y0 = np.floor(min(p[0] for p in b) / STEP) * STEP, np.floor(min(p[1] for p in b) / STEP) * STEP
    x1, y1 = np.ceil(max(p[0] for p in b) / STEP) * STEP, np.ceil(max(p[1] for p in b) / STEP) * STEP
    return [(round(x, 2), round(y, 2)) for x in np.arange(x0, x1, STEP) for y in np.arange(y0, y1, STEP)]


def main():
    a = argparse.ArgumentParser(); a.add_argument("--project", required=True); a.add_argument("--workers", type=int, default=8)
    a = a.parse_args(); ee.Initialize(project=a.project); DATA.mkdir(exist_ok=True)
    img, colombia, proj = layers()
    cgeom = colombia.geometry()
    palm = img.select("stratum").mask().gt(0)
    h, t = forest_images(img)
    area = ee.Image.pixelArea().divide(1e4)
    stack = (palm.rename("palm_px")
             .addBands(area.rename("palm_ha"))
             .addBands(area.updateMask(h).rename("hansen_ha"))
             .addBands(area.updateMask(t).rename("tmf_ha"))
             .addBands(area.updateMask(h.And(t)).rename("both_ha"))
             .addBands(area.updateMask(h.neq(t)).rename("disagree_ha"))).updateMask(palm)

    def region(c):
        x, y = c
        return ee.Geometry.Rectangle([x, y, x + STEP, y + STEP], None, False).intersection(cgeom, 1)

    # 1. wall-to-wall, per cell
    cells_csv = DATA / "cells_w2w.csv"
    if cells_csv.exists():
        W = pd.read_csv(cells_csv)
    else:
        cells = grid(colombia); print(len(cells), "cells of", STEP, "deg in the Colombia bounding box")

        def w2w(c):
            s = retry(lambda: stack.reduceRegion(ee.Reducer.sum(), region(c), crs=proj, maxPixels=1e10, tileScale=4).getInfo())
            return dict(lon=c[0], lat=c[1], **{k: (v or 0) for k, v in s.items()})
        with ThreadPoolExecutor(a.workers) as ex:
            W = pd.DataFrame(list(ex.map(w2w, cells)))
        W.to_csv(cells_csv, index=False)
    W = W[W.palm_px > 0].reset_index(drop=True)
    tot = W.drop(columns=["lon", "lat"]).sum()
    out = {k: round(float(v), 1) for k, v in tot.items()}
    out.update({f"share_{k[:-3]}": round(tot[k] / tot.palm_ha, 4) for k in ("hansen_ha", "tmf_ha", "both_ha", "disagree_ha")})
    out["cells_with_palm"] = int(len(W))
    (DATA / "wall_to_wall.json").write_text(json.dumps(out, indent=1)); print(json.dumps(out, indent=1))

    # 2. Bernoulli sample with the same p everywhere
    p = TARGET / tot.palm_px
    print("Bernoulli p =", round(p, 6), "expected units", TARGET)
    rnd = ee.Image.random(SEED).lt(p)
    cand = img.unmask(MISSING).updateMask(palm.And(rnd))

    def bern(c):
        fc = cand.sample(region=region(c), projection=proj, seed=SEED, dropNulls=True, tileScale=4, geometries=True)
        feats = retry(lambda: fc.getInfo()["features"])
        rows = []
        for f in feats:
            r = f["properties"]; r["lon"], r["lat"] = f["geometry"]["coordinates"]; r["cell"] = f"{c[0]}_{c[1]}"; rows.append(r)
        return rows
    with ThreadPoolExecutor(a.workers) as ex:
        parts = list(ex.map(bern, list(zip(W.lon, W.lat))))
    B = pd.DataFrame([r for part in parts for r in part])
    B.to_csv(DATA / "bernoulli.csv", index=False)
    print("Bernoulli units", len(B), "(expected about", TARGET, ")")
    assert len(B) >= N, "fewer Bernoulli units than the sample size"
    per_cell = B.groupby("cell").size().max()
    assert per_cell < 5000, "a cell reached the 5,000-feature getInfo limit; use smaller cells"

    # 3. simple random sample of exactly N
    d = B.sample(n=N, random_state=SEED).reset_index(drop=True)
    gaul = ee.FeatureCollection("FAO/GAUL/2015/level1").filter(ee.Filter.eq("ADM0_NAME", "Colombia"))
    names = dict(zip(gaul.aggregate_array("ADM1_CODE").getInfo(), gaul.aggregate_array("ADM1_NAME").getInfo()))
    d["department"] = d.adm1_code.map(names)
    d.to_csv(DATA / "sample.csv", index=False)
    print("sample", d.shape, "->", DATA / "sample.csv")
    print("classification", d.classification.value_counts().to_dict())
    print("planting_year range", d.planting_year.min(), d.planting_year.max())
    print("cells per pixel max", int(per_cell))
    print("missing (-1) per column", {k: int(v) for k, v in (d == MISSING).sum().items() if v > 0})
    print("department missing", int(d.department.isna().sum()))


if __name__ == "__main__":
    main()
