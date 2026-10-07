# Security Policy

## Supported versions

The latest release on the `main` branch.

| Version | Supported |
|---|---|
| main (latest) | Yes |

## Reporting a vulnerability

Open a private vulnerability report via
[GitHub Security Advisories](https://github.com/alexolvin/phonebroker/security/advisories/new)
(preferred). Do not file public issues for undisclosed vulnerabilities.

Please include:

- affected version / commit
- reproduction steps
- impact

## Threat model notes

- Tokens live in `/etc/phonebroker/env` (root:phonebroker, 640) and are never
  committed; rotation is `sudo make token PROJECT=<name>`.
- ADB ports (5037, 27183) are restricted by nftables to the `phonebroker` user.
- Owner access uses a dedicated sshd on port 2222 with a forced command and
  pubkey-only authentication.
