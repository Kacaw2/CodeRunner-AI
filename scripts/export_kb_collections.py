"""Export non-derived Chroma collections before Chroma 1.x migration.

Questions are derived from MySQL problems and should be rebuilt. Knowledge
points and error patterns can contain teacher-created records, so they are
exported before the storage switch.
"""

import argparse
import json
from pathlib import Path

from ai.knowledge.store import get_knowledge_base


COLLECTIONS = {
    "knowledge_points": "knowledge",
    "error_patterns": "error_patterns",
}


def _jsonable(obj):
    if hasattr(obj, "tolist"):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def export(path: Path) -> None:
    kb = get_knowledge_base()
    payload = {}
    for output_name, attr in COLLECTIONS.items():
        collection = getattr(kb, attr)
        payload[output_name] = collection.get(
            include=["documents", "metadatas", "embeddings"]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_jsonable),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    export(Path(args.output))


if __name__ == "__main__":
    main()
