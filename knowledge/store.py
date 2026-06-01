import logging
import os

logger = logging.getLogger(__name__)

_kb_instance = None


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
    try:
        return client.get_or_create_collection(
            name=name,
            configuration={"hnsw": {"space": "cosine"}},
        )
    except (AttributeError, ValueError) as exc:
        # Chroma 0.6 local clients expect internal configuration objects while
        # Chroma 1.x clients expect a plain dict. Keep this fallback so older
        # local test environments still work during the upgrade window.
        message = str(exc)
        if (
            "'dict' object has no attribute" not in message
            and "CollectionConfiguration" not in message
        ):
            raise

    from chromadb.api.configuration import (
        CollectionConfigurationInternal,
        ConfigurationParameter,
        HNSWConfigurationInternal,
    )

    hnsw = HNSWConfigurationInternal(
        parameters=[ConfigurationParameter(name="space", value="cosine")]
    )

    return client.get_or_create_collection(
        name=name,
        configuration=CollectionConfigurationInternal(
            parameters=[ConfigurationParameter(name="hnsw_configuration", value=hnsw)]
        ),
    )


class KnowledgeBase:
    """Vector-based knowledge base using ChromaDB for problem similarity search and knowledge retrieval."""

    def __init__(self, persist_dir=None):
        from sentence_transformers import SentenceTransformer

        from core.config import get_settings

        cfg = get_settings()
        if persist_dir is not None:
            # Explicit local persistence (isolated tests / one-off scripts).
            # Build a PersistentClient directly so we don't mutate the cached
            # settings singleton and leak mode into other callers.
            import chromadb
            from chromadb.config import Settings

            os.makedirs(persist_dir, exist_ok=True)
            self.client = chromadb.PersistentClient(
                path=persist_dir,
                settings=Settings(
                    anonymized_telemetry=cfg.CHROMA_ANONYMIZED_TELEMETRY
                ),
            )
        else:
            self.client = create_chroma_client()

        self.embedder = SentenceTransformer(cfg.RAG_EMBED_MODEL)

        self.questions = get_or_create_cosine_collection(self.client, "questions")
        self.knowledge = get_or_create_cosine_collection(self.client, "knowledge_points")
        self.error_patterns = get_or_create_cosine_collection(self.client, "error_patterns")

    def _split_text(self, text: str) -> list:
        """Split text into chunks for embedding (langchain splitter, pure-Python fallback)."""
        from core.config import get_settings
        cfg = get_settings()
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=cfg.RAG_CHUNK_SIZE, chunk_overlap=cfg.RAG_CHUNK_OVERLAP,
            )
            return splitter.split_text(text) or [text]
        except Exception:
            size, overlap = cfg.RAG_CHUNK_SIZE, cfg.RAG_CHUNK_OVERLAP
            if len(text) <= size:
                return [text]
            step = max(1, size - overlap)
            return [text[i:i + size] for i in range(0, len(text), step)] or [text]

    def index_problem(self, problem):
        """Index a problem (not per-variant) into the vector store, chunked."""
        text = f"{problem.title}\n{problem.description}"
        languages = [v.programming_language for v in problem.variants] if problem.variants else []
        base_meta = {
            "problem_id": problem.id,
            "languages": ",".join(languages),
            "title": problem.title or "",
            "difficulty": problem.difficulty or "easy",
            "created_by": getattr(problem, "created_by", 0) or 0,
        }
        for lang in languages:
            base_meta[f"lang_{lang}"] = True

        parent_id = f"problem_{problem.id}"
        # Drop any prior chunks so a shorter re-index can't leave stale tail chunks.
        try:
            self.questions.delete(where={"parent_id": parent_id})
        except Exception:
            pass

        chunks = self._split_text(text)
        embeddings = self.embedder.encode(chunks)
        ids = [f"{parent_id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = []
        for i in range(len(chunks)):
            m = dict(base_meta)
            m["parent_id"] = parent_id
            m["chunk_index"] = i
            metadatas.append(m)
        self.questions.upsert(
            ids=ids,
            embeddings=[e.tolist() for e in embeddings],
            documents=chunks,
            metadatas=metadatas,
        )

    def _rerank(self, query: str, candidates: list) -> list:
        """Re-rank candidates with a cross-encoder; fall back to vector score."""
        from core.config import get_settings
        cfg = get_settings()
        if not cfg.RAG_RERANK_ENABLED or not candidates:
            return candidates
        try:
            if not hasattr(self, "_reranker"):
                from sentence_transformers import CrossEncoder
                self._reranker = CrossEncoder(cfg.RAG_RERANK_MODEL)
            pairs = [(query, c.get("content") or c.get("text_preview", "")) for c in candidates]
            scores = self._reranker.predict(pairs)
            for c, s in zip(candidates, scores):
                c["rerank_score"] = float(s)
            return sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)
        except Exception as e:
            logger.warning("Rerank unavailable, falling back to vector score: %s", e)
            return sorted(candidates, key=lambda c: c.get("similarity", 0), reverse=True)

    def search_similar_problems(self, query: str, n: int = 5, language: str = None,
                                owner_id: int = None) -> list:
        """Find problems similar to a query, with optional language and owner filters."""
        if self.questions.count() == 0:
            return []

        from core.config import get_settings
        cfg = get_settings()
        embedding = self.embedder.encode(query).tolist()

        clauses = []
        if language:
            clauses.append({f"lang_{language}": True})
        if owner_id:
            clauses.append({"$or": [{"created_by": owner_id}, {"created_by": 0}]})  # 0 = 公共题库
        where = clauses[0] if len(clauses) == 1 else ({"$and": clauses} if clauses else None)

        candidate_k = max(n, cfg.RAG_CANDIDATE_K)
        results = self.questions.query(
            query_embeddings=[embedding],
            n_results=min(candidate_k, self.questions.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        if not results["metadatas"] or not results["metadatas"][0]:
            return []

        # Collapse chunks: keep the best-scoring chunk per parent problem.
        by_parent = {}
        for meta, doc, dist in zip(
            results["metadatas"][0],
            results["documents"][0],
            results["distances"][0],
        ):
            parent = meta.get("parent_id") or f"problem_{meta.get('problem_id')}"
            distance = dist if dist is not None else 1.0
            prev = by_parent.get(parent)
            if prev is not None and distance >= prev["_distance"]:
                continue
            by_parent[parent] = {
                "problem_id": meta.get("problem_id") or meta.get("question_id"),
                "title": meta.get("title", ""),
                "similarity": round(max(0, 1 - distance), 4),
                "content": doc or "",
                "text_preview": (doc or "")[:200],
                "_distance": distance,
            }

        candidates = self._rerank(query, list(by_parent.values()))
        final = candidates[:n] if n else candidates[:cfg.RAG_FINAL_K]
        for c in final:
            c.pop("content", None)
            c.pop("_distance", None)
        return final

    def add_knowledge_point(self, topic: str, content: str, category: str = "concept",
                            scope: str = "global", owner_id: int = None):
        """Add a course knowledge point with optional scope isolation."""
        embedding = self.embedder.encode(f"{topic}: {content}").tolist()
        metadata = {
            "topic": topic,
            "category": category,
            "scope": scope,
            "owner_id": owner_id or 0,
        }
        self.knowledge.upsert(
            ids=[f"{category}_{topic}"],
            embeddings=[embedding],
            documents=[content],
            metadatas=[metadata],
        )

    def search_knowledge(self, query: str, n: int = 3, scope_filter: dict = None) -> list:
        """Search course knowledge for relevant context. Returns structured results."""
        if self.knowledge.count() == 0:
            return []

        from core.config import get_settings
        cfg = get_settings()
        embedding = self.embedder.encode(query).tolist()
        where = None
        if scope_filter and scope_filter.get("owner_id"):
            where = {"$or": [
                {"scope": "global"},
                {"owner_id": scope_filter["owner_id"]},
            ]}

        candidate_k = max(n, cfg.RAG_CANDIDATE_K)
        results = self.knowledge.query(
            query_embeddings=[embedding],
            n_results=min(candidate_k, self.knowledge.count()),
            include=["documents", "metadatas", "distances"],
            where=where,
        )
        if not results["documents"] or not results["documents"][0]:
            return []

        candidates = [
            {
                "topic": meta.get("topic", ""),
                "category": meta.get("category", ""),
                "content": doc,
                "distance": round(dist, 4),
                "similarity": round(max(0, 1 - dist), 4),
                "score": round(max(0, 1 - dist), 4),
            }
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]
        return self._rerank(query, candidates)[:n]

    def add_error_pattern(self, error_type: str, description: str, explanation: str):
        """Add a common error pattern for tutoring reference."""
        text = f"{error_type}: {description}\nExplanation: {explanation}"
        embedding = self.embedder.encode(text).tolist()
        self.error_patterns.upsert(
            ids=[f"err_{error_type}_{hash(description) % 10000}"],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{"error_type": error_type, "description": description}],
        )

    def search_error_patterns(self, query: str, n: int = 3) -> list:
        """Search for similar error patterns. Returns structured results."""
        if self.error_patterns.count() == 0:
            return []

        embedding = self.embedder.encode(query).tolist()
        results = self.error_patterns.query(
            query_embeddings=[embedding],
            n_results=min(n, self.error_patterns.count()),
            include=["documents", "metadatas", "distances"],
        )
        if not results["documents"] or not results["documents"][0]:
            return []

        return [
            {
                "error_type": meta.get("error_type", ""),
                "content": doc,
                "distance": round(dist, 4),
                "score": round(max(0, 1 - dist), 4),
            }
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]


def get_knowledge_base() -> KnowledgeBase:
    """Get or create the singleton KnowledgeBase instance."""
    global _kb_instance
    if _kb_instance is None:
        try:
            _kb_instance = KnowledgeBase()
        except Exception:
            logger.exception("Failed to initialize KnowledgeBase")
            raise
    return _kb_instance


def kb_health() -> dict:
    """Readiness probe for the knowledge base (F6). Never raises.

    Constructing the KnowledgeBase loads the embedding model — with
    HF_*_OFFLINE=1 a missing/uncached model fails here, which is exactly what
    this probe surfaces. Used as a warm-up at startup and by /health.

    Returns a dict with status "ok" or "degraded". Degraded is non-fatal: the
    search tools already return empty results on failure, so callers continue
    without RAG context rather than crashing.
    """
    try:
        from core.config import get_settings

        kb = get_knowledge_base()
        return {
            "status": "ok",
            "embed_model": get_settings().RAG_EMBED_MODEL,
            "questions": kb.questions.count(),
            "knowledge_points": kb.knowledge.count(),
            "error_patterns": kb.error_patterns.count(),
        }
    except Exception as e:
        logger.warning("Knowledge base health probe degraded: %s", e)
        return {"status": "degraded", "error": str(e)}


def index_all_problems():
    """Index all problems (not per-variant) into the vector store."""
    from app.models.problem import Problem

    kb = get_knowledge_base()
    problems = Problem.query.all()
    for p in problems:
        try:
            kb.index_problem(p)
        except Exception as e:
            logger.warning("Failed to index problem %d: %s", p.id, e)
    logger.info("Indexed %d problems", len(problems))
    return len(problems)


def index_all_questions():
    """Legacy alias — delegates to index_all_problems."""
    return index_all_problems()
