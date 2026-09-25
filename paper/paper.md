---
title: "Agent Reliability Harness: Auditable fault-injection experiments for tool-using language-model agents"
tags:
  - large language model agents
  - reliability
  - fault injection
  - software testing
  - reproducibility
authors:
  - name: Shuo Xu
    affiliation: 1
    orcid: 0009-0006-6718-4707
affiliations:
  - name: Independent Researcher, China
    index: 1
date: 25 September 2026
bibliography: paper.bib
---

# Summary

Language-model agents interact with external state through tools, so a plausible
completion message is not sufficient evidence that a task was completed safely
and correctly. Agent Reliability Harness is a dependency-free Python toolkit for
controlled and auditable experiments on tool-using agents. It separates action
proposal from tool execution, injects explicit execution faults, grades
authoritative postconditions, and provides machine-readable episode evidence
through its unified engine. The toolkit is intended for researchers studying
agent reliability, recovery, and false completion under reproducible task
conditions. Independent measurement of general safety remains future work.

# Statement of need

Interactive agent evaluations increasingly use stateful websites, repositories,
and tool environments [@react; @swebench]. A final success rate, however, can
hide whether the agent used an invalid trajectory, trusted a false tool receipt,
created duplicate side effects, or stopped after an infrastructure failure.
Policy-aware and adversarial benchmarks further show that task completion and
safe behavior are distinct outcomes [@taubench; @agentdojo]. Researchers need a
small experimental substrate that makes these distinctions testable without
requiring a production service or a specific model vendor.

Agent Reliability Harness addresses this need with five design commitments:

1. Agents propose actions through a provider interface and never mutate the
   environment directly.
2. Tool calls pass through an execution layer that can inject faults with an
   explicit receipt describing whether external state changed.
3. Scoring reads authoritative state independently of the agent's claim.
4. The unified episode engine records versioned events, a hash-chain checkpoint,
   reset and injection receipts, verification and score records, and a manifest
   for completed episodes.
5. Factorial plans and atomic progress files support deterministic ordering,
   interruption recovery, and independent acceptance checks.

# State of the field

ReAct established a general pattern for interleaving language-model reasoning
and external actions [@react]. SWE-bench evaluates agents against real software
issues [@swebench], while tau-bench adds policy-constrained interactions and
AgentDojo studies prompt-injection attacks in tool-integrated agents
[@taubench; @agentdojo]. These systems provide important tasks and threat
models. Agent Reliability Harness is complementary: it focuses on controlled
execution faults, explicit side-effect truth, independent state verification,
and portable evidence artifacts that can be applied consistently across model
providers and synthetic task environments.

# Software design

The included task catalog spans deterministic file operations, idempotent ledger
updates, restricted software configuration repair, optimistic web-backend state,
and security-policy scenarios. Fault modes include timeout before execution,
timeout after durable commit, malformed observation, and silent no-op. Baseline
and verifying scaffolds share an action interface; the latter prompts the model
to check state and attempt bounded recovery, without guaranteeing that it will
do so. A separate OpenAI-compatible adapter supports model-list lookup or a
minimal chat preflight, JSON-response compatibility handling, and post-response
token and cost estimates. Per-episode checks stop later action requests after
missing or excessive usage; they do not cap the current request. A persistent
budget ledger and single-attempt transport bridge exist as opt-in components,
but are not yet wired into every CLI request path.

The analysis layer exports episode-level data and stratified outcomes. A
hierarchical simulation estimates design sensitivity without treating episodes
as independent observations. The acceptance command independently recomputes
schema validity, event-chain integrity, manifest hashes, reset stability,
injection eligibility, false-success indicators, policy-violation flags, and
missing data. It returns a machine-readable `GO`, `REVISE`, or `STOP` decision.
An engineering `GO` does not establish general safety or publication readiness;
deterministic rehearsals are not model evidence.

# Quality and research use

The software includes automated tests for environment contracts, fault truth,
recovery, path containment, tamper and truncation detection, schema validation,
planning, resume semantics, provider handling, analysis, and security policy.
The runtime uses the Python standard library; versioned schemas are distributed
inside the installable package. Reproducibility guidance distinguishes
engineering fixtures from real-model data and requires model, prompt, provider,
budget, plan-hash, and environment freezing before confirmatory collection.

The harness is not a hardened sandbox and must not execute untrusted generated
code or target production systems. It is best used as an experimental control
plane for bounded synthetic environments and sanitized provider traces.

# Research impact statement

The [later engineering summary of early runs](https://github.com/xushuodasd/agent-reliability-harness/blob/85ea06c/docs/pilot-results.md) reports a
deterministic 864-cell rehearsal and 72 exploratory episodes across two provider
services. The original untracked local run artifacts were not recovered after a
September 2026 repository deletion; the retained summary cannot substitute for
rechecking individual episodes. This draft therefore makes no empirical claim
about model ranking, effect size, or broad research impact from those historical
counts. The reproducible code checks, any newly collected study data, and
independent adoption require separate assessment.

# AI usage disclosure

OpenAI Codex assisted with
research planning, software implementation, automated-test development,
documentation, and drafting and language editing of this paper. MiniMax M3 and
DeepSeek V4 appear in the historical exploratory provider-test record. Before
submission, the author must review generated material, verify public artifacts,
claims and citations, and approve the final manuscript and disclosure. This
draft does not assert that those checks are complete.

# Software availability

The source code is publicly available at
[github.com/xushuodasd/agent-reliability-harness](https://github.com/xushuodasd/agent-reliability-harness).
All archived versions are identified by the Zenodo concept DOI
[`10.5281/zenodo.22306201`](https://doi.org/10.5281/zenodo.22306201); the
archived `v0.1.2` release is identified by
[`10.5281/zenodo.22306202`](https://doi.org/10.5281/zenodo.22306202).
Development on the main branch has continued beyond that tag; the cited frozen
software version and manuscript claims must be aligned before submission.

# Acknowledgements

The author received no specific funding for this work.

# References
