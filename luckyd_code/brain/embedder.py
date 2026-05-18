"""Embedder — generates embeddings for code chunks.

Supports multiple backends:
  - sentence-transformers (local, no API key)
  - OpenAI text-embedding-3-small (requires API key)

All dependencies are optional — embedder returns available=False gracefully.
"""

import os
from typing import Any

from ..log import get_logger

# Module-level singleton
_embedder: "Embedder | None" = None


def get_embedder() -> "Embedder":
    """Get or create the shared embedder singleton."""
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
        _embedder.load()
    return _embedder


class Embedder:
    """Generates embeddings for text/code using available backends."""

    def __init__(self) -> None:
        self.available = False
        self.dimension = 0
        self.model_name = "none"
        self._model: Any = None
        self._openai_client: Any = None

    def load(self, model_type: str | None = None) -> bool:
        """Load the embedding model.

        Args:
            model_type: "local" for sentence-transformers, "openai" for OpenAI API.
                        If None, reads from settings or tries local first.

        Returns:
            True if a backend was successfully loaded.
        """
        if model_type is None:
            try:
                from .. import settings as cfg
                model_type = str(cfg.load_settings().get("embedding_model", "local"))
            except Exception:
                model_type = "local"

        if model_type == "openai":
            return self._load_openai()
        return self._load_local()

    def _load_local(self) -> bool:
        """Load sentence-transformers for local embeddings."""
        try:
            import contextlib
            import io
            import sentence_transformers

            with contextlib.redirect_stderr(io.StringIO()):
                self._model = sentence_transformers.SentenceTransformer(
                    "all-MiniLM-L6-v2"
                )
            self.dimension = 384
            self.model_name = "sentence-transformers/all-MiniLM-L6-v2"
            self.available = True
            get_logger().info(
                "Loaded local embedding model: %s (dim=%d)",
                self.model_name, self.dimension,
            )
            return True
        except ImportError:
            get_logger().info(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
        except Exception as exc:
            get_logger().warning("Failed to load sentence-transformers: %s", exc)

        self.available = False
        return False

    def _load_openai(self) -> bool:
        """Load OpenAI embedding API client."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            get_logger().warning(
                "OPENAI_API_KEY not set. Cannot use OpenAI embeddings."
            )
            self.available = False
            return False

        try:
            from openai import OpenAI

            self._openai_client = OpenAI(api_key=api_key)
            self.dimension = 1536
            self.model_name = "text-embedding-3-small"
            self.available = True
            get_logger().info("Loaded OpenAI embedding model: text-embedding-3-small")
            return True
        except ImportError:
            get_logger().warning("openai package not installed.")
        except Exception as exc:
            get_logger().warning("Failed to load OpenAI embeddings: %s", exc)

        self.available = False
        return False

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Embed a list of texts into vectors.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (list of floats), or None if unavailable.
        """
        if not self.available or not texts:
            return None

        # Filter out empty texts
        valid_texts = [t for t in texts if t and t.strip()]
        if not valid_texts:
            return None

        # Truncate very long texts (sentence-transformers has 256/512 token limit)
        truncated = [t[:8192] for t in valid_texts]

        try:
            if self._model is not None:
                # sentence-transformers
                import numpy as np

                embeddings = self._model.encode(truncated, show_progress_bar=False)
                return embeddings.tolist() if isinstance(embeddings, np.ndarray) else embeddings  # type: ignore[no-any-return]
            elif self._openai_client is not None:
                resp = self._openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=truncated,
                )
                return [item.embedding for item in resp.data]
        except Exception as exc:
            get_logger().warning("Embedding failed: %s", exc)

        return None

    def embed_query(self, query: str) -> list[float] | None:
        """Embed a single query string.

        Args:
            query: The search query.

        Returns:
            Single embedding vector, or None if unavailable.
        """
        result = self.embed([query])
        if result:
            return result[0]
        return None
