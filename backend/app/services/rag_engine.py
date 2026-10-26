import os
import re
import json
import warnings
import shutil
import requests
import tempfile

# Suppress CryptographyDeprecationWarning from pypdf import of ARC4
warnings.filterwarnings("ignore", message=".*ARC4 has been moved to cryptography.*")

from app.config import settings

from langchain_core.documents import Document
from langchain_community.document_loaders import PyMuPDFLoader, Docx2txtLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

class RAGEngine:
    def __init__(self):
        self.db_dir = os.path.join(tempfile.gettempdir(), "sarvam_chroma_db")
        self.metadata_path = os.path.join(tempfile.gettempdir(), "sarvam_documents_metadata.json")
        self.chunk_size = 500
        self.chunk_overlap = 50
        self.metadata = {"files": [], "total_chunks": 0}
        self.load_metadata()
        
        # Initialize HuggingFace Multilingual Embeddings with Vyakyarth
        self.embeddings = HuggingFaceEmbeddings(model_name="krutrim-ai-labs/Vyakyarth")
        
        # Initialize Vector Store
        self.vector_store = Chroma(persist_directory=self.db_dir, embedding_function=self.embeddings)

    def load_metadata(self):
        """Loads metadata from JSON database if it exists."""
        old_total = self.metadata.get("total_chunks", 0)
        if os.path.exists(self.metadata_path):
            try:
                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
            except Exception as e:
                print(f"Error loading metadata: {e}")
                self.metadata = {"files": [], "total_chunks": 0}
                
        # If a background Celery worker added chunks to the database, reload Chroma
        new_total = self.metadata.get("total_chunks", 0)
        if hasattr(self, 'vector_store') and new_total != old_total:
            print(f"🔄 Reloading ChromaDB Client! Chunks changed from {old_total} to {new_total}.")
            self.vector_store = Chroma(persist_directory=self.db_dir, embedding_function=self.embeddings)

    def save_metadata(self):
        """Saves current metadata to JSON database."""
        try:
            with open(self.metadata_path, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving metadata: {e}")

    def clear_index(self):
        """Clears all documents from RAG memory."""
        self.metadata = {"files": [], "total_chunks": 0}
        self.save_metadata()
        
        if os.path.exists(self.db_dir):
            self.vector_store.delete_collection()
            shutil.rmtree(self.db_dir, ignore_errors=True)
            self.vector_store = Chroma(persist_directory=self.db_dir, embedding_function=self.embeddings)
            
        # Clean uploaded files
        for f in os.listdir(settings.UPLOAD_DIR):
            file_path = os.path.join(settings.UPLOAD_DIR, f)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Error deleting file {file_path}: {e}")

    def add_document(self, file_path, filename, progress_callback=None):
        """Parses document and adds it to search index."""
        ext = os.path.splitext(filename)[1].lower()
        documents = []
        
        try:
            if ext == ".pdf":
                loader = PyMuPDFLoader(file_path)
                documents = loader.load()
            elif ext == ".docx":
                loader = Docx2txtLoader(file_path)
                documents = loader.load()
            elif ext in [".txt", ".md", ".json"]:
                loader = TextLoader(file_path, encoding="utf-8")
                documents = loader.load()
            else:
                return {"error": True, "message": f"Unsupported file extension: {ext}"}
        except Exception as e:
            return {"error": True, "message": f"Failed to parse document: {str(e)}"}
            
        if not documents:
            return {"error": True, "message": "No text content found in document."}

        # Add filename to metadata so we know where it came from
        for doc in documents:
            doc.metadata["source_file"] = filename

        # Create chunks
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
        chunks = text_splitter.split_documents(documents)
        
        if not chunks:
            return {"error": True, "message": "No text content extracted from document."}
            
        # Add chunks to repository
        # Avoid duplicate insertion by checking metadata (simplified approach)
        if filename not in self.metadata["files"]:
            self.metadata["files"].append(filename)
            
            # Batch add to Chroma
            batch_size = 100
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i+batch_size]
                self.vector_store.add_documents(documents=batch)
                
                if progress_callback:
                    progress_callback(i + len(batch), len(chunks))
                
            self.metadata["total_chunks"] += len(chunks)
            self.save_metadata()
            
        return {"success": True, "chunks_added": len(chunks), "total_chunks": self.metadata["total_chunks"]}

    def retrieve_context(self, query, top_k=3):
        """Retrieves top_k relevant text chunks as context for chatbot."""
        self.load_metadata() # Force reload from disk in case Celery updated it
        if not self.metadata["files"]:
            return ""
            
        # Retrieve context from Chroma based on semantic similarity
        docs = self.vector_store.similarity_search(query, k=top_k)
        if not docs:
            return ""

        context_parts = []
        for i, doc in enumerate(docs):
            source_file = doc.metadata.get("source_file", "Unknown Document")
            context_parts.append(
                f"--- [SOURCE DOCUMENT: {source_file} (Segment {i+1})] ---\n"
                f"{doc.page_content}"
            )
            
        return "\n\n".join(context_parts)
    
    def web_search(self, query: str, num_results: int = 3) -> tuple:
        """
        Searches the live web for company details or news.
        Returns a tuple of (context_string, list_of_sources)
        """
        search_api_key = os.getenv("WEB_SEARCH_API_KEY")
        if not search_api_key:
            return "", []

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": search_api_key,
            "query": query,
            "search_depth": "advanced"
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                results = response.json().get("results", [])
                
                context_parts = []
                sources = []
                
                for res in results[:num_results]:
                    title = res.get("title", "Web Source")
                    link = res.get("url", "")
                    content = res.get("content", "")
                    
                    sources.append(f"{title} ({link})")
                    context_parts.append(
                        f"--- [WEB SOURCE: {title}] ---\n"
                        f"URL: {link}\n"
                        f"Content: {content}"
                    )
                
                return "\n\n".join(context_parts), sources
            else:
                return f"Web search failed with status {response.status_code}", []
        except Exception as e:
            return f"Error executing web search: {str(e)}", []

    def get_all_sources(self):
        """Returns details about loaded files."""
        self.load_metadata() # Force reload from disk
        return {
            "total_documents": len(self.metadata["files"]),
            "files": self.metadata["files"],
            "total_chunks": self.metadata["total_chunks"]
        }

rag_engine = RAGEngine()
