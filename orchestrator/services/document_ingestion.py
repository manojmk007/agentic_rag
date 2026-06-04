"""
orchestrator/services/document_ingestion.py
=============================================
Document Ingestion Service.
Parses, cleans, chunks, embeds, and saves uploaded documents to MongoDB.
"""

import io
import re
import uuid
import hashlib
import datetime
from typing import Optional

from orchestrator.config.settings import settings
from orchestrator.services.embedder_service import embedder_service
from orchestrator.services.mongodb_service import mongodb_service
from orchestrator.services.observability import get_logger, track_latency

logger = get_logger(__name__)


class DocumentIngestionService:
    """Handles parsing, cleaning, chunking, and database ingestion of documents."""

    @staticmethod
    def calculate_doc_id(file_bytes: bytes, filename: str) -> str:
        """Calculate a deterministic document ID based on file content and name."""
        hasher = hashlib.sha256()
        hasher.update(file_bytes)
        hasher.update(filename.encode("utf-8", errors="ignore"))
        return hasher.hexdigest()

    def parse_document(self, file_bytes: bytes, filename: str) -> str:
        """Extract text content from file based on extension."""
        ext = filename.split(".")[-1].lower()
        
        if ext == "txt":
            return file_bytes.decode("utf-8", errors="ignore")
            
        elif ext == "docx":
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            # Extract paragraphs, omitting empty ones
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)
            
        elif ext == "pdf":
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text and text.strip():
                    pages.append(text.strip())
            return "\n\n".join(pages)
            
        else:
            raise ValueError(f"Unsupported file format: .{ext}")

    @staticmethod
    def clean_text(text: str) -> str:
        """Clean and normalize extracted document text."""
        # 1. Split by line, strip whitespace, and normalize spaces
        lines = [re.sub(r"[ \t]+", " ", line.strip()) for line in text.splitlines()]
        
        # 2. Join lines back
        text = "\n".join(lines)
        
        # 3. Limit consecutive newlines to at most 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        return text.strip()

    def chunk_text_adaptive(self, text: str) -> list[dict]:
        """
        Adaptive Semantic Chunking.
        Groups sentences together up to settings.chunk_size words.
        Maintains an overlap of settings.chunk_overlap words.
        """
        # Split text into paragraphs first
        paragraphs = text.split("\n\n")
        
        sentences_with_meta = []
        sentence_end_regex = re.compile(r'(?<=[.!?])\s+')
        
        current_paragraph_idx = 0
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            # Split paragraph into sentences
            sentences = sentence_end_regex.split(para)
            for sentence in sentences:
                sentence = sentence.strip()
                if sentence:
                    sentences_with_meta.append({
                        "text": sentence,
                        "paragraph_index": current_paragraph_idx
                    })
            current_paragraph_idx += 1

        chunks = []
        if not sentences_with_meta:
            return chunks

        # Sliding window chunking based on word count
        current_sentences = []
        current_word_count = 0
        chunk_index = 0

        target_size = settings.chunk_size
        overlap_size = settings.chunk_overlap

        for item in sentences_with_meta:
            sentence_text = item["text"]
            sentence_words = len(sentence_text.split())
            
            # If a single sentence is extremely long, we may need to split it by character length
            if sentence_words > target_size and not current_sentences:
                # Add it as its own chunk
                chunks.append({
                    "text": sentence_text,
                    "metadata": {
                        "chunk_index": chunk_index,
                        "paragraph_index": item["paragraph_index"],
                        "word_count": sentence_words
                    }
                })
                chunk_index += 1
                continue

            # If adding this sentence exceeds target size, save the current chunk first
            if current_word_count + sentence_words > target_size and current_sentences:
                chunk_text = " ".join([s["text"] for s in current_sentences])
                chunks.append({
                    "text": chunk_text,
                    "metadata": {
                        "chunk_index": chunk_index,
                        "paragraph_index": current_sentences[0]["paragraph_index"],
                        "word_count": len(chunk_text.split())
                    }
                })
                chunk_index += 1
                
                # Roll back sliding window for overlap
                # Keep removing sentences from the start until the remaining word count is below overlap_size
                while len(current_sentences) > 1:
                    first_sent_words = len(current_sentences[0]["text"].split())
                    if current_word_count - first_sent_words < overlap_size:
                        break
                    current_sentences.pop(0)
                    current_word_count -= first_sent_words
                
                # Pop one more sentence if we're still over overlap size just to stay safe, but keep at least one
                if len(current_sentences) > 1 and current_word_count > overlap_size:
                    removed = current_sentences.pop(0)
                    current_word_count -= len(removed["text"].split())

            current_sentences.append(item)
            current_word_count += sentence_words

        # Add the remaining sentences as the last chunk
        if current_sentences:
            chunk_text = " ".join([s["text"] for s in current_sentences])
            chunks.append({
                "text": chunk_text,
                "metadata": {
                    "chunk_index": chunk_index,
                    "paragraph_index": current_sentences[0]["paragraph_index"],
                    "word_count": len(chunk_text.split())
                }
            })

        return chunks

    @track_latency("ingest_document")
    async def ingest_document(
        self,
        file_bytes: bytes,
        filename: str,
        tenant_id: Optional[str] = None,
        category: Optional[str] = None,
        additional_metadata: Optional[dict] = None
    ) -> dict:
        """
        Runs the full ingestion pipeline: parse, clean, chunk, embed, and store in MongoDB.
        Determines duplicates based on content hash.
        """
        doc_id = self.calculate_doc_id(file_bytes, filename)
        
        # Check if document already exists
        existing = await mongodb_service.document_chunks.find_one({"doc_id": doc_id})
        if existing:
            logger.info("document_ingestion_duplicate", filename=filename, doc_id=doc_id)
            return {
                "status": "success",
                "message": "Document already ingested (duplicate skipped)",
                "doc_id": doc_id,
                "chunks_count": await mongodb_service.document_chunks.count_documents({"doc_id": doc_id}),
                "filename": filename
            }

        # 1. Parse Document
        raw_text = self.parse_document(file_bytes, filename)
        if not raw_text.strip():
            raise ValueError(f"Extracted text from '{filename}' is empty")

        # 2. Clean Text
        cleaned_text = self.clean_text(raw_text)

        # 3. Adaptive Chunking
        chunks = self.chunk_text_adaptive(cleaned_text)
        if not chunks:
            raise ValueError(f"No chunks generated for document '{filename}'")

        # 4. Generate Embeddings
        chunk_texts = [c["text"] for c in chunks]
        embeddings = await embedder_service.embed_batch(chunk_texts)

        # 5. Enrich and Store
        now = datetime.datetime.utcnow().isoformat()
        db_documents = []
        for i, chunk in enumerate(chunks):
            # Base metadata
            meta = {
                "filename": filename,
                "chunk_index": chunk["metadata"]["chunk_index"],
                "paragraph_index": chunk["metadata"]["paragraph_index"],
                "word_count": chunk["metadata"]["word_count"],
                "uploaded_at": now,
                "tenant_id": tenant_id or "default",
                "category": category or "general"
            }
            if additional_metadata:
                meta.update(additional_metadata)

            db_documents.append({
                "doc_id": doc_id,
                "chunk_id": f"{doc_id}_{i}",
                "text": chunk["text"],
                "embedding": embeddings[i],
                "metadata": meta
            })

        # Insert to MongoDB
        await mongodb_service.document_chunks.insert_many(db_documents)
        logger.info(
            "document_ingested",
            filename=filename,
            doc_id=doc_id,
            chunks=len(db_documents),
            tenant_id=tenant_id
        )

        return {
            "status": "success",
            "message": "Document ingested successfully",
            "doc_id": doc_id,
            "chunks_count": len(db_documents),
            "filename": filename
        }

    async def delete_document(self, doc_id: str) -> bool:
        """Delete all chunks associated with a document ID."""
        result = await mongodb_service.document_chunks.delete_many({"doc_id": doc_id})
        deleted = result.deleted_count > 0
        if deleted:
            logger.info("document_deleted", doc_id=doc_id, chunks_deleted=result.deleted_count)
        return deleted


# Module-level singleton
document_ingestion_service = DocumentIngestionService()
