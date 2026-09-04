# Reproducibility Guide

## Scope

This guide reproduces the engineering behavior of Agent Reliability Harness.
It does not reproduce paid provider outputs because model snapshots, service
policies, and stochastic execution can change.

## Environment

- Python 3.10 or newer
- No required third-party runtime dependencies
- A writable local directory
- Network access only for explicitly selected real-provider runs

Record the operating system, Python version, repository commit, task catalog
hash, plan hash, model identifier, provider base URL, access date, decoding
parameters, output limits, and provider pricing before formal data collection.

## Local validation

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m pilot_harness.rehearsal --output runs/full-matrix-rehearsal-864
python -m pilot_harness.acceptance runs/full-matrix-rehearsal-864 \
  --milestone M4 \
  --output-dir runs/full-matrix-rehearsal-864/acceptance \
  --engineering-rehearsal
```

The rehearsal should contain 864 unique completed design cells. Its scientific
decision remains REVISE because deterministic fixtures are not real-model
evidence.

## Artifact interpretation

- `plan.json` freezes design cells and their order.
- `progress.json` is an atomic resumable checkpoint bound to the plan hash.
- Each episode contains versioned events, a tail checkpoint, reset and
  injection receipts, independent verification, scoring, and a manifest.
- `acceptance-report.json` independently recomputes integrity and gate results.
- `analysis-long.csv` is the episode-level analysis table.

Do not remove failed, unknown, unsafe, truncated, rate-limited, or provider-error
episodes after observing results. Apply only exclusions frozen before the run.

## Archival release checklist

1. Run the full automated test suite from a clean checkout.
2. Confirm that no credentials or personal data occur in tracked files.
3. Freeze a version tag and generate source archives.
4. Archive that exact release in Zenodo or another DOI-granting repository.
5. Add the repository URL, release DOI, commit hash, and software version to
   `CITATION.cff` and the paper.
6. Publish only sanitized example runs; never publish private provider traces.
