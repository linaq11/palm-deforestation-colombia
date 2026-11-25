# Negative tests of the rules

Each line is a deliberate break of `src/palmforest/rules.py`, the tests that failed, and the restore. Run on 2026-11-25 after the boundary cases were added; the rules themselves were not changed and the results do not depend on these tests. The first round of breaks, run on 2026-11-24 before the real run, was not logged.

| Break | Tests that failed |
|---|---|
| `MARGIN = 1` | Hansen loss at Y+2 counts; TMF deforested at Y+2 counts |
| `MARGIN = 3` | Hansen loss at Y+3 does not; TMF deforested at Y+3 does not |
| `tc > threshold` instead of `>=` | tree cover exactly at threshold counts |
| TMF window extended to Y+3 | TMF deforested at Y+3 does not |
| restored | 18 passed |
