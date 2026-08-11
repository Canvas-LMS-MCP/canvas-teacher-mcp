# Security Policy

## Reporting a vulnerability

If you discover a security issue, please **do not** open a public GitHub issue.

Instead, open a private security advisory on the repository's GitHub Security tab, or contact the maintainers directly via the email listed in the repository's settings.

We'll respond within a few days. Once the issue is understood and a fix is available, we'll publish a CVE / advisory if appropriate.

## Scope

This package handles Canvas API credentials (tokens and browser session cookies). Particular care is warranted for:

- Token storage / leakage
- Session file permissions (cookies must not be world-readable)
- Browser-login flows (Playwright session capture)
- Configuration files containing per-school auth data

If you find a way to exfiltrate, replay, or escalate via any of these paths, that's a security issue worth a private report.

## Out of scope

- Generic Python supply-chain concerns unrelated to this package
- Issues only reproducible on unsupported Python versions
- Social engineering of end users
