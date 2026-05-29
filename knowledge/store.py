import logging
import os

logger = logging.getLogger(__name__)

_kb_instance = None


class KnowledgeBase:
    """Vector-based knowledge base using ChromaDB for problem similarity search and knowledge retrieval."""

    def __init__(self, persist_dir=None):
        import chromadb
        from sentence_transformers import SentenceTransformer

        if persist_dir is None:
            persist_dir = os.path.join(os.getcwd(), "data", "knowledge_base")
        os.makedirs(persist_dir, exist_ok=True)

        self.client = chromadb.PersistentClient(path=persist_dir)
        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")

        self.questions = self.client.get_or_create_collection(
            "questions", metadata={"hnsw:space": "cosine"},
        )
        self.knowledge = self.client.get_or_create_collection(
            "knowledge_points", metadata={"hnsw:space": "cosine"},
        )
        self.error_patterns = self.client.get_or_create_collection(
            "error_patterns", metadata={"hnsw:space": "cosine"},
        )

    def index_problem(self, problem):
        """Index a problem (not per-variant) into the vector store."""
        text = f"{problem.title}\n{problem.description}"
        embedding = self.embedder.encode(text).tolist()
        languages = [v.programming_language for v in problem.variants] if problem.variants else []
        self.questions.upsert(
            ids=[f"problem_{problem.id}"],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{
                "problem_id": problem.id,
                "languages": ",".join(languages),
                "title": problem.title or "",
                "difficulty": problem.difficulty or "easy",
            }],
        )

    def search_similar_problems(self, query: str, n: int = 5, language: str = None) -> list:
        """Find problems similar to a query."""
        if self.questions.count() == 0:
            return []

        embedding = self.embedder.encode(query).tolist()
        where = {"language": language} if language else None
        try:
            results = self.questions.query(
                query_embeddings=[embedding],
                n_results=min(n, self.questions.count()),
                where=where,
            )
        except Exception:
            results = self.questions.query(
                query_embeddings=[embedding],
                n_results=min(n, self.questions.count()),
            )

        if not results["metadatas"] or not results["metadatas"][0]:
            return []

        return [
            {
                "problem_id": meta.get("problem_id") or meta.get("question_id"),
                "title": meta.get("title", ""),
                "similarity": round(max(0, 1 - dist), 4) if dist is not None else 0,
                "text_preview": doc[:200],
            }
            for meta, doc, dist in zip(
                results["metadatas"][0],
                results["documents"][0],
                results["distances"][0],
            )
        ]

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

        embedding = self.embedder.encode(query).tolist()
        where = None
        if scope_filter and scope_filter.get("owner_id"):
            where = {"$or": [
                {"scope": "global"},
                {"owner_id": scope_filter["owner_id"]},
            ]}

        results = self.knowledge.query(
            query_embeddings=[embedding],
            n_results=min(n, self.knowledge.count()),
            include=["documents", "metadatas", "distances"],
            where=where,
        )
        if not results["documents"] or not results["documents"][0]:
            return []

        return [
            {
                "topic": meta.get("topic", ""),
                "category": meta.get("category", ""),
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
