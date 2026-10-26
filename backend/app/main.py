import os
import sys
import re
import logging
import shutil
import time
import uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
from tinydb import Query

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
    from app.celery_worker import process_upload_task, process_ocr_task, master_upload_task
    from app.services.job_manager import create_job, get_job
    from app.services.auth import get_user, verify_password, create_access_token, get_current_user, users_table, pending_users_table, history_table, documents_table, generate_otp, send_otp_email, get_password_hash
except ModuleNotFoundError:
    from graphs.assistant_graph import corporate_agent_graph
    from services.sarvam_client import sarvam_client
    from services.rag_engine import rag_engine
    from celery_worker import process_upload_task, process_ocr_task, master_upload_task
    from services.job_manager import create_job, get_job
    from services.auth import get_user, verify_password, create_access_token, get_current_user, users_table, pending_users_table, history_table, documents_table, generate_otp, send_otp_email, get_password_hash

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

class SignupRequest(BaseModel):
    username: str
    email: str
    password: str
    role: str = "customer"

class VerifyOTPRequest(BaseModel):
    email: str
    otp: str

class LoginRequest(BaseModel):
    username: str
    password: str

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

@app.delete("/api/rag/clear")
async def clear_rag_memory(current_user = Depends(get_current_user)):
    """Clears the underlying ChromaDB and all uploaded documents."""
    try:
        # 1. Clear TinyDB Tracking records
        DocQuery = Query()
        documents_table.remove(DocQuery.username == current_user["username"])
        
        # 2. Clear RAG Vector Store
        if hasattr(rag_engine, 'clear_index'):
            rag_engine.clear_index()
            return {"success": True, "message": "Knowledge base cleared."}
        else:
            return {"success": False, "message": "RAG engine not initialized."}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/auth/signup")
async def signup(request: SignupRequest):
    role = request.role.lower()
    if role not in ["employee", "customer"]:
        raise HTTPException(status_code=400, detail="Invalid role.")
        
    if role == "employee":
        employee_domains = os.getenv("EMPLOYEE_DOMAINS", "@prixgen.com,@sarvam.ai").split(",")
        is_valid_domain = any(request.email.lower().endswith(domain) for domain in employee_domains)
        if not is_valid_domain:
            raise HTTPException(status_code=403, detail="Employees must use an official company email domain.")

    UserQuery = Query()
    if users_table.search((UserQuery.username == request.username) | (UserQuery.email == request.email)):
        raise HTTPException(status_code=400, detail="Username or email already registered")
        
    otp = generate_otp()
    email_sent = send_otp_email(request.email, otp)
    if not email_sent:
        raise HTTPException(status_code=500, detail="Failed to send verification email. Please check server configuration.")
        
    pending_users_table.remove(UserQuery.email == request.email)
    
    hashed_pw = get_password_hash(request.password)
    pending_user_doc = {
        "username": request.username,
        "email": request.email,
        "hashed_password": hashed_pw,
        "role": role,
        "otp": otp,
        "timestamp": time.time()
    }
    pending_users_table.insert(pending_user_doc)
    
    return {"message": "Verification code sent to email. Please verify to complete signup.", "status": "pending_verification"}

@app.post("/api/auth/verify-otp")
async def verify_otp(request: VerifyOTPRequest):
    UserQuery = Query()
    pending_user = pending_users_table.search(UserQuery.email == request.email)
    
    if not pending_user:
        raise HTTPException(status_code=404, detail="No pending signup found for this email.")
        
    pending_user = pending_user[0]
    
    # 5 minutes expiration
    if time.time() - pending_user["timestamp"] > 300:
        pending_users_table.remove(UserQuery.email == request.email)
        raise HTTPException(status_code=400, detail="OTP has expired. Please sign up again.")
        
    if pending_user["otp"] != request.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP code.")
        
    new_user = {
        "username": pending_user["username"],
        "email": pending_user["email"],
        "hashed_password": pending_user["hashed_password"],
        "role": pending_user["role"]
    }
    users_table.insert(new_user)
    pending_users_table.remove(UserQuery.email == request.email)
    
    access_token = create_access_token(data={"sub": new_user["username"]})
    return {"access_token": access_token, "token_type": "bearer", "username": new_user["username"], "role": new_user["role"]}

@app.post("/api/auth/login")
async def login(request: LoginRequest):
    user = get_user(request.username)
    if not user or not verify_password(request.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    access_token = create_access_token(data={"sub": user["username"]})
    return {"access_token": access_token, "token_type": "bearer", "username": user["username"], "role": user.get("role", "Customer")}

@app.post("/api/chat")
def chat_endpoint(request: ChatRequest, current_user = Depends(get_current_user)):
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
            "errors": [],
            "use_rag": request.use_rag,
            "fallback_message": ""
        }

        final_graph_state = corporate_agent_graph.invoke(initial_state)

        # Save to history_table
        HistoryQuery = Query()
        existing_session = history_table.search((HistoryQuery.session_id == session_id) & (HistoryQuery.username == current_user["username"]))
        new_messages = [
            {"role": "user", "content": user_query},
            {"role": "assistant", "content": final_graph_state["final_output"]}
        ]
        
        if existing_session:
            session_data = existing_session[0]
            session_data["messages"].extend(new_messages)
            history_table.update({"messages": session_data["messages"]}, (HistoryQuery.session_id == session_id) & (HistoryQuery.username == current_user["username"]))
        else:
            title = user_query[:40] + "..." if len(user_query) > 40 else user_query
            session_doc = {
                "session_id": session_id,
                "username": current_user["username"],
                "title": title,
                "timestamp": time.time(),
                "messages": new_messages
            }
            history_table.insert(session_doc)

        return {
            "source": "langgraph_agent_orchestrator",
            "response": final_graph_state["final_output"]  
        }

    except Exception as general_error:
        import traceback
        trace = traceback.format_exc()
        logger.error(f"Fatal server loop captured: {trace}")
@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...), current_user = Depends(get_current_user)):
    import tempfile
    job_id = str(uuid.uuid4())
    file_path = os.path.join(tempfile.gettempdir(), file.filename)
    try:
        file_bytes = await file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(file_bytes)
        
        # Log job in DB and send to Celery Master Task
        start_time = time.time()
        create_job(job_id, status="PENDING", start_time=start_time)
        master_upload_task.delay(job_id, file_path, file.filename, start_time)
        
        # Log document for user
        document_doc = {
            "username": current_user["username"],
            "filename": file.filename,
            "timestamp": time.time(),
            "job_id": job_id
        }
        documents_table.insert(document_doc)
        
        return {"job_id": job_id, "status": "PENDING"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history")
async def get_history(current_user = Depends(get_current_user)):
    HistoryQuery = Query()
    sessions = history_table.search(HistoryQuery.username == current_user["username"])
    sessions.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return {"sessions": sessions}

@app.delete("/api/history/{session_id}")
async def delete_history(session_id: str, current_user = Depends(get_current_user)):
    HistoryQuery = Query()
    session = history_table.search((HistoryQuery.session_id == session_id) & (HistoryQuery.username == current_user["username"]))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or not authorized")
    
    history_table.remove((HistoryQuery.session_id == session_id) & (HistoryQuery.username == current_user["username"]))
    return {"success": True, "message": "Session deleted"}

@app.get("/api/documents")
async def get_documents(current_user = Depends(get_current_user)):
    DocQuery = Query()
    docs = documents_table.search(DocQuery.username == current_user["username"])
    docs.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return {"documents": docs}

@app.post("/api/ocr")
async def ocr_endpoint(file: UploadFile = File(...), language_code: str = Form("en-IN"), current_user = Depends(get_current_user)):
    import tempfile
    job_id = str(uuid.uuid4())
    file_path = os.path.join(tempfile.gettempdir(), file.filename)
    try:
        file_bytes = await file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(file_bytes)
            
        start_time = time.time()
        create_job(job_id, status="PENDING", start_time=start_time)
        process_ocr_task.delay(job_id, file_path, file.filename, language_code, start_time)
        
        return {"job_id": job_id, "status": "PENDING"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    job_data = get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_data

@app.post("/api/clear-docs")
async def clear_documents(current_user = Depends(get_current_user)):
    try:
        if hasattr(rag_engine, 'clear_index'):
            rag_engine.clear_index()
            
        # Clear the jobs table so frontend UI is clean
        try:
            import app.services.job_manager as jm
            jm.clear_jobs()
        except Exception as e:
            print(f"Error clearing jobs: {e}")
            
        return {"success": True, "message": "Knowledge base cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stt")
async def speech_to_text_endpoint(file: UploadFile = File(...), mode: str = Form("transcribe"), language_code: str = Form("hi-IN"), current_user = Depends(get_current_user)):
    try:
        audio_bytes = await file.read()
        return sarvam_client.speech_to_text(audio_bytes=audio_bytes, filename=file.filename, mode=mode, language_code=language_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tts")
async def text_to_speech_endpoint(request: TTSRequest, current_user = Depends(get_current_user)):
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