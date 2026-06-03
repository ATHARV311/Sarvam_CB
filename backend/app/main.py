import os
import sys
import re
import logging
import shutil
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional

try:
    import app.config as config
except ImportError:
    import config

# ─── RUNTIME WORKING DIRECTORY REGISTRATION ───
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))      # .../backend/app
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..")) # .../backend

if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

try:
    from dotenv import load_dotenv
    env_path = os.path.join(BACKEND_ROOT, ".env")
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except ImportError:
    print("⚠️ Missing python-dotenv reference package dependencies.")

try:
    from app.graphs.assistant_graph import corporate_agent_graph
    from app.services.sarvam_client import sarvam_client
    from app.services.rag_engine import rag_engine
except ModuleNotFoundError:
    from graphs.assistant_graph import corporate_agent_graph
    from services.sarvam_client import sarvam_client
    from services.rag_engine import rag_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Sarvam AI Agentic Corporate Assistant backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_DIR = os.path.join(BACKEND_ROOT, "db")
os.makedirs(DB_DIR, exist_ok=True)

# ─── SCHEMA DEFINITION BLOCK ───
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    query: Optional[str] = ""
    session_id: Optional[str] = "default_session"
    messages: Optional[List[Message]] = None
    model: Optional[str] = "sarvam-30b"
    use_rag: Optional[bool] = True
    temperature: Optional[float] = 0.5
    target_language: Optional[str] = "English"

    class Config:
        extra = "allow"

class TTSRequest(BaseModel):
    text: str
    language_code: Optional[str] = "hi-IN"
    speaker: Optional[str] = "ritu"
    pace: Optional[float] = 1.0

def normalize_target_language(raw_lang: str) -> str:
    if not raw_lang:
        return "English"

    normalized = str(raw_lang).strip().lower()
    language_code_map = {
        "en": "English", "en-in": "English", "english": "English",
        "hi": "Hindi", "hi-in": "Hindi", "hindi": "Hindi",
        "bn": "Bengali", "bn-in": "Bengali", "bengali": "Bengali",
        "ta": "Tamil", "ta-in": "Tamil", "tamil": "Tamil",
        "te": "Telugu", "te-in": "Telugu", "telugu": "Telugu",
        "kn": "Kannada", "kn-in": "Kannada", "kannada": "Kannada",
        "ml": "Malayalam", "ml-in": "Malayalam", "malayalam": "Malayalam",
        "mr": "Marathi", "mr-in": "Marathi", "marathi": "Marathi",
        "gu": "Gujarati", "gu-in": "Gujarati", "gujarati": "Gujarati",
        "pa": "Punjabi", "pa-in": "Punjabi", "punjabi": "Punjabi",
    }

    if normalized in language_code_map:
        return language_code_map[normalized]
    if "-" in normalized:
        prefix = normalized.split("-")[0]
        if prefix in language_code_map:
            return language_code_map[prefix]

    first_token = re.split(r'[\s\(\)]+', normalized)[0]
    if first_token in language_code_map:
        return language_code_map[first_token]

    return "English"

@app.get("/api/status")
async def get_status():
    try:
        sources = rag_engine.get_all_sources() if hasattr(rag_engine, 'get_all_sources') else []
        return {
            "status": "healthy", 
            "engine": "LangGraph Network Active", 
            "mode": "PRODUCTION",  
            "rag_stats": sources
        }
    except Exception as e:
        return {"status": "degraded", "error": str(e)}

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        session_id = request.session_id or "default_session"
        user_query = request.query.strip() if request.query else ""
        if not user_query and request.messages:
            for msg in reversed(request.messages):
                if msg.role == "user":
                    user_query = msg.content.strip()
                    break

        if not user_query:
            return {"response": "No active query detected."}

        # Language dropdown sync mappings
        raw_lang = request.target_language or "English"
        extra_data = request.model_extra if request.model_extra else {}
        if "target_lang" in extra_data and extra_data["target_lang"]:
            raw_lang = extra_data["target_lang"]
        elif "language" in extra_data and extra_data["language"]:
            raw_lang = extra_data["language"]

        extracted_lang = normalize_target_language(raw_lang)

        language_directives = {
            "English": "English text output format",
            "Hindi": "Hindi (हिंदी - देवनागरी लिपि)",
            "Marathi": "Marathi (मराठी)",
            "Tamil": "Tamil (தமிழ்)",
            "Telugu": "Telugu (తెలుగు)",
            "Gujarati": "Gujarati (ગુજરાતી)",
            "Bengali": "Bengali (বাংলা)",
            "Punjabi": "Punjabi (ਪੰਜਾਬੀ)"
        }
        target_directive = language_directives.get(extracted_lang, "English text output format")
        cache_key = f"{session_id}:{extracted_lang.lower()}:{user_query.lower()}"

        # Feed initial dictionary keys to multi-agent state machines
        initial_state = {
            "query": user_query,
            "session_id": session_id,
            "extracted_lang": extracted_lang,
            "target_directive": target_directive,
            "cache_key": cache_key,
            "history": [],
            "retrieved_context": "",
            "raw_search_results": "",
            "final_output": "",
            "next_step": "",
            "errors": []
        }

        final_graph_state = corporate_agent_graph.invoke(initial_state)

        return {
            "source": "langgraph_agent_orchestrator",
            "response": final_graph_state["final_output"]  
        }

    except Exception as general_error:
        logger.error(f"Fatal server loop captured: {str(general_error)}")
        return {"source": "error", "response": f"Backend Error Code: {str(general_error)}"}

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    file_path = os.path.join(DB_DIR, file.filename)
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        index_result = rag_engine.add_document(file_path, file.filename) if hasattr(rag_engine, 'add_document') else "RAG indexed block."
        return {"filename": file.filename, "success": True, "details": index_result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stt")
async def speech_to_text_endpoint(file: UploadFile = File(...), mode: str = Form("transcribe"), language_code: str = Form("hi-IN")):
    try:
        audio_bytes = await file.read()
        return sarvam_client.speech_to_text(audio_bytes=audio_bytes, filename=file.filename, mode=mode, language_code=language_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tts")
async def text_to_speech_endpoint(request: TTSRequest):
    try:
        return sarvam_client.text_to_speech(text=request.text, language_code=request.language_code, speaker=request.speaker, pace=request.pace)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

FRONTEND_DIR = os.path.abspath(os.path.join(BACKEND_ROOT, "..", "frontend"))
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    # Lock execution loops down by disabling unsafe hot-reload threads
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False) 