# Chroma 1.x Upgrade Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Upgrade CodeRunner-AI from embedded ChromaDB `<1.0` file persistence to a Chroma 1.x-compatible deployment without losing teacher-managed knowledge data or reintroducing Docker rebuild/runtime drift.

**Architecture:** Run Chroma as a dedicated Docker service on the internal `educode_network`, backed by a `chroma_data` volume. `web`, `workers`, and `mcp_gateway` become Chroma HTTP clients and no longer directly share a SQLite/HNSW directory. Rebuild the derived `questions` collection from MySQL problems, and export/import manually maintained `knowledge_points` and `error_patterns` across the migration.

**Tech Stack:** Docker Compose, ChromaDB `1.5.9`, Python `chromadb.HttpClient`, Flask health checks, existing `knowledge.store`, existing RAG tests.

---

## Current Evidence

- `requirements.txt` currently pins Chroma below 1.0: `chromadb>=0.5.0,<1.0.0`.
- `knowledge/store.py` uses `chromadb.PersistentClient(path=...)` and legacy collection configuration via `metadata={"hnsw:space": "cosine"}`.
- `compose.yaml` mounts `kb_data` into `web` and `mcp_gateway`; `workers` does not mount that volume, so multiple services can observe different KB state.
- The recent rebuild failure was caused by stale persisted Chroma collection rows with `config_json_str = '{}'`, which current Chroma code tried to read as a typed collection config and failed with `KeyError: '_type'`.
- Official Chroma 1.x docs use `configuration={"hnsw": {"space": "cosine"}}` instead of metadata for index settings.
- PyPI currently lists `chromadb 1.5.9` as the latest release, dated May 5, 2026.

## Design Decision

Use **Chroma server mode** rather than continuing with embedded `PersistentClient`.

Why:

- It avoids multiple Python processes writing the same local Chroma files.
- It gives Docker a single persistent boundary: `chroma_data`.
- It lets `web`, `workers`, and `mcp_gateway` converge on the same KB state.
- It fits the repo's ongoing direction of clearer runtime service boundaries.

Do not expose Chroma to the host by default. Keep it internal to `educode_network`.

## Files To Modify

- `requirements.txt`
  Pin the Python Chroma client/server package to a known 1.x version.

- `core/config.py`
  Add Chroma connection settings used by `knowledge.store`.

- `knowledge/store.py`
  Replace direct `PersistentClient` construction with a client factory. Use Chroma 1.x `configuration` for collection creation.

- `scripts/export_kb_collections.py`
  New one-shot export helper for manual KB data before migration.

- `scripts/import_kb_collections.py`
  New one-shot import helper for manual KB data after migration.

- `scripts/migrate_kb.py`
  Update migration logging and validation from metadata-based HNSW checks to Chroma 1.x configuration checks.

- `compose.yaml`
  Add `chroma` service and `chroma_data` volume. Wire `web`, `workers`, and `mcp_gateway` to Chroma over HTTP. Remove direct `kb_data` mounts from app services.

- `docker/docker-compose.yml`
  Keep the side compose file aligned if it still mirrors the root compose contract.

- `tests/test_knowledge_base.py`
  Update collection configuration assertions.

- `tests/test_chroma_client_config.py`
  New focused tests for config-driven client construction and collection creation parameters.

## Task 1: Pin Chroma 1.x Dependency

**Files:**
- Modify: `requirements.txt:43-46`

- [x] **Step 1: Update dependency pin**

Replace:

```text
# Phase 3: Knowledge base / RAG
# Pin chromadb <1.0 to avoid Rust bindings requirement in Docker slim images
chromadb>=0.5.0,<1.0.0
sentence-transformers>=3.0.0
```

With:

```text
# Phase 3: Knowledge base / RAG
# Pin Chroma 1.x to avoid accidental storage/API drift during Docker rebuilds.
chromadb==1.5.9
sentence-transformers>=3.0.0
```

- [x] **Step 2: Rebuild only the Python images that install `requirements.txt`**

Run:

```powershell
docker compose build web workers mcp_gateway
```

Expected:

```text
Successfully built
```

or BuildKit equivalent output ending without errors.

- [x] **Step 3: Verify installed Chroma version in rebuilt images**

After recreation in Task 6, run:

```powershell
docker compose exec -T web python -m pip show chromadb
docker compose exec -T workers python -m pip show chromadb
docker compose exec -T mcp_gateway python -m pip show chromadb
```

Expected:

```text
Name: chromadb
Version: 1.5.9
```

## Task 2: Add Chroma Runtime Configuration

**Files:**
- Modify: `core/config.py`
- Test: `tests/test_chroma_client_config.py`

- [x] **Step 1: Write config test**

Create `tests/test_chroma_client_config.py`:

```python
"""Tests for Chroma runtime configuration and client selection."""

from unittest.mock import patch


def test_chroma_http_client_uses_configured_host(monkeypatch):
    from core.config import get_settings
    import knowledge.store as store

    settings = get_settings()
    monkeypatch.setattr(settings, "CHROMA_MODE", "http")
    monkeypatch.setattr(settings, "CHROMA_HOST", "chroma")
    monkeypatch.setattr(settings, "CHROMA_PORT", 8000)
    monkeypatch.setattr(settings, "CHROMA_SSL", False)

    with patch("chromadb.HttpClient") as http_client:
        store.create_chroma_client()

    http_client.assert_called_once_with(host="chroma", port=8000, ssl=False)


def test_chroma_persistent_client_kept_for_explicit_local_mode(monkeypatch, tmp_path):
    from core.config import get_settings
    import knowledge.store as store

    settings = get_settings()
    monkeypatch.setattr(settings, "CHROMA_MODE", "persistent")
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path / "kb"))

    with patch("chromadb.PersistentClient") as persistent_client:
        store.create_chroma_client()

    _, kwargs = persistent_client.call_args
    assert kwargs["path"] == str(tmp_path / "kb")
```

- [x] **Step 2: Run test and confirm it fails before implementation**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_chroma_client_config.py -q
```

Expected:

```text
FAILED ... AttributeError: module 'knowledge.store' has no attribute 'create_chroma_client'
```

If the host venv lacks `chromadb`, run the same test in Docker after Task 1 build:

```powershell
docker compose run --rm web pytest tests/test_chroma_client_config.py -q
```

- [x] **Step 3: Add settings**

In `core/config.py`, add these fields near the existing RAG settings:

```python
    # Chroma vector store. Default to server mode in Docker; set
    # CHROMA_MODE=persistent only for isolated local tests.
    CHROMA_MODE: str = os.environ.get("CHROMA_MODE", "http")
    CHROMA_HOST: str = os.environ.get("CHROMA_HOST", "chroma")
    CHROMA_PORT: int = int(os.environ.get("CHROMA_PORT", "8000"))
    CHROMA_SSL: bool = os.environ.get("CHROMA_SSL", "False").lower() in ("true", "1")
    CHROMA_PERSIST_DIR: str = os.environ.get(
        "CHROMA_PERSIST_DIR",
        os.path.join(os.getcwd(), "data", "knowledge_base"),
    )
    CHROMA_ANONYMIZED_TELEMETRY: bool = os.environ.get(
        "CHROMA_ANONYMIZED_TELEMETRY", "False"
    ).lower() in ("true", "1")
```

- [x] **Step 4: Run config test again after Task 3 implementation**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_chroma_client_config.py -q
```

Expected:

```text
2 passed
```

## Task 3: Move Chroma Client Creation Behind a Factory

**Files:**
- Modify: `knowledge/store.py:12-33`
- Test: `tests/test_chroma_client_config.py`
- Test: `tests/test_knowledge_base.py`

- [x] **Step 1: Add client factory and collection helper**

In `knowledge/store.py`, add:

```python
def create_chroma_client():
    """Create a Chroma client from runtime settings."""
    import chromadb
    from chromadb.config import Settings

    from core.config import get_settings

    cfg = get_settings()
    if cfg.CHROMA_MODE == "http":
        return chromadb.HttpClient(
            host=cfg.CHROMA_HOST,
            port=cfg.CHROMA_PORT,
            ssl=cfg.CHROMA_SSL,
        )

    if cfg.CHROMA_MODE == "persistent":
        os.makedirs(cfg.CHROMA_PERSIST_DIR, exist_ok=True)
        return chromadb.PersistentClient(
            path=cfg.CHROMA_PERSIST_DIR,
            settings=Settings(anonymized_telemetry=cfg.CHROMA_ANONYMIZED_TELEMETRY),
        )

    raise ValueError(f"Unsupported CHROMA_MODE: {cfg.CHROMA_MODE}")


def get_or_create_cosine_collection(client, name: str):
    """Create Chroma 1.x collections with cosine HNSW distance."""
    return client.get_or_create_collection(
        name=name,
        configuration={"hnsw": {"space": "cosine"}},
    )
```

- [x] **Step 2: Update `KnowledgeBase.__init__`**

Replace the current client/collection setup with:

```python
    def __init__(self, persist_dir=None):
        from sentence_transformers import SentenceTransformer

        from core.config import get_settings

        cfg = get_settings()
        if persist_dir is not None:
            cfg.CHROMA_MODE = "persistent"
            cfg.CHROMA_PERSIST_DIR = persist_dir

        self.client = create_chroma_client()
        self.embedder = SentenceTransformer(cfg.RAG_EMBED_MODEL)

        self.questions = get_or_create_cosine_collection(self.client, "questions")
        self.knowledge = get_or_create_cosine_collection(self.client, "knowledge_points")
        self.error_patterns = get_or_create_cosine_collection(self.client, "error_patterns")
```

- [x] **Step 3: Update tests that inspect collection config**

In `tests/test_knowledge_base.py`, replace metadata assertions with a helper:

```python
def _collection_space(collection):
    config = getattr(collection, "configuration", None)
    if isinstance(config, dict):
        return config.get("hnsw", {}).get("space")
    return collection.metadata.get("hnsw:space")
```

Then update:

```python
assert _collection_space(kb.questions) == "cosine"
assert _collection_space(kb.knowledge) == "cosine"
assert _collection_space(kb.error_patterns) == "cosine"
```

- [x] **Step 4: Run focused KB tests**

Run:

```powershell
docker compose run --rm web pytest tests/test_chroma_client_config.py tests/test_knowledge_base.py -q
```

Expected:

```text
passed
```

## Task 4: Add Export/Import For Manual Knowledge Data

**Files:**
- Create: `scripts/export_kb_collections.py`
- Create: `scripts/import_kb_collections.py`
- Test manually inside Docker before switching compose to Chroma server.

- [x] **Step 1: Create export script**

Create `scripts/export_kb_collections.py`:

```python
"""Export non-derived Chroma collections before Chroma 1.x migration.

Questions are derived from MySQL problems and should be rebuilt. Knowledge
points and error patterns can contain teacher-created records, so they are
exported before the storage switch.
"""

import argparse
import json
from pathlib import Path

from knowledge.store import get_knowledge_base


COLLECTIONS = {
    "knowledge_points": "knowledge",
    "error_patterns": "error_patterns",
}


def export(path: Path) -> None:
    kb = get_knowledge_base()
    payload = {}
    for output_name, attr in COLLECTIONS.items():
        collection = getattr(kb, attr)
        payload[output_name] = collection.get(
            include=["documents", "metadatas", "embeddings"]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    export(Path(args.output))


if __name__ == "__main__":
    main()
```

- [x] **Step 2: Create import script**

Create `scripts/import_kb_collections.py`:

```python
"""Import manually managed Chroma collections after Chroma 1.x migration."""

import argparse
import json
from pathlib import Path

from knowledge.store import get_knowledge_base


TARGETS = {
    "knowledge_points": "knowledge",
    "error_patterns": "error_patterns",
}


def _upsert(collection, data):
    ids = data.get("ids") or []
    if not ids:
        return 0
    collection.upsert(
        ids=ids,
        embeddings=data.get("embeddings"),
        documents=data.get("documents"),
        metadatas=data.get("metadatas"),
    )
    return len(ids)


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
```

- [x] **Step 3: Export current manual collections**

Run before deleting or detaching the old `kb_data` volume:

```powershell
docker compose exec -T web python -m scripts.export_kb_collections --output /app/data/kb-manual-export.json
docker cp educode_web:/app/data/kb-manual-export.json data\kb-manual-export.json
```

Expected:

```text
data\kb-manual-export.json exists and contains knowledge_points and error_patterns keys
```

## Task 5: Add Dedicated Chroma Service

**Files:**
- Modify: `compose.yaml`
- Modify: `docker/docker-compose.yml`

- [x] **Step 1: Add `chroma` service**

Add this service under `services`:

```yaml
  chroma:
    image: chromadb/chroma:1.5.9
    container_name: educode_chroma
    command: ["chroma", "run", "--host", "0.0.0.0", "--port", "8000", "--path", "/chroma/chroma"]
    environment:
      ANONYMIZED_TELEMETRY: "FALSE"
      CHROMA_ANONYMIZED_TELEMETRY: "FALSE"
    volumes:
      - chroma_data:/chroma/chroma
    networks:
      - educode_network
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import socket; s=socket.create_connection(('localhost',8000), timeout=3); s.close()\""]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 20s
    restart: unless-stopped
```

- [x] **Step 2: Wire app services to HTTP Chroma**

For `web`, `workers`, and `mcp_gateway`, add:

```yaml
      CHROMA_MODE: http
      CHROMA_HOST: chroma
      CHROMA_PORT: "8000"
      CHROMA_SSL: "False"
      CHROMA_ANONYMIZED_TELEMETRY: "False"
```

- [x] **Step 3: Add dependencies**

For `web`, `workers`, and `mcp_gateway`, add:

```yaml
      chroma:
        condition: service_healthy
```

under each service's `depends_on`.

- [x] **Step 4: Remove direct Chroma file mounts from app services**

Remove these mounts from `web` and `mcp_gateway`:

```yaml
      - kb_data:/app/data/knowledge_base
```

Do not add this mount to `workers`.

- [x] **Step 5: Replace volume declaration**

Replace:

```yaml
  kb_data:
```

with:

```yaml
  chroma_data:
```

- [x] **Step 6: Validate compose config**

Run:

```powershell
docker compose config --services
```

Expected includes:

```text
chroma
db
redis
executor
mcp_gateway
web
workers
```

## Task 6: Recreate Services And Rebuild Knowledge Data

**Files:**
- No source edits.
- Uses: `data/kb-manual-export.json`

- [x] **Step 1: Start Chroma and app stack with recreated containers**

Run:

```powershell
docker compose up -d --build --force-recreate chroma mcp_gateway web workers
```

Expected:

```text
Container educode_chroma Started
Container educode_web Started
Container educode_workers Started
Container educode_mcp_gateway Started
```

- [x] **Step 2: Check Chroma service status**

Run:

```powershell
docker compose ps chroma
```

Expected:

```text
educode_chroma ... healthy
```

- [x] **Step 3: Copy manual export into `web` container**

Run:

```powershell
docker cp data\kb-manual-export.json educode_web:/tmp/kb-manual-export.json
```

Expected: command exits `0`.

- [x] **Step 4: Rebuild derived problems and seed built-ins**

Run:

```powershell
docker compose exec -T web python -m scripts.migrate_kb
```

Expected includes:

```text
Recreated collection 'questions' with distance=cosine
Indexed 35 problems.
Seeded 27 error patterns, 21 knowledge points.
Migration complete
```

The exact problem count can differ if the database changed; the command must exit `0`.

- [x] **Step 5: Import manual collections**

Run:

```powershell
docker compose exec -T web python -m scripts.import_kb_collections --input /tmp/kb-manual-export.json
```

Expected:

```text
{'knowledge_points': 0, 'error_patterns': 0}
```

The numbers can be greater than `0` if teacher-created records existed beyond seed data.

## Task 7: Update Migration Script For Chroma 1.x

**Files:**
- Modify: `scripts/migrate_kb.py:49-52`

- [x] **Step 1: Add config reader helper**

Add:

```python
def _collection_space(collection) -> str:
    config = getattr(collection, "configuration", None)
    if isinstance(config, dict):
        return config.get("hnsw", {}).get("space", "unknown")
    metadata = getattr(collection, "metadata", None) or {}
    return metadata.get("hnsw:space", "unknown")
```

- [x] **Step 2: Use helper in logging**

Replace:

```python
            space = col.metadata.get("hnsw:space", "unknown")
```

With:

```python
            space = _collection_space(col)
```

- [x] **Step 3: Validate migration output**

Run:

```powershell
docker compose exec -T web python -m scripts.migrate_kb
```

Expected:

```text
Recreated collection 'questions' with distance=cosine
Recreated collection 'knowledge_points' with distance=cosine
Recreated collection 'error_patterns' with distance=cosine
```

## Task 8: Verify Runtime Health And API Behavior

**Files:**
- No source edits.

- [x] **Step 1: Verify all services are healthy**

Run:

```powershell
docker compose ps -a
```

Expected:

```text
educode_chroma ... healthy
educode_web ... healthy
educode_workers ... healthy
educode_mcp_gateway ... healthy
```

- [x] **Step 2: Verify Flask health**

Run:

```powershell
(Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:19900/health' -TimeoutSec 10).Content
```

Expected:

```json
{"checks":{"database":"ok","knowledge_base":"ok"},"service":"coderunner","status":"healthy"}
```

- [x] **Step 3: Verify Agent Host health**

Run:

```powershell
(Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:8100/api/health' -TimeoutSec 10).Content
```

Expected includes:

```json
{"status":"ok","service":"agent-host","redis":"connected","knowledge_base":"ok"}
```

- [x] **Step 4: Verify KB counts**

Run:

```powershell
docker compose exec -T web python -c "from knowledge.store import kb_health; print(kb_health())"
docker compose exec -T workers python -c "from knowledge.store import kb_health; print(kb_health())"
docker compose exec -T mcp_gateway python -c "from knowledge.store import kb_health; print(kb_health())"
```

Expected:

```text
{'status': 'ok', 'embed_model': 'all-MiniLM-L6-v2', 'questions': 43, 'knowledge_points': 21, 'error_patterns': 27}
```

Counts can differ from this local snapshot if the database changed, but each count should be nonzero and should match across `web`, `workers`, and `mcp_gateway`.

- [x] **Step 5: Verify no `_type` failure remains**

Run:

```powershell
docker compose logs --since=5m web workers mcp_gateway | Select-String -Pattern \"KeyError: '_type'|degraded: '_type'\"
```

Expected: no output.

## Task 9: Run Regression Tests

**Files:**
- No source edits.

- [x] **Step 1: Run focused RAG tests in Docker**

Run:

```powershell
docker compose run --rm web pytest tests/test_chroma_client_config.py tests/test_knowledge_base.py tests/test_rag_filter.py tests/test_rag_chunk_rerank.py -q
```

Expected:

```text
passed
```

- [x] **Step 2: Run MCP/KB integration tests**

Run:

```powershell
docker compose run --rm web pytest tests/test_mcp_gateway.py tests/test_agent_features.py -q
```

Expected:

```text
passed
```

- [x] **Step 3: Run diff checks**

Run:

```powershell
git diff --check
```

Expected: no output and exit code `0`.

## Task 10: Cleanup And Documentation

**Files:**
- Modify: `docs/DOCKER_CONTAINERS.md`
- Modify: `docs/DOCKER_CONTAINERS.zh-CN.md`
- Optional modify: `docs/README.md` if it lists active runtime docs.

- [x] **Step 1: Update Docker service docs**

Record the new Chroma service:

```markdown
### chroma

Runs the shared Chroma 1.x vector database for RAG collections. `web`,
`workers`, and `mcp_gateway` connect to it over the internal Docker network
instead of writing local Chroma files directly. Its persistent state lives in
the `chroma_data` Docker volume.
```

- [x] **Step 2: Document migration command**

Add this operational note:

````markdown
After Chroma dependency or schema changes, export manual KB collections first,
then recreate Chroma and run:

```powershell
docker compose exec -T web python -m scripts.migrate_kb
docker compose exec -T web python -m scripts.import_kb_collections --input /tmp/kb-manual-export.json
```
````

- [x] **Step 3: Confirm git scope**

Run:

```powershell
git status -sb
```

Expected changed files only from this plan:

```text
requirements.txt
core/config.py
knowledge/store.py
scripts/export_kb_collections.py
scripts/import_kb_collections.py
scripts/migrate_kb.py
compose.yaml
docker/docker-compose.yml
tests/test_chroma_client_config.py
tests/test_knowledge_base.py
docs/DOCKER_CONTAINERS.md
docs/DOCKER_CONTAINERS.zh-CN.md
```

Existing unrelated local changes, such as `.claude/settings.local.json`, must remain unstaged unless the user explicitly asks to include them.

## Rollback Plan

- Keep `data/kb-manual-export.json` until the upgraded stack passes runtime health and KB search checks.
- Keep the previous Docker volume backup until the user confirms the new Chroma service is acceptable.
- To roll back code, revert only the files changed by this plan.
- To roll back runtime, restore the previous `kb_data` volume backup and recreate `web`, `workers`, and `mcp_gateway` from the previous compose shape.
- Do not delete `docker_kb_data` until the Chroma 1.x stack has passed at least one full rebuild/recreate cycle.

## Success Criteria

- `docker compose ps -a` shows `chroma`, `web`, `workers`, and `mcp_gateway` healthy.
- `/health` reports `knowledge_base: ok`.
- `web`, `workers`, and `mcp_gateway` all report the same KB counts.
- Focused RAG and MCP tests pass in Docker.
- Logs no longer contain `KeyError: '_type'` or `degraded: '_type'`.
- `requirements.txt` pins Chroma 1.x.
- Collection creation uses `configuration={"hnsw": {"space": "cosine"}}`.
- Manual KB records are exported before migration and imported after migration.

## Execution Order

1. Dependency pin and config tests.
2. Client factory and Chroma 1.x collection creation.
3. Export manual KB data from current runtime.
4. Add Chroma server to compose.
5. Recreate stack.
6. Rebuild derived questions and import manual KB data.
7. Runtime verification.
8. Docs update.
9. Commit only scoped changes.



鍓╀綑姝ラ涓庡搴斿懡浠?1. 纭 chroma 鍋ュ悍锛堟柊 healthcheck 閲嶅缓鍚庯級

docker compose ps chroma
docker logs educode_chroma --tail 15
鏈熸湜锛歋TATUS 鏄剧ず (healthy)銆?
2. 鎷夎捣渚濊禆鏈嶅姟

docker compose up -d --force-recreate mcp_gateway web workers
docker compose ps
鏈熸湜锛歸eb / workers / mcp_gateway / chroma 鍏ㄩ儴 healthy銆?
3. 鎶婂鍑虹殑 KB 鏁版嵁娉ㄥ叆 web 瀹瑰櫒锛坉ocker cp 鏈夋寕杞?bug锛岀敤 cat 娴佸啓鍏ワ級

docker compose exec -T web sh -c 'cat > /tmp/kb-manual-export.json' < data/kb-manual-export.json
4. 閲嶅缓 questions 闆嗗悎 + 绉嶅瓙鏁版嵁

docker compose exec -T web python -m scripts.migrate_kb
5. 瀵煎洖鑰佸笀鎵嬪伐 KB锛坘nowledge_points鈫択nowledge锛宔rror_patterns鈫抏rror_patterns锛?
docker compose exec -T web python -m scripts.import_kb_collections --input /tmp/kb-manual-export.json
6. 楠岃瘉 /health 涓庤法鏈嶅姟 KB 璁℃暟涓€鑷?
docker compose exec -T web curl -s http://localhost:9900/health
docker compose exec -T workers curl -s http://localhost:8100/api/health
# 涓変釜鏈嶅姟鍚勮嚜杩?chroma 鐪嬮泦鍚堣鏁版槸鍚︿竴鑷达紙knowledge / error_patterns / questions锛?鍚屾椂妫€鏌ユ棩蹇楁棤 KeyError: '_type'锛?
docker logs educode_web 2>&1 | grep -i "_type" || echo "no _type error"
7. 鍥炲綊娴嬭瘯

docker compose exec -T web python -m pytest tests/test_chroma_client_config.py tests/test_knowledge_base.py tests/test_rag_filter.py tests/test_rag_chunk_rerank.py tests/test_mcp_gateway.py tests/test_agent_features.py -q
8. 楠岃瘉閫氳繃鍚庯紝鍒犻櫎鏃у嵎锛堜綘宸叉巿鏉冿級

git diff --check
docker volume rm docker_kb_data   # 鍚嶇О浠?docker volume ls | grep kb_data 瀹為檯涓哄噯
9. 鏀跺熬锛坋xecuting-plans 瑕佹眰锛?
璧?finishing-a-development-branch锛氭彁浜ゆ敼鍔ㄣ€佹妸璁″垝浠?docs/plans/active/ 褰掓。銆?
杩欎釜鍛戒护鏈塨ug
PS C:\Users\libie\Desktop\program\CodeRunner-AI> docker compose exec -T web sh -c 'cat > /tmp/kb-manual-export.json' < data/kb-manual-export.json
At line:1 char:69
+ ... ompose exec -T web sh -c 'cat > /tmp/kb-manual-export.json' < data/kb ...
+                                                                 ~
The '<' operator is reserved for future use.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : RedirectionNotSupported
