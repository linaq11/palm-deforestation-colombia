"""Preregistered rules (PREREGISTRATION.md, item 3): was a palm pixel forest before it was planted?

Everything works on numpy arrays, one element per pixel, so the rules can be tested on synthetic pixels.
"""
import numpy as np

TMF_FIRST, TMF_LAST = 2000, 2020          # Dec2000 .. Dec2020 is enough: Y + 2 <= 2020 because Y <= 2018
TMF_CODES = {1, 2, 3, 4, 5, 6}
MARGIN = 2                                # years after planting, for planting-year error


def hansen_forest(treecover2000, lossyear, planting_year, threshold=30):
    """Hansen: tree cover in 2000 >= threshold and loss between 2001 and Y + 2 (lossyear 1 = 2001, 0 = no loss)."""
    tc = np.asarray(treecover2000); ly = np.asarray(lossyear); y = np.asarray(planting_year)
    year = np.where(ly > 0, 2000 + ly, 0)
    return (tc >= threshold) & (year >= 2001) & (year <= y + MARGIN)


def tmf_forest(tmf, planting_year):
    """TMF: class 1 or 2 in Dec2000 and class 3 in at least one year from Dec2001 to Dec(Y + 2).

    tmf: array (n_pixels, 21) with Dec2000 .. Dec2020 in order.
    """
    tmf = np.asarray(tmf); y = np.asarray(planting_year)
    assert tmf.shape[1] == TMF_LAST - TMF_FIRST + 1, "TMF needs columns Dec2000..Dec2020"
    bad = set(np.unique(tmf).tolist()) - TMF_CODES
    if bad:
        raise ValueError(f"unexpected TMF codes {sorted(bad)}")
    years = np.arange(TMF_FIRST, TMF_LAST + 1)
    forest2000 = np.isin(tmf[:, 0], (1, 2))
    window = (years[None, :] >= 2001) & (years[None, :] <= (y + MARGIN)[:, None])
    deforested = ((tmf == 3) & window).any(axis=1)
    return forest2000 & deforested
