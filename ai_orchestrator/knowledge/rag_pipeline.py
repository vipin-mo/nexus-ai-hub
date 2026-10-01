import sys
try:
    import pysqlite3
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    try:
        import sqlite3
    except ImportError:
        pass
import os
import chromadb
import traceback
from dotenv import load_dotenv
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, StorageContext, Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.ollama import OllamaEmbedding

# Load infrastructure environments
load_dotenv()

# Define project folder paths relative to this script context location
DOCS_DIR = os.path.join(os.path.dirname(__file__), "documents")
CHROMA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../data_pipeline/storage/chroma_db"))

# Local embedding engine initialization
local_embed_model = OllamaEmbedding(
    model_name="nomic-embed-text",
    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
)
Settings.embed_model = local_embed_model
Settings.llm = None  # Decouple text generation completely from the knowledge vector module

# Module-level cached vector index instance singleton
_RAG_INDEX = None

def get_or_create_index() -> VectorStoreIndex:
    """Instantiates the vector index schema singleton or serves the existing memory allocation."""
    global _RAG_INDEX
    if _RAG_INDEX is not None:
        return _RAG_INDEX

    # Initialize persistent DB engine client safely
    db = chromadb.PersistentClient(path=CHROMA_DIR)

    collection_name = "enterprise_knowledge"
    chroma_collection = db.get_or_create_collection(collection_name)
    collection_is_empty = chroma_collection.count() == 0

    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    if collection_is_empty:
        print("📦 [Vector RAG] Storage collection empty. Parsing and vectorizing raw text sources...")
        if not os.path.exists(DOCS_DIR) or not os.listdir(DOCS_DIR):
            return None

        documents = SimpleDirectoryReader(DOCS_DIR).load_data()
        _RAG_INDEX = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
    else:
        print("💾 [Vector RAG] Existing semantic layout indexes identified. Attaching storage contexts...")
        _RAG_INDEX = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_context)

    return _RAG_INDEX

def initialize_and_query_rag(query_str: str) -> str:
    """Queries vector records using a cached singleton structure without rebuilding data indexes."""
    try:
        index = get_or_create_index()
        if index is None:
            return "Knowledge database empty. Document repository directory missing context."

        # Fetch index collection size safely from standard storage references to determine k bounds
        # LlamaIndex vector store abstracts the underlying collection
        retriever = index.as_retriever(similarity_top_k=2)
        nodes = retriever.retrieve(query_str)

        if not nodes:
            return "No matching corporate records located inside vector database context."

        context_payload = "\n---\n".join([node.node.get_content() for node in nodes])
        return context_payload

    except Exception as e:
        traceback.print_exc()
        return f"Error executing local vector database retrieval operations: {str(e)}"

if __name__ == "__main__":
    print("Initializing local vector infrastructure and parsing workspace data...")
    sample_context = initialize_and_query_rag("What are our safety gates?")
    print("\nLocal Vector Match Retrieval Output Test:\n", sample_context)
