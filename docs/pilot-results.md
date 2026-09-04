# Exploratory provider validation

This document records engineering validation performed before the first public
release. It is not a confirmatory comparison of model capability.

## Scope

- Two independent OpenAI-compatible providers were exercised: MiniMax M3 and
  DeepSeek V4.
- The main smoke matrices contained 36 episodes per provider, covering six file
  tasks, two scaffolds, and three execution conditions.
- A separate deterministic 864-cell rehearsal exercised planning, resume,
  evidence-chain, manifest, analysis, and acceptance paths without making model
  claims.

## Observed engineering outcomes

- MiniMax M3: 36 main episodes, 28 verified terminal successes, 105 model calls,
  and 47,517 metered tokens. Two episodes ended in transport or parsing errors.
- DeepSeek V4 Flash: 36 main episodes, 27 verified terminal successes, 64 model
  calls, and 64,671 metered tokens. One episode ended in a parsing error.
- DeepSeek V4 Pro additionally completed one connectivity episode.

Early connection attempts exposed provider-specific reasoning wrappers,
incomplete JSON responses, and output-budget truncation. The adapter and
regression suite were updated to preserve these outcomes without recording API
credentials.

## Interpretation limits

The task set was small, output budgets were adjusted during exploration, and the
design was not preregistered before collection. The counts above must not be used
to rank providers or estimate population effects. A confirmatory study requires
frozen model identifiers, prompts, budgets, exclusions, analysis rules, and a
newly collected balanced matrix.
