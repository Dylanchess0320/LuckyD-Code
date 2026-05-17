"""autoDream — 4-phase idle-time memory consolidation.

Runs during idle periods to clean accumulated session memories:

  Phase 1  Orient      — survey what's stored, build a catalogue
  Phase 2  Gather      — group semantically related memories by keyword overlap
  Phase 3  Consolidate — merge duplicates, resolve contradictions via LLM
  Phase 4  Prune       — archive stale / low-importance entries
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .memory.manager import MemoryManager

_log = logging.getLogger(__name__)

# ── tunables ──────────────────────────────────────────────────────────────────
_MIN_MEMORIES_TO_DREAM = 5    # skip cycle if fewer memories than this exist
_SIMILARITY_THRESHOLD  = 3    # keyword-overlap hits to consider two memories "related"
_GROUP_SIZE_TO_MERGE   = 3    # groups this large or bigger get LLM-merged
_MAX_MERGE_CALLS       = 5    # cap LLM calls per cycle (cost safety)
_CONSOLIDATION_MODEL   = "deepseek-v4-flash"


# ── report ────────────────────────────────────────────────────────────────────

@dataclass
class DreamReport:
    """Summary of what one dream cycle accomplished."""
    phase_1_memories_found: int  = 0
    phase_2_groups_formed: int   = 0
    phase_3_memories_merged: int = 0
    phase_4_memories_pruned: int = 0
    duration_seconds: float      = 0.0
    errors: list[str]            = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"autoDream complete in {self.duration_seconds:.1f}s — "
            f"{self.phase_1_memories_found} surveyed, "
            f"{self.phase_2_groups_formed} groups, "
            f"{self.phase_3_memories_merged} merged, "
            f"{self.phase_4_memories_pruned} pruned."
        )


# ── cycle ─────────────────────────────────────────────────────────────────────

class DreamCycle:
    """Runs a single autoDream consolidation cycle on a MemoryManager.

    All phases are non-destructive in the event of errors: a failed merge
    leaves the originals intact, a failed prune leaves stale memories in place.
    """

    def __init__(self, memory_manager: MemoryManager, config=None):
        self.mm = memory_manager
        self.config = config

    # ── public entry point ────────────────────────────────────────────────────

    def run(self) -> DreamReport:
        """Execute all four phases. Never raises — errors are captured in the report."""
        report = DreamReport()
        t0 = time.monotonic()

        try:
            memories = self._phase_orient(report)
            if len(memories) < _MIN_MEMORIES_TO_DREAM:
                _log.info(
                    "autoDream: only %d memories — skipping (min %d)",
                    len(memories), _MIN_MEMORIES_TO_DREAM,
                )
                report.duration_seconds = time.monotonic() - t0
                return report

            groups = self._phase_gather(memories, report)
            self._phase_consolidate(groups, report)
            self._phase_prune(report)

        except Exception as exc:
            _log.exception("autoDream cycle error: %s", exc)
            report.errors.append(str(exc))

        report.duration_seconds = time.monotonic() - t0
        _log.info("autoDream: %s", report.summary())
        return report

    # ── Phase 1: Orient ───────────────────────────────────────────────────────

    def _phase_orient(self, report: DreamReport) -> list[dict]:
        """Survey all stored memories. Returns the raw list for downstream phases."""
        memories = self.mm.list_memories()
        report.phase_1_memories_found = len(memories)
        _log.debug("autoDream Orient: %d memories found", len(memories))
        return memories

    # ── Phase 2: Gather ───────────────────────────────────────────────────────

    def _phase_gather(
        self, memories: list[dict], report: DreamReport
    ) -> list[list[dict]]:
        """Group memories by keyword-overlap similarity.

        Each memory appears in at most one group. Groups with fewer than 2
        members are dropped (nothing to merge).
        """
        loaded: list[tuple[dict, str]] = []
        for m in memories:
            content = self.mm.load_memory(m["name"], m["type"]) or ""
            loaded.append((m, content.lower()))

        grouped: list[list[dict]] = []
        assigned: set[str] = set()

        for i, (m_i, text_i) in enumerate(loaded):
            key_i = f"{m_i['type']}_{m_i['name']}"
            if key_i in assigned:
                continue

            words_i = set(text_i.split())
            group = [m_i]
            assigned.add(key_i)

            for j, (m_j, text_j) in enumerate(loaded):
                if i == j:
                    continue
                key_j = f"{m_j['type']}_{m_j['name']}"
                if key_j in assigned:
                    continue
                overlap = len(words_i & set(text_j.split()))
                if overlap >= _SIMILARITY_THRESHOLD:
                    group.append(m_j)
                    assigned.add(key_j)

            if len(group) >= 2:
                grouped.append(group)

        report.phase_2_groups_formed = len(grouped)
        _log.debug("autoDream Gather: %d groups formed", len(grouped))
        return grouped

    # ── Phase 3: Consolidate ──────────────────────────────────────────────────

    def _phase_consolidate(
        self, groups: list[list[dict]], report: DreamReport
    ) -> None:
        """Merge large groups via LLM call. Replaces the cluster with one memory."""
        if self.config is None:
            _log.debug("autoDream Consolidate: no config — LLM merge skipped")
            return

        merge_calls = 0
        for group in groups:
            if len(group) < _GROUP_SIZE_TO_MERGE:
                continue
            if merge_calls >= _MAX_MERGE_CALLS:
                _log.debug("autoDream Consolidate: merge cap reached (%d)", _MAX_MERGE_CALLS)
                break

            try:
                merged_name, merged_content = self._llm_merge(group)
                if not merged_content:
                    continue

                # Pick the most common type for the merged memory
                types = [m["type"] for m in group]
                merged_type = max(set(types), key=types.count)

                # Delete originals before saving the merge
                for m in group:
                    try:
                        self.mm.delete_memory(m["name"], m["type"])
                    except Exception:
                        pass

                self.mm.save_memory(
                    merged_name, merged_content,
                    memory_type=merged_type,
                    importance=7,  # merged facts carry higher importance
                )
                report.phase_3_memories_merged += len(group)
                merge_calls += 1

            except Exception as exc:
                _log.warning("autoDream merge failed: %s", exc)
                report.errors.append(f"merge: {exc}")

    def _llm_merge(self, group: list[dict]) -> tuple[str, str]:
        """Ask the LLM to synthesise a cluster of memories into one.

        Returns (merged_name, merged_content).
        """
        from openai import OpenAI
        import httpx

        parts: list[str] = []
        for m in group:
            content = self.mm.load_memory(m["name"], m["type"]) or ""
            parts.append(f"### {m['name']} ({m['type']})\n{content[:600]}")

        prompt = (
            "You are a memory consolidation agent. The memories below are related "
            "and may be redundant or contradictory. Merge them into ONE concise, "
            "authoritative memory. Remove duplicates. Resolve contradictions by "
            "keeping the most recent or most specific fact.\n\n"
            "Respond with ONLY these two lines (no other text):\n"
            "NAME: <short_snake_case_name>\n"
            "CONTENT: <merged content, max 400 characters>\n\n"
            + "\n\n".join(parts)
        )

        client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            http_client=httpx.Client(timeout=20),
        )
        resp = client.chat.completions.create(
            model=_CONSOLIDATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.1,
        )
        raw = (resp.choices[0].message.content or "").strip()

        name = "consolidated"
        content = ""
        for line in raw.splitlines():
            if line.startswith("NAME:"):
                name = line[5:].strip().replace(" ", "_")[:40]
            elif line.startswith("CONTENT:"):
                content = line[8:].strip()

        return name or "consolidated", content

    # ── Phase 4: Prune ────────────────────────────────────────────────────────

    def _phase_prune(self, report: DreamReport) -> None:
        """Archive stale and low-importance memories via MemoryManager.decay()."""
        try:
            archived = self.mm.decay(max_days=30, importance_threshold=3)
            report.phase_4_memories_pruned = archived
            _log.debug("autoDream Prune: %d memories archived", archived)
        except Exception as exc:
            _log.warning("autoDream Prune failed: %s", exc)
            report.errors.append(f"prune: {exc}")


# ── convenience wrapper ───────────────────────────────────────────────────────

def run_dream_cycle(
    memory_manager: MemoryManager,
    config=None,
) -> DreamReport:
    """Run one autoDream cycle. Thin wrapper around DreamCycle.run()."""
    return DreamCycle(memory_manager, config).run()
