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
date: 4 September 2026
bibliography: paper.bib
---

# Summary

Language-model agents interact with external state through tools, so a plausible
completion message is not sufficient evidence that a task was completed safely
and correctly. Agent Reliability Harness is a dependency-free Python toolkit for
controlled and auditable experiments on tool-using agents. It separates action
proposal from tool execution, injects explicit execution faults, grades
authoritative postconditions, and seals episode evidence in machine-readable
artifacts. The toolkit is intended for researchers studying agent reliability,
recovery, false completion, and safety under reproducible task conditions.

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
4. Every episode emits versioned events, a hash-chain checkpoint, reset and
   injection receipts, verification and score records, and an artifact manifest.
5. Factorial plans and atomic progress files support deterministic ordering,
   interruption recovery, and independent acceptance checks.

# Functionality

The included task catalog spans deterministic file operations, idempotent ledger
updates, restricted software configuration repair, optimistic web-backend state,
and security-policy scenarios. Fault modes include timeout before execution,
timeout after durable commit, malformed observation, and silent no-op. Baseline
and verifying scaffolds share an action interface, while the latter performs
state checks and bounded recovery. A separate OpenAI-compatible adapter supports
read-only model preflight, JSON-response compatibility handling, token and cost
accounting, and hard per-episode limits.

The analysis layer exports episode-level data and stratified outcomes. A
hierarchical simulation estimates design sensitivity without treating episodes
as independent observations. The acceptance command independently recomputes
schema validity, event-chain integrity, manifest hashes, reset stability,
injection eligibility, false-success indicators, safety violations, and missing
data. It returns a machine-readable `GO`, `REVISE`, or `STOP` decision. A
deterministic 864-cell rehearsal exercises the complete engineering pipeline but
is explicitly marked as non-model evidence.

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

# Software availability

The source code is publicly available at
[github.com/xushuodasd/agent-reliability-harness](https://github.com/xushuodasd/agent-reliability-harness).
All archived versions are identified by the Zenodo concept DOI
[`10.5281/zenodo.22306201`](https://doi.org/10.5281/zenodo.22306201); the
reviewed `v0.1.2` release is archived as
[`10.5281/zenodo.22306202`](https://doi.org/10.5281/zenodo.22306202).

# Acknowledgements

The author received no specific funding for this work.

# References
