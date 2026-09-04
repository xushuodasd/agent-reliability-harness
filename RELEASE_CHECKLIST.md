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

- [ ] Register an ORCID and add it to `AUTHORS.md`, `CITATION.cff`, and
  `paper/paper.md`.
- [ ] Create a GitHub account or choose another public Git host.
- [ ] Create a public repository named `agent-reliability-harness`.
- [ ] Push the prepared local Git history.
- [ ] Confirm that GitHub Actions passes on Linux and Windows.
- [ ] Add repository and issue-tracker URLs to `pyproject.toml` and
  `CITATION.cff`.
- [ ] Create release `v0.1.0` and archive it with Zenodo to obtain a DOI.
- [ ] Add the release DOI to `CITATION.cff` and the JOSS submission form.

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
