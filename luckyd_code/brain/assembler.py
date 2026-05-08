"""Context assembler — takes ranked chunks and produces prompt-ready context blocks."""

from typing import Any



def _token_count(text: str) -> int:
    return len(text) // 4


class ContextAssembler:
    """Assembles ranked chunks into a prompt-ready XML context block."""

    def assemble(
        self,
        chunks: list[dict[str, Any]],
        max_tokens: int = 8000,
        max_chunks: int = 20,
    ) -> str:
        if not chunks:
            return ""

        deduped = self._deduplicate(chunks)
        return self._format_chunks(deduped, max_tokens, max_chunks)

    def _deduplicate(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not chunks:
            return []

        by_file: dict[str, list[dict[str, Any]]] = {}
        for c in chunks:
            by_file.setdefault(c["file_path"], []).append(c)

        result: list[dict[str, Any]] = []
        for file_path, file_chunks in by_file.items():
            file_chunks.sort(key=lambda c: c.get("score", 0), reverse=True)

            keep: list[dict[str, Any]] = []
            for c in file_chunks:
                c_start = c.get("start_line", 0)
                c_end = c.get("end_line", 0)
                overlapping = False
                for kept in keep:
                    k_start = kept.get("start_line", 0)
                    k_end = kept.get("end_line", 0)
                    if not (c_end < k_start or c_start > k_end):
                        if c.get("score", 0) > kept.get("score", 0):
                            keep.remove(kept)
                            keep.append(c)
                        overlapping = True
                        break
                if not overlapping:
                    keep.append(c)

            result.extend(keep)

        result.sort(key=lambda c: c.get("score", 0), reverse=True)
        return result

    def _format_chunks(
        self,
        chunks: list[dict[str, Any]],
        max_tokens: int,
        max_chunks: int,
    ) -> str:
        parts: list[str] = []
        total_tokens = 0

        for chunk in chunks[:max_chunks]:
            score = chunk.get("score", 0)
            file_path = chunk.get("file_path", "")
            start_line = chunk.get("start_line", 0)
            end_line = chunk.get("end_line", 0)
            content = chunk.get("content", "").strip()

            if not content:
                continue

            chunk_tokens = _token_count(content)
            remaining = max_tokens - total_tokens - _token_count("<context></context>")

            if remaining <= 0:
                break

            if chunk_tokens > remaining:
                truncated_chars = remaining * 4
                content = content[:truncated_chars] + "..."

            score_str = f'{score:.2f}' if score else "0.00"
            context_tag = (
                f'<context file="{file_path}" lines="{start_line}-{end_line}" '
                f'relevance="{score_str}">\n'
                f"{content}\n"
                f"</context>"
            )

            parts.append(context_tag)
            total_tokens += _token_count(context_tag)

        return "\n\n".join(parts)
