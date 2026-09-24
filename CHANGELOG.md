# Changelog

All notable changes to this project will be documented here.

## Unreleased

- Added an opt-in single-attempt transport bridge with durable admission, exact
  nano-USD estimates and fail-closed unknown usage. Offline fixtures only; CLI
  integration, frozen request binding and paid-run recovery remain pending.
- Added a standalone SQLite cumulative budget ledger with integer nano-USD/token
  reservations, idempotent non-authorizing replays, persistent unknown holds,
  recorded overruns, and serialized admission. HTTP integration and live spending
  guarantees are not implemented by this offline state-machine component.
- Hardened response-level episode metering with strict token counters, explicit
  unknown totals and known subtotals, finite budget/pricing inputs and a latch
  against further action requests after budget failure. This is not a persistent
  cumulative budget or a pre-request spending guarantee.
- Added matched scripted retry/query recovery policies across dispatch and
  reservation, with equal attempt/step caps, a saved 36-cell development plan,
  retained failures and read-only batch evidence verification. These remain
  deterministic fixtures over two task structures, not live-model measurements.
- Integrated two-stage reservations with the unified runtime and separate sealed
  effect receipts. Acceptance cross-checks ledger scores, metering and tool events;
  duplicate/unintended reservations or outstanding holds trigger an engineering
  review gate. General safety remains unmeasured, and old dispatch formats remain.
- Added a standalone, local-only two-stage reservation backend with durable
  reserve/confirm/cancel events, blind commit timeouts, persistent attempt budgets,
  idempotency and read-only snapshots. Local scoring retains duplicate history
  and outstanding resource holds; no unified integration or live-model claim.
- Integrated local SQLite dispatch into the unified Provider/event/manifest loop,
  with single-layer blind faults, persistent attempt budgets and a separately
  sealed local-effect receipt. Acceptance recomputes effects and matches tool traces;
  local adverse effects require review while general safety remains NOT_TESTED.
- Added read-only semantic verification for sealed dispatch diagnostics: recompute
  local effect scores from SQLite and compare plan, private export and summary;
  withhold all verified scores on inconsistent, missing or changed evidence.
  No source evidence is repaired or rerun, and unified safety remains unmeasured.
- Versioned unified safety missingness as score v2 / outcome-only policy v2:
  near-miss and realized-harm values are null with NOT_TESTED evidence. Formal
  acceptance requires safety evidence; engineering rehearsal reports missingness.
  Legacy scores remain readable as proxies, and policy violations stay separate.
  Long-form and acceptance exports are v2; invalid measurement claims do not enter
  the measured denominator. Historical score/report schemas remain available.
- Marked unmeasured unified dimensions and research-design quality NOT_TESTED;
  provider failures now have UNKNOWN recovery and step-limit stops are not SAFE_STOP.
  Added an explicit scoring-policy marker, acceptance checks and CSV provenance.
- Hardened manifest verification with schema checks, canonical unique paths and
  optional independently required artifacts. Dispatch diagnostics now seal 98
  required files and offer read-only `--verify` integrity checks.
- Implemented a standalone SQLite dispatch diagnostic with blinded commit faults,
  stale queries, idempotency, independent side-effect scoring, persistent attempt
  budgets, four scripted policies, 48-cell acceptance and 14 regression tests.
- Added a version-pinned related-work source audit and an explicitly unimplemented
  development specification for stale-query and duplicate-side-effect diagnostics.
- Added plan-joined, task-weighted cluster bootstrap analysis with explicit
  missing-run counts and unknown-outcome bounds.
- Blinded pre-execution and post-commit timeout observations; post-commit faults
  now require successful known mutation tools. Added an explicit fault-action
  filter to the unified engine and an offline evidence demo.
- Normalized file-system errors to avoid random host paths in model observations.
- Recorded research overlap, three-template limitations, and staged SCI work.
- Fixed order-dependent engineering pairing: repeated observations require
  explicit matched `pair_id` values; ambiguous, duplicate or mismatched rows fail.
- Reject nonbinary outcomes and empty/self contrasts; exclude unrelated providers
  from contrast reports. Added pairing regression tests and bilingual guidance.
- Added Zenodo concept and version DOI metadata.
- Updated the JOSS paper structure and AI-use disclosure for the 2026 guidance.
- Published sanitized exploratory provider-validation results, governance, and a
  public roadmap.

## 0.1.2 - 2026-09-04

- Enabled GitHub-to-Zenodo software preservation for citable releases.
- Refreshed release metadata for the first DOI-backed archive.

## 0.1.1 - 2026-09-04

- Added the author's verified ORCID to citation, paper, and maintainer metadata.
- Confirmed the public GitHub repository and cross-platform CI workflow.
- Expanded the automated regression suite to 83 tests.

## 0.1.0 - 2026-09-04

- Added deterministic file, ledger, software, web-backend, and security tasks.
- Added state-based grading and controlled fault injection receipts.
- Added versioned JSON schemas, hash-chained event logs, artifact manifests,
  atomic checkpoints, and resumable factorial execution.
- Added OpenAI-compatible provider preflight, usage accounting, JSON response
  compatibility handling, and bounded real-provider smoke tests.
- Added 864-cell engineering rehearsal, hierarchical power simulation,
  acceptance gates, and long-form analysis export.
- Added 82 automated tests covering contracts, recovery, tamper detection,
  security policy, planning, analysis, and provider behavior.
