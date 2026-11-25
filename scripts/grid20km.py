"""Palm area that was forest, on a 20 km grid, and the four detail cells (PREREGISTRATION.md, detail areas).

Grid: 20 km cells in EPSG:9377 (MAGNA-SIRGAS / Origen-Nacional), built locally with pyproj, only where the 0.5 degree cells of tiled.py found palm,
palm outside the Colombia outline masked out. Rule fixed in the preregistration: among cells with at least 500 ha of palm
planted 2001 to 2018, the two with the most palm area where both products say forest, and the two with the largest
disagreement in hectares.
USE: python scripts/grid20km.py --project P   ->  data/grid20km.csv, data/detail_cells.json
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ee
import pandas as pd
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample import layers  # noqa: E402
from tiled import STEP, retry  # noqa: E402
from wall_to_wall import forest_images  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"
MIN_PALM_HA, CELL_M, BATCH = 500, 20000, 40
BANDS = ["palm_ha", "hansen_ha", "tmf_ha", "both_ha", "disagree_ha"]


def local_grid(halves, n=10):
    """20 km cells of EPSG:9377 that touch the 0.5 degree cells with palm, as lon/lat rings densified with n points
    per side. Neighbouring cells share the same vertices, so the cells tile the plane with no gap or overlap."""
    fwd = Transformer.from_crs(4326, 9377, always_xy=True); back = Transformer.from_crs(9377, 4326, always_xy=True)
    keys = set()
    for x, y in zip(halves.lon, halves.lat):
        xs, ys = fwd.transform([x + STEP * i / n for i in range(n + 1)] * (n + 1),
                               [y + STEP * j / n for j in range(n + 1) for _ in range(n + 1)])
        for i in range(int(min(xs) // CELL_M), int(max(xs) // CELL_M) + 1):
            for j in range(int(min(ys) // CELL_M), int(max(ys) // CELL_M) + 1):
                keys.add((i, j))
    out = []
    for i, j in sorted(keys):
        x0, y0 = i * CELL_M, j * CELL_M; k = [q / n for q in range(n)]
        ex = [(x0 + CELL_M * q, y0) for q in k] + [(x0 + CELL_M, y0 + CELL_M * q) for q in k] +              [(x0 + CELL_M * (1 - q), y0 + CELL_M) for q in k] + [(x0, y0 + CELL_M * (1 - q)) for q in k]
        lon, lat = back.transform([e[0] for e in ex], [e[1] for e in ex])
        ring = [[a, b] for a, b in zip(lon, lat)] + [[lon[0], lat[0]]]
        cx, cy = back.transform(x0 + CELL_M / 2, y0 + CELL_M / 2)
        out.append(dict(cell_id=f"E{x0 // 1000}_N{y0 // 1000}", ring=ring, lon=cx, lat=cy,
                        bbox=[min(lon), min(lat), max(lon), max(lat)]))
    return out


def main():
    a = argparse.ArgumentParser(); a.add_argument("--project", required=True); a.add_argument("--workers", type=int, default=8)
    a = a.parse_args(); ee.Initialize(project=a.project)
    img, colombia, proj = layers()
    inside = ee.Image.constant(1).clip(colombia.geometry()).mask().gt(0)   # Colombia as a raster mask
    palm = img.select("stratum").mask().gt(0).And(inside)
    h, t = forest_images(img)
    area = ee.Image.pixelArea().divide(1e4)
    stack = (area.rename("palm_ha").addBands(area.updateMask(h).rename("hansen_ha"))
             .addBands(area.updateMask(t).rename("tmf_ha")).addBands(area.updateMask(h.And(t)).rename("both_ha"))
             .addBands(area.updateMask(h.neq(t)).rename("disagree_ha"))).updateMask(palm)

    cells = local_grid(pd.read_csv(DATA / "cells_w2w.csv").query("palm_px > 0"))
    print(len(cells), "cells of 20 km over the palm area")

    def run(i):
        fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Polygon([c["ring"]], None, False), {"cell_id": c["cell_id"]})
                                   for c in cells[i:i + BATCH]])
        r = stack.reduceRegions(fc, ee.Reducer.sum(), crs=proj, tileScale=4)
        return [x["properties"] for x in retry(lambda: r.getInfo()["features"])]
    with ThreadPoolExecutor(a.workers) as ex:
        rows = [p for part in ex.map(run, range(0, len(cells), BATCH)) for p in part]
    meta = {c["cell_id"]: c for c in cells}
    for r in rows:
        r.update(lon=meta[r["cell_id"]]["lon"], lat=meta[r["cell_id"]]["lat"], bbox=meta[r["cell_id"]]["bbox"])
    G = pd.DataFrame(rows)
    for b in BANDS:
        G[b] = G[b].fillna(0)
    G = G[G.palm_ha > 0].sort_values("palm_ha", ascending=False).reset_index(drop=True)
    G.drop(columns=["bbox"]).round(4).to_csv(DATA / "grid20km.csv", index=False)

    tot = G[BANDS].sum(); w = json.loads((DATA / "wall_to_wall.json").read_text())
    print("check, grid total vs wall-to-wall (ha):", {b: (round(tot[b], 1), w[b]) for b in BANDS})
    E = G[G.palm_ha >= MIN_PALM_HA]
    pick = {"most_both": E.nlargest(2, "both_ha"), "largest_disagreement": E.nlargest(2, "disagree_ha")}
    out = {k: [dict(cell_id=r.cell_id, lon=round(r.lon, 4), lat=round(r.lat, 4), bbox=r.bbox,
                    **{b: round(getattr(r, b), 1) for b in BANDS}) for r in v.itertuples()] for k, v in pick.items()}
    out["eligible_cells"] = int(len(E)); out["cells_with_palm"] = int(len(G))
    (DATA / "detail_cells.json").write_text(json.dumps(out, indent=1))
    print("eligible cells (>= %d ha palm):" % MIN_PALM_HA, len(E), "of", len(G))
    for k, v in pick.items():
        print(k); print(v[["cell_id", "lon", "lat"] + BANDS].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
