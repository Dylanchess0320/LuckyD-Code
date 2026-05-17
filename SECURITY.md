# Security Policy

## ⚠️ Credential Rotation Required

If you **cloned this repo before v1.2.1 (2026-05-02)**, a `DEEPSEEK_API_KEY`
was present in git history. **Rotate it immediately** at
<https://platform.deepseek.com/api_keys>.

The key was removed from tracking in v1.2.1 (`git rm --cached .env`). The
`.gitignore` rule for `.env` already existed but had no effect while the file
was being tracked. All copies of this repo cloned before that release should
be assumed to have the old key in `git log`.

---

## 🔑 Key Rotation Runbook

If a secret is exposed (API key, token, password), follow these steps **immediately**:

1. **Revoke the key** at the provider dashboard before doing anything else.
   - DeepSeek: <https://platform.deepseek.com/api_keys>
   - OpenAI: <https://platform.openai.com/api-keys>
   - Groq, Together, etc.: the respective provider dashboard

2. **Find the exposure point** — check git history, CI logs, and any shared pastes:
   ```bash
   git log -p --all -S 'sk-' -- .env
   git log -p --all --grep='API' --diff-filter=A
   ```

3. **Remove from git history** if committed (choose one):
   ```bash
   # Option A — BFG Repo Cleaner (recommended for large repos)
   bfg --replace-text secrets.txt

   # Option B — git filter-repo
   git filter-repo --path .env --invert-paths

   # After either: force-push ALL branches
   git push origin --force --all
   git push origin --force --tags
   ```

4. **Rotate all related credentials** — if one secret leaked, assume any secret that
   co-existed in the same env file or CI config is compromised too.

5. **Notify affected parties** — if the repo is public or the key had write access,
   open a private advisory (see Reporting a Vulnerability below).

6. **Audit for misuse** — check provider usage dashboards for unexpected API calls
   in the window between when the key was committed and when it was revoked.

7. **Issue a new release** — bump the patch version, add a CHANGELOG entry, and
   tag the commit so consumers know to pull the clean version.

---

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.2.x   | ✅ Yes     |
| 1.1.x   | ⚠️ Critical fixes only |
| 1.0.x   | ❌ No      |
| < 1.0   | ❌ No      |

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, report them privately:

1. Go to the [Security tab](https://github.com/Dylanchess0320/LuckyD-Code/security/advisories/new) and open a private advisory, **or**
2. Email the maintainer directly (see GitHub profile for contact)

### What to include

- A clear description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional but appreciated)

### What to expect

- **Acknowledgement** within 48 hours
- **Status update** within 7 days
- A fix will be prioritised based on severity
- You'll be credited in the release notes unless you prefer to remain anonymous

## Scope

The following are **in scope**:

- API key leakage or exposure through any code path
- Path traversal in file tools (Read, Write, Glob, etc.)
- Command injection via the Bash tool or shell detection
- Auth bypass in the Web UI bearer token system
- Sandbox escape from the Docker execution environment

The following are **out of scope**:

- Vulnerabilities in third-party dependencies (report to them directly)
- Issues requiring physical access to the machine
- Social engineering attacks
