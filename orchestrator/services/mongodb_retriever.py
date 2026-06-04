"""
orchestrator/services/mongodb_retriever.py
=============================================
MongoDB Retriever Service.
Implements RetrievalInterface with:
  - Stage 1: Vector similarity + Keyword search (Hybrid Search) returning Top 20 results.
  - Stage 2: Cross-Encoder reranking returning Top 5 results.
  - Parent-Child chunk expansion to fetch adjacent context.
"""

import asyncio
import threading
from typing import Optional, Any

import numpy as np
from sentence_transformers import CrossEncoder

from orchestrator.config.settings import settings
from orchestrator.models.context_models import RetrievedChunk
from orchestrator.services.retrieval_interface import RetrievalInterface
from orchestrator.services.embedder_service import embedder_service
from orchestrator.services.mongodb_service import mongodb_service
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)


class RerankerService:
    """Thread-safe Cross-Encoder reranker service."""

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()

    def _ensure_model(self) -> None:
        """Lazy-load Cross-Encoder model on first use."""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            logger.info("loading_reranker_model", model=settings.reranker_model)
            self._model = CrossEncoder(
                settings.reranker_model,
                device=settings.reranker_device,
            )
            logger.info("reranker_model_loaded", model=settings.reranker_model)

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Compute relevance scores for a query-document pair list."""
        if not documents:
            return []
        self._ensure_model()
        pairs = [[query, doc] for doc in documents]
        # predict returns numpy array or list of scores
        scores = self._model.predict(pairs)
        if isinstance(scores, np.ndarray):
            return scores.tolist()
        return scores


# Singleton reranker
reranker_service = RerankerService()


class MongoDBRetriever(RetrievalInterface):
    """
    Wise RAG MongoDB retriever.
    Performs hybrid search (vector + text), reranks using Cross-Encoder,
    and expands results using parent-child context window.
    """

    def __init__(self):
        pass

    @track_latency("mongodb_vector_search")
    async def _vector_search(
        self,
        query_vector: list[float],
        query_filter: dict,
        limit: int = 100
    ) -> list[dict]:
        """Fetch candidates and compute vector cosine similarity using numpy locally."""
        # 1. Fetch candidates from MongoDB (excluding raw embeddings to save bandwidth)
        cursor = mongodb_service.document_chunks.find(
            query_filter,
            {"doc_id": 1, "chunk_id": 1, "text": 1, "embedding": 1, "metadata": 1}
        )
        
        candidates = []
        async for chunk in cursor:
            candidates.append(chunk)
            
        if not candidates:
            return []

        # 2. Compute similarity
        q_vec = np.array(query_vector)
        q_norm = np.linalg.norm(q_vec)
        
        results = []
        for c in candidates:
            c_vec = np.array(c["embedding"])
            c_norm = np.linalg.norm(c_vec)
            if q_norm == 0 or c_norm == 0:
                sim = 0.0
            else:
                sim = float(np.dot(q_vec, c_vec) / (q_norm * c_norm))
                
            results.append({
                "doc_id": c["doc_id"],
                "chunk_id": c["chunk_id"],
                "text": c["text"],
                "metadata": c["metadata"],
                "vector_score": sim
            })
            
        # Sort and limit
        results.sort(key=lambda x: x["vector_score"], reverse=True)
        return results[:limit]

    @track_latency("mongodb_text_search")
    async def _text_search(
        self,
        query: str,
        query_filter: dict,
        limit: int = 100
    ) -> list[dict]:
        """Fetch candidates using MongoDB Text index, falling back to regex if needed."""
        text_filter = query_filter.copy()
        text_filter["$text"] = {"$search": query}
        
        results = []
        try:
            cursor = mongodb_service.document_chunks.find(
                text_filter,
                {"doc_id": 1, "chunk_id": 1, "text": 1, "metadata": 1, "score": {"$meta": "textScore"}}
            ).sort([("score", {"$meta": "textScore"})]).limit(limit)
            
            async for chunk in cursor:
                results.append({
                    "doc_id": chunk["doc_id"],
                    "chunk_id": chunk["chunk_id"],
                    "text": chunk["text"],
                    "metadata": chunk["metadata"],
                    "keyword_score": chunk["score"]
                })
        except Exception as e:
            # Fallback to regex search on text if index is not ready or fails
            logger.warning("mongodb_text_index_failed_using_regex", error=str(e))
            regex_filter = query_filter.copy()
            # Simple regex search
            words = [w for w in re.split(r"\W+", query) if len(w) > 2]
            if words:
                regex_pattern = "|".join(words)
                regex_filter["text"] = {"$regex": regex_pattern, "$options": "i"}
                
                cursor = mongodb_service.document_chunks.find(
                    regex_filter,
                    {"doc_id": 1, "chunk_id": 1, "text": 1, "metadata": 1}
                ).limit(limit)
                
                async for chunk in cursor:
                    results.append({
                        "doc_id": chunk["doc_id"],
                        "chunk_id": chunk["chunk_id"],
                        "text": chunk["text"],
                        "metadata": chunk["metadata"],
                        "keyword_score": 1.0  # constant score for regex match
                    })
        return results

    @track_latency("parent_child_expansion")
    async def _expand_chunk(self, doc_id: str, chunk_index: int) -> tuple[str, dict]:
        """Fetch adjacent chunks to expand context surrounding a match."""
        window = settings.parent_child_window
        if window <= 0:
            return "", {}
            
        cursor = mongodb_service.document_chunks.find({
            "doc_id": doc_id,
            "metadata.chunk_index": {
                "$gte": max(0, chunk_index - window),
                "$lte": chunk_index + window
            }
        }).sort([("metadata.chunk_index", 1)])
        
        sibling_chunks = []
        async for sc in cursor:
            sibling_chunks.append(sc)
            
        if not sibling_chunks:
            return "", {}
            
        expanded_text = "\n\n[...]\n\n".join([sc["text"] for sc in sibling_chunks])
        
        # Merge page numbers or other indicators if present
        pages = sorted(list(set(
            sc["metadata"].get("page_number")
            for sc in sibling_chunks
            if sc["metadata"].get("page_number") is not None
        )))
        
        summary_meta = {
            "expanded": True,
            "expanded_chunks_count": len(sibling_chunks),
            "original_chunk_index": chunk_index,
        }
        if pages:
            summary_meta["pages"] = pages
            
        return expanded_text, summary_meta

    @track_latency("mongodb_search")
    async def search(
        self,
        query: str,
        query_vector: Optional[list[float]] = None,
        top_k: int = 50,
        filters: Optional[dict] = None,
    ) -> list[RetrievedChunk]:
        """
        Runs the full 2-stage retrieval:
        1. Hybrid Search (Vector + Text score) -> Top 20
        2. Cross-Encoder Reranking -> Top 5
        Extends results using Parent-Child context expansion.
        """
        # Build base filter
        query_filter = {}
        if filters:
            for k, v in filters.items():
                if v is not None:
                    query_filter[f"metadata.{k}"] = v

        # ── STAGE 1: HYBRID SEARCH ─────────────────────────────
        # Get vector
        if not query_vector:
            query_vector = await embedder_service.embed_query(query)
            
        # Execute searches in parallel
        vector_task = self._vector_search(query_vector, query_filter, limit=50)
        text_task = self._text_search(query, query_filter, limit=50)
        
        vector_res, text_res = await asyncio.gather(vector_task, text_task)
        
        # Fuse results
        # Min-max normalize vector scores to [0, 1]
        v_scores = [x["vector_score"] for x in vector_res]
        min_v = min(v_scores) if v_scores else 0.0
        max_v = max(v_scores) if v_scores else 1.0
        v_range = max_v - min_v if max_v != min_v else 1.0
        
        # Min-max normalize keyword scores
        k_scores = [x["keyword_score"] for x in text_res]
        min_k = min(k_scores) if k_scores else 0.0
        max_k = max(k_scores) if k_scores else 1.0
        k_range = max_k - min_k if max_k != min_k else 1.0

        merged_candidates = {}
        
        # Add vector results
        for item in vector_res:
            cid = item["chunk_id"]
            norm_v = (item["vector_score"] - min_v) / v_range
            merged_candidates[cid] = {
                "doc_id": item["doc_id"],
                "chunk_id": item["chunk_id"],
                "text": item["text"],
                "metadata": item["metadata"],
                "norm_v": norm_v,
                "norm_k": 0.0
            }
            
        # Add or merge keyword results
        for item in text_res:
            cid = item["chunk_id"]
            norm_k = (item["keyword_score"] - min_k) / k_range
            if cid in merged_candidates:
                merged_candidates[cid]["norm_k"] = norm_k
            else:
                merged_candidates[cid] = {
                    "doc_id": item["doc_id"],
                    "chunk_id": item["chunk_id"],
                    "text": item["text"],
                    "metadata": item["metadata"],
                    "norm_v": 0.0,
                    "norm_k": norm_k
                }

        # Calculate hybrid score
        hybrid_list = []
        w = settings.hybrid_vector_weight
        for cid, item in merged_candidates.items():
            hybrid_score = w * item["norm_v"] + (1 - w) * item["norm_k"]
            hybrid_list.append({
                "doc_id": item["doc_id"],
                "chunk_id": item["chunk_id"],
                "text": item["text"],
                "metadata": item["metadata"],
                "hybrid_score": hybrid_score
            })
            
        # Sort by hybrid score and limit to Top 20
        hybrid_list.sort(key=lambda x: x["hybrid_score"], reverse=True)
        top_20 = hybrid_list[:20]
        
        if not top_20:
            logger.info("mongodb_search_no_results", query=query[:50])
            return []

        # Check database miss
        best_vector_score = 0.0
        if vector_res:
            best_vector_score = vector_res[0]["vector_score"]
            
        if not vector_res or best_vector_score < settings.early_abort_similarity_threshold:
            logger.info("mongodb_search_early_abort_db_miss", best_score=best_vector_score)
            return [RetrievedChunk(
                id="db_miss_chunk",
                text="System Notification: No documents in storage match the query topic.",
                score=0.0,
                source="system",
                metadata={"db_miss": True}
            )]

        # Check high-confidence reranking bypass
        if best_vector_score >= settings.skip_rerank_similarity_threshold:
            logger.info("mongodb_search_reranking_bypassed_high_confidence", best_score=best_vector_score)
            top_5 = top_20[:settings.rerank_top_k]
            for item in top_5:
                item["rerank_score"] = item["hybrid_score"]
        else:
            # ── STAGE 2: CROSS-ENCODER RERANKING ───────────────────
            candidate_texts = [x["text"] for x in top_20]
            # Execute reranking in thread executor (blocking call)
            loop = asyncio.get_event_loop()
            rerank_scores = await loop.run_in_executor(
                None,
                lambda: reranker_service.rerank(query, candidate_texts)
            )
            
            # Merge scores back
            for idx, score in enumerate(rerank_scores):
                top_20[idx]["rerank_score"] = score
                
            # Sort by rerank score and limit to Top 5 (user specified)
            top_20.sort(key=lambda x: x.get("rerank_score", -99.0), reverse=True)
            top_5 = top_20[:settings.rerank_top_k]
        
        logger.info(
            "mongodb_search_reranked",
            candidates_stage1=len(hybrid_list),
            candidates_stage2=len(top_20),
            returned=len(top_5),
            best_score=top_5[0].get("rerank_score") if top_5 else None
        )

        # ── STAGE 3: PARENT-CHILD EXPANSION ────────────────────
        final_chunks = []
        for item in top_5:
            doc_id = item["doc_id"]
            chunk_idx = item["metadata"].get("chunk_index", 0)
            
            # Retrieve expanded text and metadata
            expanded_text, summary_meta = await self._expand_chunk(doc_id, chunk_idx)
            
            # Fallback to original text if expansion fails
            display_text = expanded_text if expanded_text else item["text"]
            
            # Merge metadata
            final_meta = item["metadata"].copy()
            final_meta.update(summary_meta)
            
            final_chunks.append(RetrievedChunk(
                id=item["chunk_id"],
                text=display_text,
                score=item.get("rerank_score", 0.0),
                source=item["metadata"].get("filename", "mongodb"),
                metadata=final_meta
            ))
            
        return final_chunks

    async def health_check(self) -> bool:
        """Check connection to MongoDB."""
        return await mongodb_service.health_check()
