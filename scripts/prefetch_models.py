"""Pre-download embedding (and rerank) models into the image's HF cache.

Invoked at Docker build time so the running container never reaches out to
HuggingFace at runtime (F6: eliminate runtime model download). At runtime the
images set HF_HUB_OFFLINE=1 / TRANSFORMERS_OFFLINE=1, so a missing model fails
loudly instead of silently downloading.

Reads model names straight from env (not core.config.get_settings) on purpose:
get_settings() runs the SECRET_KEY production gate, which would abort the build.
The defaults here mirror core.config.Settings.
"""

import os
import sys


def main() -> int:
    embed = os.environ.get("RAG_EMBED_MODEL", "all-MiniLM-L6-v2")
    rerank = os.environ.get("RAG_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

    from sentence_transformers import SentenceTransformer

    print(f"[prefetch] embedding model: {embed}", flush=True)
    SentenceTransformer(embed)

    # Rerank cross-encoder is default-off (RAG_RERANK_ENABLED) but we bundle it
    # so it can be enabled later without a runtime download. Non-fatal if it fails.
    try:
        from sentence_transformers import CrossEncoder

        print(f"[prefetch] rerank model: {rerank}", flush=True)
        CrossEncoder(rerank)
    except Exception as e:  # noqa: BLE001 - build-time best effort
        print(f"[prefetch] rerank prefetch skipped (non-fatal): {e}", file=sys.stderr, flush=True)

    print("[prefetch] complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
