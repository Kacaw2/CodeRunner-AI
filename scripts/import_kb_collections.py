"""Import manually managed Chroma collections after Chroma 1.x migration."""

import argparse
import json
from pathlib import Path

from ai.knowledge.store import get_knowledge_base


TARGETS = {
    "knowledge_points": "knowledge",
    "error_patterns": "error_patterns",
}


def _upsert(collection, data):
    ids = data.get("ids") or []
    if not ids:
        return 0

    existing = collection.get(include=["documents"])
    existing_docs = set(existing.get("documents") or [])
    documents = data.get("documents") or []
    embeddings = data.get("embeddings")
    metadatas = data.get("metadatas")

    filtered = [
        (idx, doc)
        for idx, doc in enumerate(documents)
        if doc not in existing_docs
    ]
    if not filtered:
        return 0

    keep_indices = [idx for idx, _ in filtered]
    collection.upsert(
        ids=[ids[idx] for idx in keep_indices],
        embeddings=[embeddings[idx] for idx in keep_indices] if embeddings else None,
        documents=[documents[idx] for idx in keep_indices],
        metadatas=[metadatas[idx] for idx in keep_indices] if metadatas else None,
    )
    return len(keep_indices)


def import_file(path: Path) -> dict:
    kb = get_knowledge_base()
    payload = json.loads(path.read_text(encoding="utf-8"))
    counts = {}
    for input_name, attr in TARGETS.items():
        counts[input_name] = _upsert(getattr(kb, attr), payload.get(input_name, {}))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    counts = import_file(Path(args.input))
    print(counts)


if __name__ == "__main__":
    main()
