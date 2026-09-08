# Public roadmap

This roadmap records intended directions rather than guaranteed delivery dates.
Proposals and independent reproduction reports are welcome in GitHub issues.

## Near term

- Publish a clean-install reproduction template and collect independent reports.
- Add more task families while preserving authoritative state-based grading.
- Harden provider retry classification without hiding authentication, quota, or
  truncation failures.
- Validate citation metadata and the JOSS paper in continuous integration.

## Research validation

- Use the [2026-09-08 source audit](docs/related-work-audit-2026-09-08.md) and
  [development acceptance specification](docs/ambiguous-commit-study-design.md)
  to test commit ambiguity, stale queries, and persistent side effects before
  claiming a contribution or collecting live-model results.
- Follow the [2026-09-07 research audit](docs/research-progress-2026-09-07.md):
  prioritize independent task structures, blinded commit ambiguity, matched
  baselines and cluster-aware analysis before scaling paid runs.
- Freeze and publicly timestamp a confirmatory experimental protocol.
- Run balanced real-provider experiments only after model, prompt, budget,
  exclusion, and analysis policies are fixed.
- Add blinded human scoring where authoritative state alone is insufficient.
- Compare evidence completeness and false-success rates across scaffolds without
  treating exploratory smoke tests as confirmatory evidence.

## Longer term

- Evaluate container or microVM isolation for untrusted execution scenarios.
- Add signed evidence anchors and separation between raw and publication chains.
- Grow maintainership and governance if sustained external contributions emerge.
