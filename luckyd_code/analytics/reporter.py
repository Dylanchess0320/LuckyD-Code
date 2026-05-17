"""Report generation for codebase analytics."""

import json
import time
from dataclasses import asdict
from pathlib import Path

from .scanner import scan_project



def _format_size(b):
    for u in ["B", "KB", "MB", "GB"]:
        if b < 1024:
            return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} TB"


class ReportGenerator:
    """Generate reports in multiple formats from scan results."""

    def __init__(self, pm, smells=None):
        self.pm = pm
        self.smells = smells or []

    def terminal(self):
        pm = self.pm
        lines = []
        lines.append("")
        lines.append("=== CODEBASE HEALTH REPORT ===")
        lines.append(f"Project: {pm.root}")
        lines.append(f"Health Score: {pm.health_score}/100")
        lines.append("")
        lines.append("-- Summary --")
        lines.append(f"Source files:     {pm.source_files}")
        lines.append(f"Total lines:      {pm.total_lines:}")
        lines.append(f"Code lines:       {pm.total_code_lines:}")
        lines.append(f"Total size:       {_format_size(pm.total_size_bytes)}")
        lines.append(f"Functions:        {pm.total_functions}")
        lines.append(f"Classes:          {pm.total_classes}")
        lines.append(f"TODOs:            {pm.total_todos}")
        lines.append(f"FIXMEs:           {pm.total_fixmes}")
        lines.append(f"Avg complexity:   {pm.avg_complexity:.1f}")

        if pm.files_by_language:
            lines.append("")
            lines.append("-- Languages --")
            for lang, count in sorted(pm.files_by_language.items(), key=lambda x: -x[1]):
                lines.append(f"  {lang:<12} {count:>4} files")

        top = sorted(pm.complexity_breakdown.items(), key=lambda x: -x[1])[:10]
        if top:
            lines.append("")
            lines.append("-- Top Complexity --")
            for fp, c in top:
                lines.append(f"  {c:>4}  {fp}")

        if pm.todos:
            lines.append("")
            lines.append(f"-- TODOs & FIXMEs ({len(pm.todos)}) --")
            for t in pm.todos[:20]:
                lines.append(f"  [{t['kind']}] {t['file']}:{t['line']}  {t['text'][:80]}")

        if self.smells:
            lines.append("")
            lines.append(f"-- Code Smells ({len(self.smells)}) --")
            for s in self.smells[:30]:
                lines.append(f"  [{s.severity}] {s.kind}: {s.file}:{s.line}")
                if s.message:
                    lines.append(f"    {s.message}")
                if s.suggestion:
                    lines.append(f"    -> {s.suggestion}")

        # Files needing attention
        issues = []
        for fm in pm.file_metrics:
            score = 0
            if fm.lines_code > 300:
                score += 1
            if fm.complexity > 20:
                score += 2
            if fm.todo_count > 5:
                score += 1
            if fm.fixme_count > 2:
                score += 2
            if score > 0:
                issues.append((fm, score))

        if issues:
            issues.sort(key=lambda x: -x[1])
            lines.append("")
            lines.append("-- Files Needing Attention --")
            for fm, score in issues[:10]:
                lines.append(
                    f"  {fm.path}  "
                    f"(lines={fm.lines_code}, complexity={fm.complexity}, "
                    f"todos={fm.todo_count}, fixmes={fm.fixme_count})"
                )

        lines.append("")
        return "\n".join(lines)

    def markdown(self):
        pm = self.pm
        m = []
        m.append("# Codebase Health Report\n")
        m.append(f"**Project:** `{pm.root}`  ")
        m.append(f"**Health Score: {pm.health_score}/100**\n")

        m.append("## Summary\n")
        m.append("| Metric | Value |")
        m.append("|--------|-------|")
        m.append(f"| Source files | {pm.source_files} |")
        m.append(f"| Total lines | {pm.total_lines:} |")
        m.append(f"| Code lines | {pm.total_code_lines:} |")
        m.append(f"| Total size | {_format_size(pm.total_size_bytes)} |")
        m.append(f"| Functions | {pm.total_functions} |")
        m.append(f"| Classes | {pm.total_classes} |")
        m.append(f"| Avg complexity | {pm.avg_complexity:.1f} |")
        m.append(f"| TODOs | {pm.total_todos} |")
        m.append(f"| FIXMEs | {pm.total_fixmes} |")
        m.append("")

        if pm.files_by_language:
            m.append("## Languages\n")
            for lang, cnt in sorted(pm.files_by_language.items(), key=lambda x: -x[1]):
                m.append(f"- **{lang}**: {cnt} files")
            m.append("")

        top = sorted(pm.complexity_breakdown.items(), key=lambda x: -x[1])[:10]
        if top:
            m.append("## Top Complexity\n")
            for fp, c in top:
                m.append(f"- `{fp}`: {c}")
            m.append("")

        if pm.todos:
            m.append(f"## TODOs & FIXMEs ({len(pm.todos)})\n")
            m.append("| Kind | File | Line | Description |")
            m.append("|------|------|------|-------------|")
            for t in pm.todos[:30]:
                m.append(f"| {t['kind']} | `{t['file']}` | {t['line']} | {t['text'][:100]} |")
            m.append("")

        if self.smells:
            m.append(f"## Code Smells ({len(self.smells)})\n")
            for s in self.smells[:30]:
                m.append(f"- **{s.kind}** `{s.file}:{s.line}` ({s.severity}): {s.message}")

        m.append("\n---\n*Report generated by LuckyD Code Analytics*")
        return "\n".join(m)

    def json_report(self):
        return json.dumps({
            "project": self.pm.to_dict(),
            "smells": [asdict(s) for s in self.smells],
            "generated_at": time.time(),
        }, indent=2)

    def html(self):
        md = self.markdown()
        return (
            "<!DOCTYPE html><html><head><meta charset=UTF-8>"
            "<title>Health Report</title>"
            "<style>body{font-family:sans-serif;max-width:900px;margin:auto;padding:2rem}"
            "table{border-collapse:collapse;width:100%}"
            "th,td{border:1px solid #ddd;padding:8px;text-align:left}"
            "th{background:#f5f5f5}code{background:#f0f0f0;padding:2px 6px}</style>"
            "</head><body><pre>" + md + "</pre></body></html>"
        )


def generate_report(pm=None, smells=None, fmt="terminal", output_path=None):
    """Generate a report from metrics. Scans if none provided."""
    if pm is None:
        pm = scan_project()

    if smells is None:
        smells = []

    gen = ReportGenerator(pm, smells)
    report = gen.terminal()

    if fmt == "markdown":
        report = gen.markdown()
    elif fmt == "json":
        report = gen.json_report()
    elif fmt == "html":
        report = gen.html()

    if output_path:
        Path(output_path).write_text(report, encoding="utf-8")
        return f"Report written to {output_path}"

    return report
