"""Synthetic pixels with known histories (PREREGISTRATION.md, negative test of the code)."""
import numpy as np
import pytest

from palmforest.rules import hansen_forest, tmf_forest

N_YEARS = 21  # Dec2000 .. Dec2020


def tmf_row(start, changes=None):
    """Annual TMF classes from Dec2000; changes = {year: class from that year on}."""
    row = np.full(N_YEARS, start)
    for year, cls in sorted((changes or {}).items()):
        row[year - 2000:] = cls
    return row


# name: (treecover2000, lossyear, planting_year, tmf row, expected hansen, expected tmf)
CASES = {
    "forest cleared then planted": (85, 8, 2010, tmf_row(1, {2008: 3, 2012: 4}), True, True),
    "pasture planted": (5, 0, 2010, tmf_row(6), False, False),
    "old palm cleared and replanted": (60, 12, 2013, tmf_row(6), True, False),
    "forest cleared ten years before planting": (
        80, 2, 2012, tmf_row(1, {2002: 3}), True, True),
    "forest cleared after planting + 2": (90, 15, 2010, tmf_row(1, {2015: 3}), False, False),
    "degraded forest cleared within margin": (70, 11, 2010, tmf_row(2, {2011: 3}), True, True),
    "regrowth in 2000, not forest for TMF": (40, 6, 2007, tmf_row(4, {2006: 3}), True, False),
}


@pytest.mark.parametrize("name", CASES)
def test_known_histories(name):
    tc, ly, y, row, exp_h, exp_t = CASES[name]
    assert hansen_forest([tc], [ly], [y])[0] == exp_h, f"Hansen wrong on: {name}"
    assert tmf_forest(row[None, :], [y])[0] == exp_t, f"TMF wrong on: {name}"


def test_vectorised_matches_cases():
    tc, ly, y, rows, eh, et = zip(*CASES.values())
    assert (hansen_forest(tc, ly, y) == np.array(eh)).all()
    assert (tmf_forest(np.vstack(rows), y) == np.array(et)).all()


def test_threshold_sensitivity():
    assert not hansen_forest([20], [5], [2008], threshold=30)[0]
    assert hansen_forest([20], [5], [2008], threshold=10)[0]


def test_unknown_tmf_code_stops():
    with pytest.raises(ValueError):
        tmf_forest(tmf_row(7)[None, :], [2010])
