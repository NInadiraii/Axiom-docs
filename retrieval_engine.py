"""
Retrieval engine — FAISS-backed contextual search over uploaded PDFs.
Uses LangChain + sentence-transformers for embedding.
"""

import os
from pathlib import Path

# Lazy imports so the app starts even if heavy deps aren't installed yet.
_faiss_store = None  # single shared FAISS index (demo; production = per-user)
_doc_registry: list[dict] = []  # [{filename, pages, chunks}]

VECTOR_DIR = Path(__file__).parent / "vectorstores"
VECTOR_DIR.mkdir(exist_ok=True)

EMBED_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150


def _get_embeddings():
    from langchain_community.embeddings import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=EMBED_MODEL)


def ingest_pdf(file_path: str, filename: str) -> dict:
    """Load a PDF, chunk it, embed, and add to the FAISS index."""
    global _faiss_store

    from langchain_community.document_loaders import PyPDFLoader
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    from langchain_community.vectorstores import FAISS

    loader = PyPDFLoader(file_path)
    pages = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(pages)

    # Tag each chunk with the source filename
    for chunk in chunks:
        chunk.metadata.setdefault("source", filename)

    embeddings = _get_embeddings()

    if _faiss_store is None:
        _faiss_store = FAISS.from_documents(chunks, embeddings)
    else:
        _faiss_store.add_documents(chunks)

    _doc_registry.append({
        "filename": filename,
        "pages": len(pages),
        "chunks": len(chunks),
    })

    return {
        "filename": filename,
        "pages": len(pages),
        "chunks": len(chunks),
    }


def contextual_search(query: str, k: int = 5) -> list[dict]:
    """Return the top-k most relevant chunks for the given query."""
    if _faiss_store is None:
        return []

    embeddings = _get_embeddings()
    results = _faiss_store.similarity_search_with_score(query, k=k)

    return [
        {
            "text": doc.page_content,
            "source": doc.metadata.get("source", "unknown"),
            "page": doc.metadata.get("page", 0),
            "score": float(score),
        }
        for doc, score in results
    ]


def list_documents() -> list[dict]:
    return list(_doc_registry)
