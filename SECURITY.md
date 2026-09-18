# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a vulnerability that could expose API keys, Feishu webhooks, browser profiles, recordings, or transcripts. Contact the repository maintainer privately through the security contact configured on the GitHub repository.

Include the affected version, reproduction steps, expected impact, and any suggested mitigation. Remove credentials and personal data from screenshots and logs before sharing them.

## Protecting local data

- Keep `.env`, `config/anchors.json`, `browser_profile/`, `recordings/`, `transcripts/`, and `logs/` out of Git.
- Rotate a credential immediately if it is committed or pasted into an issue.
- Review generated logs and transcripts before sharing them because they may contain personal or copyrighted content.
- Use a dedicated, least-privilege Feishu bot webhook where possible.
