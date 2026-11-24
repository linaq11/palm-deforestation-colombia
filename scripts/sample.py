"""Simple random sample of 20,000 oil palm pixels (planted 2001-2018) in mainland Colombia, on the Hansen 30 m grid.

PREREGISTRATION.md, items 2 and 4. Writes data/sample.csv with the raw values; the rules are applied in analyze.py.
USE: python scripts/sample.py --project <earth-engine-project>
"""
import argparse
from pathlib import Path

import ee
import pandas as pd

N, SEED = 20000, 0
TMF_YEARS = [f"Dec{y}" for y in range(2000, 2021)]
OUT = Path(__file__).resolve().parents[1] / "data" / "sample.csv"


def layers():
    colombia = ee.FeatureCollection("USDOS/LSIB_SIMPLE/2017").filter(ee.Filter.eq("country_na", "Colombia"))
    hansen = ee.Image("UMD/hansen/global_forest_change_2025_v1_13")
    proj = hansen.select("lossyear").projection()
    palm = ee.ImageCollection("BIOPAMA/GlobalOilPalm/v1_2").filterBounds(colombia).mosaic()
    cls, year = palm.select("classification"), palm.select("planting_year")
    mask = cls.gte(1).And(cls.lte(2)).And(year.gte(2001)).And(year.lte(2018))
    tmf = ee.ImageCollection("projects/JRC/TMF/v1_2025/AnnualChanges").filterBounds(colombia).mosaic().select(TMF_YEARS)
    dept = (ee.FeatureCollection("FAO/GAUL/2015/level1").filter(ee.Filter.eq("ADM0_NAME", "Colombia"))
            .reduceToImage(["ADM1_CODE"], ee.Reducer.first()).rename("adm1_code"))
    img = (ee.Image.constant(1).rename("stratum").toInt().updateMask(mask)
           .addBands([cls, year, hansen.select(["treecover2000", "lossyear"]), tmf, dept]))
    return img, colombia, proj


def main():
    a = argparse.ArgumentParser(); a.add_argument("--project", required=True)
    a.add_argument("--export", action="store_true", help="start the Earth Engine export task and exit")
    a = a.parse_args()
    ee.Initialize(project=a.project)
    asset = f"projects/{a.project}/assets/palm_forest_sample_seed{SEED}"
    if a.export:
        img, colombia, proj = layers()
        fc = img.stratifiedSample(numPoints=N, classBand="stratum", region=colombia.geometry(), projection=proj,
                                  scale=30, seed=SEED, geometries=True, tileScale=16, dropNulls=False)
        t = ee.batch.Export.table.toAsset(collection=fc, description="palm_forest_sample", assetId=asset)
        t.start(); print("export started", t.id, "->", asset); return
    fc = ee.FeatureCollection(asset)
    rows = []
    for f in fc.getInfo()["features"]:
        p = f["properties"]; lon, lat = f["geometry"]["coordinates"]; p.update(lon=lon, lat=lat); rows.append(p)
    d = pd.DataFrame(rows)
    names = (ee.FeatureCollection("FAO/GAUL/2015/level1").filter(ee.Filter.eq("ADM0_NAME", "Colombia"))
             .aggregate_array("ADM1_CODE").getInfo(),
             ee.FeatureCollection("FAO/GAUL/2015/level1").filter(ee.Filter.eq("ADM0_NAME", "Colombia"))
             .aggregate_array("ADM1_NAME").getInfo())
    d["department"] = d.adm1_code.map(dict(zip(*names)))
    OUT.parent.mkdir(exist_ok=True); d.to_csv(OUT, index=False)
    print("sample", d.shape, "->", OUT)
    print("classification", d.classification.value_counts().to_dict())
    print("planting_year range", d.planting_year.min(), d.planting_year.max())
    print("missing values per column", d.isna().sum()[d.isna().sum() > 0].to_dict())


if __name__ == "__main__":
    main()
