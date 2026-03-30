# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest `main` branch | Yes |
| Older commits / tags | No |

Only the latest code on the `main` branch receives security fixes. We do not maintain separate release branches at this time.

## What to Report

- API key exposure or credential leakage in committed code
- Authentication or authorization bypass
- SQL injection, command injection, or other injection vulnerabilities
- Remote code execution
- Dependencies with known CVEs being actively exploited
- Server-side request forgery (SSRF)
- Cross-site scripting (XSS) in the dashboard frontend

## What NOT to Report

- Theoretical issues without a realistic attack vector
- Issues requiring physical access to the host machine
- Vulnerabilities in dependencies that do not affect this project's usage
- Issues already documented as known limitations

## How to Report

**Do NOT open a public GitHub issue for security vulnerabilities.**

Email **zenouz.ai@gmail.com** with the subject line:

```
[SECURITY] <short description of the vulnerability>
```

## What to Include

- A clear description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if known)
- Whether you would like to be credited in release notes

## Response Timeline

| Stage | SLA |
|-------|-----|
| Acknowledgement | Within 48 hours |
| Initial assessment | Within 7 days |
| Fix timeline communicated | Within 14 days |

## Disclosure Policy

We follow **coordinated disclosure**:

1. Reporter contacts us privately via email.
2. We acknowledge receipt, assess severity, and communicate a fix timeline.
3. We develop and test a fix.
4. We release the fix and publish an advisory.
5. Reporter is credited in release notes unless they prefer anonymity.

We will not take legal action against good-faith security researchers who follow this disclosure process.
