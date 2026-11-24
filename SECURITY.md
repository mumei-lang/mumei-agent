# Security Policy

## Supported Versions

The project is pre-1.0. Security fixes are applied to the `develop` branch and carried into the next release tag.

## Reporting a Vulnerability

Please do **not** open a public GitHub issue for security vulnerabilities.

Report vulnerabilities privately via [GitHub Security Advisories](https://github.com/mumei-lang/mumei-agent/security/advisories/new) ("Report a vulnerability"). If private vulnerability reporting is not yet enabled on this repository, contact the maintainer directly through the email on their GitHub profile instead of opening a public issue.

Please include:

- A description of the issue and its potential impact
- Steps to reproduce or a proof of concept
- Affected versions/commits, if known

We aim to acknowledge reports within 7 days and will coordinate disclosure timing with the reporter.

## Scope Notes

- The agent invokes external tools (mumei binary, LLM providers, MCP clients) and writes reports/logs; credential leaks into any output surface are security issues — handling rules live in [`AGENTS.md`](AGENTS.md).
- Audit/forge flows execute or evaluate untrusted source files; path traversal outside the checkout, or execution beyond the declared sandbox/timeout boundaries, is in scope.
- MCP tools and LLM prompts are untrusted-input boundaries: prompt-injection paths that lead to reading credentials, exfiltrating files, or bypassing verification are in scope.
