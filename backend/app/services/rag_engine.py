import os
import re
import json
import math
import warnings
import requests

# Suppress CryptographyDeprecationWarning from pypdf import of ARC4
warnings.filterwarnings("ignore", message=".*ARC4 has been moved to cryptography.*")

from pypdf import PdfReader
from app.config import settings

class RAGEngine:
    def __init__(self):
        self.index_path = os.path.join(settings.DB_DIR, "documents_index.json")
        self.documents = []  # List of chunks: {"id": str, "file": str, "text": str}
        self.load_index()

    def load_index(self):
        """Loads index from JSON database if it exists."""
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    self.documents = json.load(f)
            except Exception as e:
                print(f"Error loading index: {e}")
                self.documents = []

    def save_index(self):
        """Saves current chunks to JSON database."""
        try:
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump(self.documents, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving index: {e}")

    def clear_index(self):
        """Clears all documents from RAG memory."""
        self.documents = []
        self.save_index()
        # Clean uploaded files
        for f in os.listdir(settings.UPLOAD_DIR):
            file_path = os.path.join(settings.UPLOAD_DIR, f)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Error deleting file {file_path}: {e}")

    def add_document(self, file_path, filename):
        """Parses document and adds it to search index."""
        text = ""
        ext = os.path.splitext(filename)[1].lower()
        
        try:
            if ext == ".pdf":
                reader = PdfReader(file_path)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            elif ext in [".txt", ".md", ".json"]:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            else:
                return {"error": True, "message": f"Unsupported file extension: {ext}"}
        except Exception as e:
            return {"error": True, "message": f"Failed to parse document: {str(e)}"}
            
        if not text.strip():
            return {"error": True, "message": "No text content found in document."}

        # Create chunks
        chunks = self.chunk_text(text)
        
        # Add chunks to repository
        new_chunks_count = 0
        for i, chunk in enumerate(chunks):
            chunk_id = f"{filename}_{i}"
            # Avoid duplicate insertion
            if not any(doc["id"] == chunk_id for doc in self.documents):
                self.documents.append({
                    "id": chunk_id,
                    "file": filename,
                    "text": chunk.strip()
                })
                new_chunks_count += 1
                
        self.save_index()
        return {"success": True, "chunks_added": new_chunks_count, "total_chunks": len(chunks)}

    def chunk_text(self, text, chunk_size=800, overlap=150):
        """Chunks text based on characters while preserving sentence structures where possible."""
        # Simple splitting by sentences/newlines to avoid cutting words in half
        paragraphs = re.split(r'\n+', text)
        chunks = []
        current_chunk = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
                
            # If paragraph itself is too large, split by sentence or length
            if len(para) > chunk_size:
                sentences = re.split(r'(?<=[.!?])\s+', para)
                for sent in sentences:
                    if len(current_chunk) + len(sent) < chunk_size:
                        current_chunk += " " + sent
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        # Handle very long sentences
                        if len(sent) > chunk_size:
                            # Hard split
                            words = sent.split(" ")
                            sub_chunk = ""
                            for word in words:
                                if len(sub_chunk) + len(word) < chunk_size:
                                    sub_chunk += " " + word
                                else:
                                    chunks.append(sub_chunk.strip())
                                    sub_chunk = word
                            current_chunk = sub_chunk
                        else:
                            current_chunk = sent
            else:
                if len(current_chunk) + len(para) < chunk_size:
                    current_chunk += "\n" + para
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = para
                    
        if current_chunk:
            chunks.append(current_chunk.strip())
            
        # Optional: Add overlap chunks (simplified overlap generation)
        return chunks

    def tokenize(self, text):
        """Cleans and tokenizes text for keyword matching."""
        # Lowercase and filter out non-alphanumeric
        cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower())
        tokens = cleaned.split()
        # Filter stop words (rudimentary)
        stopwords = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with", "is", "are", "was", "were", "of", "it", "this", "that", "these", "those"}
        return [t for t in tokens if t not in stopwords and len(t) > 1]

    def get_tfidf_scores(self, query):
        """
        Computes a simple but highly effective TF-IDF score for each document chunk.
        """
        query_tokens = self.tokenize(query)
        if not query_tokens or not self.documents:
            return []

        # Count DF (Document Frequency) of query tokens
        df = {}
        for token in query_tokens:
            df[token] = sum(1 for doc in self.documents if token in self.tokenize(doc["text"]))

        # Compute IDF
        N = len(self.documents)
        idf = {}
        for token, count in df.items():
            # Apply smooth IDF
            idf[token] = math.log((N + 1) / (count + 1)) + 1

        scores = []
        for doc in self.documents:
            doc_tokens = self.tokenize(doc["text"])
            if not doc_tokens:
                continue
                
            # Compute term frequencies and score
            doc_len = len(doc_tokens)
            score = 0.0
            matched_terms = []
            
            for token in query_tokens:
                tf = doc_tokens.count(token) / doc_len
                if tf > 0:
                    score += tf * idf[token]
                    matched_terms.append(token)
            
            if score > 0:
                scores.append({
                    "document": doc,
                    "score": score,
                    "matched_terms": list(set(matched_terms))
                })
                
        # Sort by score descending
        scores.sort(key=lambda x: x["score"], reverse=True)
        return scores

    def retrieve_context(self, query, top_k=3):
        """Retrieves top_k relevant text chunks as context for chatbot."""
        if not self.documents:
            return ""
            
        results = self.get_tfidf_scores(query)
        if not results:
            return ""

        context_parts = []
        for i, res in enumerate(results[:top_k]):
            doc = res["document"]
            context_parts.append(
                f"--- [SOURCE DOCUMENT: {doc['file']} (Segment {i+1})] ---\n"
                f"{doc['text']}"
            )
            
        return "\n\n".join(context_parts)
    
    def web_search(self, query: str, num_results: int = 3) -> tuple:
        """
        Searches the live web for company details or news.
        Returns a tuple of (context_string, list_of_sources)
        """
        import requests  # Imported here or at the top of the file
        
        search_api_key = os.getenv("WEB_SEARCH_API_KEY")
        if not search_api_key:
            return "", []

        # Example utilizing the Tavily Search API
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
                        f"--- [WEB SOURCE: {title}] ---\\n"
                        f"URL: {link}\\n"
                        f"Content: {content}"
                    )
                
                return "\n\n".join(context_parts), sources
            else:
                return f"Web search failed with status {response.status_code}", []
        except Exception as e:
            return f"Error executing web search: {str(e)}", []

    def get_all_sources(self):
        """Returns details about loaded files."""
        files = list(set(doc["file"] for doc in self.documents))
        return {
            "total_documents": len(files),
            "files": files,
            "total_chunks": len(self.documents)
        }

rag_engine = RAGEngine()
