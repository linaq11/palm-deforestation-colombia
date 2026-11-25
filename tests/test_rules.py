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


# Exact boundaries of the preregistered rules (added after an audit showed MARGIN 1, 3 or 4 and `>` would pass)
BOUNDARY = {
    "Hansen loss at Y+2 counts": (lambda: hansen_forest([80], [12], [2010])[0], True),
    "Hansen loss at Y+3 does not": (lambda: hansen_forest([80], [13], [2010])[0], False),
    "Hansen loss at Y+1 counts": (lambda: hansen_forest([80], [11], [2010])[0], True),
    "tree cover exactly at threshold counts": (lambda: hansen_forest([30], [5], [2008])[0], True),
    "tree cover one below threshold does not": (lambda: hansen_forest([29], [5], [2008])[0], False),
    "TMF deforested at Y+2 counts": (lambda: tmf_forest(tmf_row(1, {2012: 3})[None, :], [2010])[0], True),
    "TMF deforested at Y+3 does not": (lambda: tmf_forest(tmf_row(1, {2013: 3})[None, :], [2010])[0], False),
    "TMF loss in 2001 counts": (lambda: tmf_forest(tmf_row(1, {2001: 3})[None, :], [2001])[0], True),
}


@pytest.mark.parametrize("name", BOUNDARY)
def test_boundaries(name):
    f, expected = BOUNDARY[name]
    assert f() == expected, f"boundary wrong on: {name}"
