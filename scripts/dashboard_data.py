"""Everything the dashboard in docs/ reads. Aggregates and imagery only: no farm boundaries, owners or companies.

  docs/data/summary.json   preregistered results, department table, shares by planting year (sample, bootstrap 95 %)
  docs/data/grid.json      20 km cells with palm: corner ring and hectares per measure; Colombia outline
  docs/data/cell_<id>.png  per detail cell, 30 m pixels packed in RGBA:
                             R = planting year - 2000 (0 = no palm 2001-2018)
                             G = bit 1 Hansen forest, bit 2 TMF forest, bit 4 smallholder, bit 8 tree cover 2000 >= 30
                             B = Hansen loss year - 2000 (0 = no loss),  A = 255
  docs/data/cell_<id>_2000.jpg, _2023.jpg   Landsat false colour (SWIR1, NIR, red) medians, 1999-2001 and 2022-2024
USE: python scripts/dashboard_data.py --project P
"""
import argparse
import io
import json
import sys
from pathlib import Path

import ee
import numpy as np
import pandas as pd
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "src"))
from analyze import flags  # noqa: E402
from grid20km import local_grid  # noqa: E402
from sample import layers  # noqa: E402
from wall_to_wall import forest_images  # noqa: E402

DATA, OUT = ROOT / "data", ROOT / "docs" / "data"
RES = 0.00025                       # Hansen pixel, degrees
B, SEED = 1000, 0


def by_year(d):
    """Share of palm planted in year Y that was forest, per product, with a bootstrap 95 % interval."""
    h, t = flags(d); w = np.cos(np.radians(d.lat.to_numpy())); y = d.planting_year.to_numpy()
    rng = np.random.default_rng(SEED); rows = []
    for yr in range(2001, 2019):
        m = y == yr; hh, tt, ww = h[m], t[m], w[m]; n = int(m.sum())
        est = lambda i: ((ww[i] * hh[i]).sum() / ww[i].sum(), (ww[i] * tt[i]).sum() / ww[i].sum())
        e = est(np.arange(n)); reps = np.array([est(rng.integers(0, n, n)) for _ in range(B)])
        lo, hi = np.percentile(reps, [2.5, 97.5], axis=0)
        rows.append(dict(year=yr, n=n, palm_share=round(float(ww.sum() / w.sum()), 4),
                         hansen=round(e[0], 4), hansen_lo=round(lo[0], 4), hansen_hi=round(hi[0], 4),
                         tmf=round(e[1], 4), tmf_lo=round(lo[1], 4), tmf_hi=round(hi[1], 4)))
    return rows


def landsat(bbox, years):
    def l57(i):
        q = i.select("QA_PIXEL"); ok = q.bitwiseAnd(0b11111).eq(0)
        return i.select(["SR_B5", "SR_B4", "SR_B3"], ["s1", "n", "r"]).multiply(2.75e-5).add(-0.2).updateMask(ok)

    def l89(i):
        q = i.select("QA_PIXEL"); ok = q.bitwiseAnd(0b11111).eq(0)
        return i.select(["SR_B6", "SR_B5", "SR_B4"], ["s1", "n", "r"]).multiply(2.75e-5).add(-0.2).updateMask(ok)
    g = ee.Geometry.Rectangle(bbox, None, False); a, b = years
    if a < 2013:
        col = (ee.ImageCollection("LANDSAT/LT05/C02/T1_L2").merge(ee.ImageCollection("LANDSAT/LE07/C02/T1_L2"))
               .filterBounds(g).filterDate(f"{a}-01-01", f"{b}-12-31").map(l57))
    else:
        col = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
               .filterBounds(g).filterDate(f"{a}-01-01", f"{b}-12-31").map(l89))
    return col.median().visualize(min=0.0, max=[0.35, 0.45, 0.2]), col.size()


def main():
    a = argparse.ArgumentParser(); a.add_argument("--project", required=True)
    a = a.parse_args(); ee.Initialize(project=a.project); OUT.mkdir(parents=True, exist_ok=True)

    # summary
    R = pd.read_csv(DATA / "results.csv"); Dp = pd.read_csv(DATA / "results_department.csv")
    w2w = json.loads((DATA / "wall_to_wall.json").read_text())
    d = pd.read_csv(DATA / "sample.csv")
    summary = dict(results=R.round(6).to_dict("records"), departments=Dp[Dp.n >= 100].to_dict("records"),
                   wall_to_wall=w2w, by_year=by_year(d), detail=json.loads((DATA / "detail_cells.json").read_text()))
    (OUT / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    print("summary.json written")

    # national grid
    G = pd.read_csv(DATA / "grid20km.csv")
    rings = {c["cell_id"]: c for c in local_grid(pd.read_csv(DATA / "cells_w2w.csv").query("palm_px > 0"))}
    cells = [dict(id=r.cell_id, ring=[[round(x, 4), round(y, 4)] for x, y in rings[r.cell_id]["ring"][::10]],
                  palm=round(r.palm_ha), hansen=round(r.hansen_ha), tmf=round(r.tmf_ha), both=round(r.both_ha),
                  disagree=round(r.disagree_ha)) for r in G.itertuples()]
    img, colombia, proj = layers()
    outline = colombia.geometry().simplify(2500).getInfo()
    (OUT / "grid.json").write_text(json.dumps(dict(cells=cells, outline=outline)), encoding="utf-8")
    print("grid.json:", len(cells), "cells")

    # detail cells
    h, t = forest_images(img)
    palm = img.select("stratum").mask().gt(0)
    y = img.select("planting_year").subtract(2000).updateMask(palm).unmask(0)
    g = (h.multiply(1).add(t.multiply(2)).add(img.select("classification").eq(2).multiply(4))).updateMask(palm).unmask(0)
    g = g.add(img.select("treecover2000").gte(30).multiply(8))
    ly = img.select("lossyear").unmask(0)
    packed = y.addBands(g).addBands(ly).toUint8().rename(["r", "g", "b"])
    ids = {c["cell_id"]: c for v in summary["detail"].values() if isinstance(v, list) for c in v}
    for cid, c in ids.items():
        x0, y0, x1, y1 = c["bbox"]
        x0, y0 = np.floor(x0 / RES) * RES, np.floor(y0 / RES) * RES
        nx, ny = int(np.ceil((x1 - x0) / RES)), int(np.ceil((y1 - y0) / RES))
        arr = ee.data.computePixels({"expression": packed, "fileFormat": "NUMPY_NDARRAY",
                                     "grid": {"dimensions": {"width": nx, "height": ny},
                                              "affineTransform": {"scaleX": RES, "shearX": 0, "translateX": x0,
                                                                  "shearY": 0, "scaleY": -RES, "translateY": y0 + ny * RES},
                                              "crsCode": "EPSG:4326"}})
        rgba = np.dstack([arr["r"], arr["g"], arr["b"], np.full(arr["r"].shape, 255, np.uint8)])
        Image.fromarray(rgba, "RGBA").save(OUT / f"cell_{cid}.png", optimize=True)
        box = [x0, y0, x0 + nx * RES, y0 + ny * RES]
        c["box"] = box; c["px"] = [nx, ny]
        for tag, yrs in (("2000", (1999, 2001)), ("2023", (2022, 2024))):
            vis, n = landsat(box, yrs)
            url = vis.getThumbURL({"region": ee.Geometry.Rectangle(box, None, False), "dimensions": f"{nx}x{ny}",
                                   "format": "jpg", "crs": "EPSG:4326"})
            im = Image.open(io.BytesIO(requests.get(url, timeout=300).content)).convert("RGB")
            im.save(OUT / f"cell_{cid}_{tag}.jpg", quality=82)
            c[f"scenes_{tag}"] = n.getInfo()
        print(cid, "pixels", nx, "x", ny, "palm px", int((arr["r"] > 0).sum()),
              "scenes", c["scenes_2000"], c["scenes_2023"])
    summary["cells"] = ids
    (OUT / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
