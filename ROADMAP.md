# Public roadmap

This roadmap records intended directions rather than guaranteed delivery dates.
Proposals and independent reproduction reports are welcome in GitHub issues.

## Near term

- Publish a clean-install reproduction template and collect independent reports.
- Add more task families while preserving authoritative state-based grading.
- Harden provider retry classification without hiding authentication, quota, or
  truncation failures.
  [Response-metering integrity](docs/provider-metering.md) now rejects malformed
  counters and exposes missing totals. A [standalone persistent budget ledger](docs/budget-ledger.md)
  now retains reservations and unknown requests across restart. An explicit
  [single-attempt transport bridge](docs/budgeted-transport.md) adds admission and
  settlement around an injected transport; automatic all-path CLI integration,
  paid-request reconciliation and end-to-end recovery remain pending.
- Validate citation metadata and the JOSS paper in continuous integration.

## Research validation

- Apply the [outcome-only scoring policy](docs/scoring-semantics.md); independently
  measure harm and stop decisions before claiming multidimensional reliability.
  Versioned null safety fields and missing-evidence acceptance gates are implemented;
  general safety measurements remain pending; task-local dispatch effects are separate.
- Adapt the tested [standalone dispatch diagnostic](docs/dispatch-diagnostic.md)
  to unified evidence interfaces without conflating scripted checks with model
  measurements; add structurally distinct tasks before scaling repetitions.
  Shared manifest integration and the [local dispatch runtime/event adapter](docs/unified-dispatch.md)
  are implemented. More independent task structures, fair LLM baselines and
  end-to-end recovery remain pending. See [integrity boundaries](docs/manifest-integrity.md).
  A [read-only semantic bridge](docs/dispatch-evidence-verification.md) now compares
  closed SQLite ledgers with saved scores, exports and the fixed diagnostic plan.
  This does not yet enable measured safety labels in the unified engine.
- A second, [two-stage reservation backend](docs/reservation-diagnostic.md) now
  separates holding capacity from confirmation and retains compensation history.
  Its [unified runtime adapter](docs/unified-reservation.md) now seals local effects
  and cross-checks tool traces. [Matched scripted policies and a sealed development
  comparison](docs/scripted-comparison.md) now share attempt/step caps and preserve
  every planned cell. Matched live-model baselines, paid-budget metering and a
  frozen confirmatory protocol remain pending. Two backend structures
  are not a validated diverse benchmark or independent scientific samples.
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
