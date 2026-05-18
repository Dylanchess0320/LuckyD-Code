"""Security review skill — pattern-based static analysis of pending git changes."""

import re
import subprocess
from dataclasses import dataclass

__all__ = ["security_review", "SecurityFinding"]


@dataclass
class SecurityFinding:
    severity: str   # "HIGH" | "MEDIUM" | "LOW"
    pattern: str    # human-readable pattern name
    line: str       # the offending line (stripped)
    context: str    # filename / hunk context


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# (pattern_name, compiled_regex, severity)
_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    # Secrets / credentials
    ("Hardcoded API key / token",
     re.compile(r'(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*=\s*["\'][^"\']{8,}["\']'),
     "HIGH"),
    ("sk- style key",
     re.compile(r'\bsk-[A-Za-z0-9]{20,}\b'),
     "HIGH"),
    ("Hardcoded password",
     re.compile(r'(?i)(password|passwd|pwd)\s*=\s*["\'][^"\']{4,}["\']'),
     "HIGH"),

    # Dangerous execution
    ("eval() call",
     re.compile(r'\beval\s*\('),
     "HIGH"),
    ("exec() call",
     re.compile(r'\bexec\s*\('),
     "HIGH"),
    ("os.system() call",
     re.compile(r'\bos\.system\s*\('),
     "HIGH"),
    ("shell=True in subprocess",
     re.compile(r'\bsubprocess\b.*\bshell\s*=\s*True'),
     "HIGH"),
    ("pickle.loads / pickle.load",
     re.compile(r'\bpickle\.(loads?)\s*\('),
     "MEDIUM"),

    # Path safety
    ("Path traversal pattern",
     re.compile(r'\.\./'),
     "MEDIUM"),
    ("Absolute path hardcoded",
     re.compile(r'(?<![#"\'])(/etc/|/usr/|/root/|C:\\\\Windows\\\\)'),
     "LOW"),

    # Network / injection
    ("SQL string interpolation",
     re.compile(r'(?i)(execute|cursor\.execute)\s*\(\s*f?["\'].*%[s|d]|.*\.format\('),
     "HIGH"),
    ("Insecure HTTP URL hardcoded",
     re.compile(r'http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)'),
     "LOW"),

    # Crypto / randomness
    ("Weak random (not secrets/os.urandom)",
     re.compile(r'\brandom\.(random|randint|choice|shuffle)\s*\('),
     "LOW"),
    ("MD5 hash usage",
     re.compile(r'\bhashlib\.md5\s*\('),
     "LOW"),
]


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _analyse_diff(diff: str) -> list[SecurityFinding]:
    """Scan added lines in a unified diff for security patterns."""
    findings: list[SecurityFinding] = []
    current_file = ""

    for raw_line in diff.splitlines():
        # Track which file we're in
        if raw_line.startswith("+++ "):
            current_file = raw_line[4:].strip()
            if current_file.startswith("b/"):
                current_file = current_file[2:]
            continue

        # Only scan added lines (skip diff metadata and removed lines)
        if not raw_line.startswith("+"):
            continue
        line = raw_line[1:]  # strip leading '+'

        # Skip blank lines and comments
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        for name, pattern, severity in _PATTERNS:
            if pattern.search(line):
                findings.append(SecurityFinding(
                    severity=severity,
                    pattern=name,
                    line=stripped[:120],
                    context=current_file,
                ))

    return findings


def _format_findings(findings: list[SecurityFinding]) -> str:
    if not findings:
        return "✅ No security patterns detected in the diff."

    # Sort by severity
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    findings = sorted(findings, key=lambda f: order.get(f.severity, 9))

    high = [f for f in findings if f.severity == "HIGH"]
    medium = [f for f in findings if f.severity == "MEDIUM"]
    low = [f for f in findings if f.severity == "LOW"]

    lines: list[str] = [
        f"🔐 Security scan: {len(findings)} finding(s) — "
        f"{len(high)} HIGH · {len(medium)} MEDIUM · {len(low)} LOW",
        "",
    ]

    icons = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵"}
    for f in findings:
        lines.append(f"{icons[f.severity]} [{f.severity}] {f.pattern}")
        lines.append(f"   File: {f.context}")
        lines.append(f"   Line: {f.line}")
        lines.append("")

    if high:
        lines.append("⚠️  HIGH findings should be resolved before merging.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def security_review() -> str:
    """Scan pending git changes for common security anti-patterns.

    Checks added lines in `git diff HEAD` (or `--cached` for staged-only)
    for: hardcoded secrets, dangerous execution patterns, path traversal,
    SQL injection, insecure URLs, weak crypto, and more.

    Returns a formatted report string with severity-annotated findings.
    """
    try:
        diff = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True, text=True, timeout=30,
        ).stdout
        if not diff:
            diff = subprocess.run(
                ["git", "diff", "--cached"],
                capture_output=True, text=True, timeout=30,
            ).stdout
        if not diff:
            return "No pending changes to review."

        findings = _analyse_diff(diff)
        return _format_findings(findings)

    except Exception as e:
        return f"Error running security review: {e}"
