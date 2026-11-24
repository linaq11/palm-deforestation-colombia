"""Wall-to-wall version of the rules in Earth Engine (PREREGISTRATION.md item 4): area of palm, and of palm that was forest
for Hansen, TMF and both, over mainland Colombia. Used for the maps and as a check: the shares must fall inside the
sample intervals.
USE: python scripts/wall_to_wall.py --project P --export    (starts the task)
     python scripts/wall_to_wall.py --project P             (reads the result)
"""
import argparse
import json
import sys
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample import layers  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def forest_images(img):
    y = img.select("planting_year"); limit = y.add(2)
    ly = img.select("lossyear")
    hansen = img.select("treecover2000").gte(30).And(ly.gt(0)).And(ly.add(2000).lte(limit))
    forest2000 = img.select("Dec2000").eq(1).Or(img.select("Dec2000").eq(2))
    defo = ee.Image(0)
    for yr in range(2001, 2021):
        defo = defo.Or(img.select(f"Dec{yr}").eq(3).And(limit.gte(yr)))
    tmf = forest2000.And(defo)
    # masked inputs count as "not forest" so that every palm pixel lands in exactly one cell of the 2 x 2 table
    return hansen.unmask(0).rename("hansen"), tmf.unmask(0).rename("tmf")


def main():
    a = argparse.ArgumentParser(); a.add_argument("--project", required=True); a.add_argument("--export", action="store_true")
    a = a.parse_args(); ee.Initialize(project=a.project)
    asset = f"projects/{a.project}/assets/palm_forest_wall_to_wall"
    if a.export:
        img, colombia, proj = layers()
        h, t = forest_images(img)
        palm = img.select("stratum").gt(0)
        area = ee.Image.pixelArea().divide(1e4)
        stack = (area.updateMask(palm).rename("palm_ha")
                 .addBands(area.updateMask(palm.And(h)).rename("hansen_ha"))
                 .addBands(area.updateMask(palm.And(t)).rename("tmf_ha"))
                 .addBands(area.updateMask(palm.And(h).And(t)).rename("both_ha"))
                 .addBands(area.updateMask(palm.And(h.neq(t))).rename("disagree_ha")))
        s = stack.reduceRegion(ee.Reducer.sum(), colombia.geometry(), crs=proj, maxPixels=1e13, tileScale=16)
        t_ = ee.batch.Export.table.toAsset(ee.FeatureCollection([ee.Feature(None, s)]), "palm_forest_wall_to_wall", asset)
        t_.start(); print("export started", t_.id, "->", asset); return
    p = ee.FeatureCollection(asset).first().toDictionary().getInfo()
    out = {k: round(v, 1) for k, v in p.items()}
    out.update({f"share_{k[:-3]}": round(p[k] / p["palm_ha"], 4) for k in ("hansen_ha", "tmf_ha", "both_ha", "disagree_ha")})
    (ROOT / "data" / "wall_to_wall.json").write_text(json.dumps(out, indent=1)); print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
