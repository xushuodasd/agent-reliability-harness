# Agent Reliability Harness

English | [中文](README.md)

[![tests](https://github.com/xushuodasd/agent-reliability-harness/actions/workflows/tests.yml/badge.svg)](https://github.com/xushuodasd/agent-reliability-harness/actions/workflows/tests.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22306201.svg)](https://doi.org/10.5281/zenodo.22306201)

**Maintainer:** Shuo Xu, Independent Researcher, China; [ORCID 0009-0006-6718-4707](https://orcid.org/0009-0006-6718-4707)
**Contact:** 1402855443@qq.com  
**License:** MIT

Agent Reliability Harness is a research-oriented Python toolkit for auditable
evaluation of tool-using language-model agents. It separates model proposals
from environment execution and scores authoritative final state rather than an
agent's completion claim.

The package supports:

- isolated episodes across file, ledger, software, web-backend, and security
  environments;
- controlled timeout, post-commit timeout, malformed-response, and silent-noop
  fault injection;
- versioned JSON contracts, hash-chained event logs, tail checkpoints, and
  artifact manifests;
- baseline and state-verifying scaffolds with a common action interface;
- deterministic factorial plans, atomic progress, and resumable execution;
- OpenAI-compatible provider preflight, token accounting, JSON-mode fallback,
  and bounded real-provider smoke tests;
- hierarchical design simulation, long-form export, and machine-readable
  GO/REVISE/STOP acceptance gates.

## Installation

Python 3.10 or newer is required. Runtime code uses only the standard library.

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Quick start

Run a deterministic local experiment:

```bash
python -m pilot_harness.cli run \
  --repetitions 3 \
  --fault none \
  --fault timeout_once \
  --output runs/local-smoke
```

Run the zero-cost 864-cell engineering rehearsal:

```bash
python -m pilot_harness.rehearsal \
  --output runs/full-matrix-rehearsal-864
```

Run the acceptance gate in engineering-rehearsal mode:

```bash
python -m pilot_harness.acceptance runs/full-matrix-rehearsal-864 \
  --milestone M4 \
  --output-dir runs/full-matrix-rehearsal-864/acceptance \
  --engineering-rehearsal
```

## Real providers

The provider adapter reads the API key from `AGENT_PILOT_API_KEY`; it does not
write the key to a run manifest. Use a disposable research key and provider-side
spending limits.

```bash
export AGENT_PILOT_API_KEY="set-this-outside-the-repository"
python -m pilot_harness.real_smoke \
  --base-url https://provider.example/v1 \
  --model exact-model-id \
  --scaffold verified \
  --preflight models \
  --max-output-tokens 4096 \
  --max-episode-tokens 16000 \
  --task write-json \
  --fault none \
  --max-episodes 1 \
  --output runs/provider-smoke
```

Real-provider runs are exploratory unless their model versions, prompts,
budgets, task set, exclusions, and analysis plan were frozen before collection.

## Reproducibility and safety

See [Reproducibility](docs/reproducibility.md) for the artifact workflow and
[Security Policy](SECURITY.md) for credential and execution constraints. The
harness is not a hardened sandbox and must not run untrusted model-generated
code or target production systems.

## Citation

Citation metadata is provided in [CITATION.cff](CITATION.cff). Cite all versions
with the concept DOI [`10.5281/zenodo.22306201`](https://doi.org/10.5281/zenodo.22306201),
or cite version `v0.1.2` with [`10.5281/zenodo.22306202`](https://doi.org/10.5281/zenodo.22306202).

## License

Released under the [MIT License](LICENSE).
