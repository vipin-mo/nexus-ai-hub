import os
import chromadb
import traceback
from dotenv import load_dotenv
from chromadb.config import Settings as ChromaSettings
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

def initialize_and_query_rag(query_str: str) -> str:
    """Loads documents, persistent structures, and queries vector records without rebuilding data indexes."""
    try:
        # Initialize persistent DB engine client safely
        db = chromadb.PersistentClient(
            path=CHROMA_DIR,
            settings=ChromaSettings(anonymized_telemetry=False)
        )

        # Retrieve collection count parameters or initialize fresh index schemas
        collection_name = "enterprise_knowledge"
        chroma_collection = db.get_or_create_collection(collection_name)
        collection_is_empty = chroma_collection.count() == 0

        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        if collection_is_empty:
            print("📦 [Vector RAG] Storage collection empty. Parsing and vectorizing raw text sources...")
            if not os.path.exists(DOCS_DIR) or not os.listdir(DOCS_DIR):
                return "Knowledge database empty. Document repository directory missing context."

            documents = SimpleDirectoryReader(DOCS_DIR).load_data()
            index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
        else:
            print("💾 [Vector RAG] Existing semantic layout indexes identified. Attaching storage contexts...")
            index = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_context)

        # Configure dynamic context distance search criteria matching true file metrics
        available_elements = chroma_collection.count()
        target_k = min(2, available_elements) if available_elements > 0 else 1

        retriever = index.as_retriever(similarity_top_k=target_k)
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
