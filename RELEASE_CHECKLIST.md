# Release and Submission Checklist

## Completed locally

- [x] MIT license added.
- [x] Author and citation metadata added.
- [x] English and Chinese documentation added.
- [x] Security, contribution, and reproducibility policies added.
- [x] JSON schemas included inside the installable wheel.
- [x] Automated tests pass.
- [x] Wheel builds and installs in an isolated directory.
- [x] An installed-wheel experiment completes outside the source tree.
- [x] JOSS English paper and Chinese companion draft added.
- [x] Known API-key patterns absent from publication candidates.

## Author actions required before public release

- [x] Register an ORCID and add it to `AUTHORS.md`, `CITATION.cff`, and
  `paper/paper.md`.
- [x] Create a GitHub account or choose another public Git host.
- [x] Create a public repository named `agent-reliability-harness`.
- [x] Push the prepared local Git history.
- [x] Confirm that GitHub Actions passes on Linux and Windows.
- [x] Add repository and issue-tracker URLs to `pyproject.toml` and
  `CITATION.cff`.
- [x] Create release `v0.1.1` on GitHub.
- [x] Create DOI-backed release `v0.1.2` after enabling Zenodo archiving.
- [x] Add the release DOI to `CITATION.cff` and the manuscript materials.

## JOSS readiness gates

- [ ] The public repository shows sustained development history rather than a
  single generated upload.
- [ ] At least one external user or independent reproduction is documented.
- [ ] Installation and example commands work from a clean public checkout.
- [ ] The software is feature-complete for the claimed research use.
- [ ] The author has read and accepted JOSS's current submission requirements.
- [ ] All references and factual claims have been checked against primary
  sources.

Do not submit until every unchecked item that applies to the selected venue is
resolved.
