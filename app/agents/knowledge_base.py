import logging
import os

logger = logging.getLogger(__name__)

_kb_instance = None


class KnowledgeBase:
    """Vector-based knowledge base using ChromaDB for question similarity search and knowledge retrieval."""

    def __init__(self, persist_dir=None):
        import chromadb
        from sentence_transformers import SentenceTransformer

        if persist_dir is None:
            persist_dir = os.path.join(os.getcwd(), "data", "knowledge_base")
        os.makedirs(persist_dir, exist_ok=True)

        self.client = chromadb.PersistentClient(path=persist_dir)
        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")

        self.questions = self.client.get_or_create_collection("questions")
        self.knowledge = self.client.get_or_create_collection("knowledge_points")
        self.error_patterns = self.client.get_or_create_collection("error_patterns")

    def index_question(self, question):
        """Add a question to the vector store for similarity search."""
        text = f"{question.title}\n{question.description}"
        embedding = self.embedder.encode(text).tolist()
        self.questions.upsert(
            ids=[str(question.id)],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{
                "question_id": question.id,
                "language": question.programming_language or "python",
                "title": question.title or "",
            }],
        )

    def search_similar_questions(self, query: str, n: int = 5, language: str = None) -> list:
        """Find questions similar to a query."""
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
                "question_id": meta.get("question_id"),
                "title": meta.get("title", ""),
                "similarity": round(1 - dist, 3) if dist else 0,
                "text_preview": doc[:200],
            }
            for meta, doc, dist in zip(
                results["metadatas"][0],
                results["documents"][0],
                results["distances"][0],
            )
        ]

    def add_knowledge_point(self, topic: str, content: str, category: str = "concept"):
        """Add a course knowledge point."""
        embedding = self.embedder.encode(f"{topic}: {content}").tolist()
        self.knowledge.upsert(
            ids=[f"{category}_{topic}"],
            embeddings=[embedding],
            documents=[content],
            metadatas=[{"topic": topic, "category": category}],
        )

    def search_knowledge(self, query: str, n: int = 3) -> list:
        """Search course knowledge for relevant context."""
        if self.knowledge.count() == 0:
            return []

        embedding = self.embedder.encode(query).tolist()
        results = self.knowledge.query(
            query_embeddings=[embedding],
            n_results=min(n, self.knowledge.count()),
        )
        return results["documents"][0] if results["documents"] else []

    def add_error_pattern(self, error_type: str, description: str, explanation: str):
        """Add a common error pattern for tutoring reference."""
        text = f"{error_type}: {description}\nExplanation: {explanation}"
        embedding = self.embedder.encode(text).tolist()
        self.error_patterns.upsert(
            ids=[f"err_{error_type}_{hash(description) % 10000}"],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{"error_type": error_type}],
        )

    def search_error_patterns(self, query: str, n: int = 3) -> list:
        """Search for similar error patterns."""
        if self.error_patterns.count() == 0:
            return []

        embedding = self.embedder.encode(query).tolist()
        results = self.error_patterns.query(
            query_embeddings=[embedding],
            n_results=min(n, self.error_patterns.count()),
        )
        return results["documents"][0] if results["documents"] else []


def get_knowledge_base() -> KnowledgeBase:
    """Get or create the singleton KnowledgeBase instance."""
    global _kb_instance
    if _kb_instance is None:
        try:
            _kb_instance = KnowledgeBase()
        except Exception as e:
            logger.error("Failed to initialize KnowledgeBase: %s", e)
            raise
    return _kb_instance


def index_all_questions():
    """Index all existing questions into the vector store."""
    from app.models.question import Question

    kb = get_knowledge_base()
    questions = Question.query.all()
    for q in questions:
        try:
            kb.index_question(q)
        except Exception as e:
            logger.warning("Failed to index question %d: %s", q.id, e)
    logger.info("Indexed %d questions", len(questions))
    return len(questions)
