# Contributing

Contributions that improve experimental validity, reproducibility, provider
compatibility, schemas, or safety checks are welcome.

1. Open an issue describing the scientific or engineering problem.
2. Create a focused branch and keep changes independent of private services.
3. Add or update deterministic tests.
4. Run `python -m unittest discover -s tests -v` from the repository root.
5. Do not commit API keys, real customer data, provider-private traces, or
   generated `runs/` directories.
6. Submit a pull request describing the changed contract and validation.

By contributing, you agree that your contribution is licensed under the MIT
License. Be respectful and focus review comments on the work.
