# Security Policy

## Supported version

The current development release is 0.1.x. Security fixes are applied to the
latest version only.

## Reporting a vulnerability

Do not disclose credentials, private datasets, working exploits, or sensitive
execution traces in a public issue. Contact Shuo Xu at 1402855443@qq.com with a
minimal description, affected version, reproduction conditions, and potential
impact. Remove all API keys and personal information before sending artifacts.

## Credential handling

The real-provider adapter reads credentials only from the
`AGENT_PILOT_API_KEY` process environment variable. Never commit `.env` files,
keys, provider responses containing credentials, or unredacted production
traces. Use disposable test credentials, set cost limits, and rotate a key
immediately after accidental disclosure.

## Scope warning

The harness uses temporary directories and action allowlists for experiments.
It is not a hardened sandbox and must not execute untrusted model-generated
code or connect to production systems.
