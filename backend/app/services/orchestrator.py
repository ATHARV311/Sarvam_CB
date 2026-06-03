import os
import re
import json
import logging
import urllib.parse
from datetime import datetime
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, END

# Import your existing, working backend clients safely
from app.services.sarvam_client import sarvam_client, summarize_web_data
from app.services.rag_engine import rag_engine
from app.services.web_search_engine import search_tavily

logger = logging.getLogger(__name__)

# ─── 1. DEFINING UNIFIED SYSTEM AGENT STATE ───
class AgentState(TypedDict):
    query: str
    session_id: str
    extracted_lang: str
    target_directive: str
    cache_key: str
    history: List[Dict[str, str]]
    retrieved_context: str
    raw_search_results: str
    final_output: str
    next_step: str

# Paths for matching original database storage locations
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DB_DIR = os.path.join(BACKEND_ROOT, "db")
CACHE_FILE = os.path.join(DB_DIR, "conversation_cache.json")
HISTORY_FILE = os.path.join(DB_DIR, "conversation_history.json")

def load_json_db(file_path: str) -> dict:
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json_db(file_path: str, data: dict):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Graph disk state sync failed: {str(e)}")

# ─── 2. THE 6 MULTI-AGENT EXECUTION NODES ───

def memory_agent_node(state: AgentState) -> Dict[str, Any]:
    """Agent 6 (Memory): Loads historical context turns across unique session tracks."""
    logger.info("🧠 Agent 6 (Memory): Extracting conversation history from local database files...")
    history_db = load_json_db(HISTORY_FILE)
    session_history = history_db.get(state["session_id"], [])[-4:]  # Grab last 4 turns
    return {"history": session_history}

def supervisor_agent_node(state: AgentState) -> Dict[str, Any]:
    """Agent 4 (Supervisor): Intent classification, preprocessing, and static greeting intercepts."""
    logger.info("🤖 Agent 4 (Supervisor): Preprocessing intent classification pathways...")
    query_lower = state["query"].lower()
    
    # Check for direct local greeting shortcuts first
    greetings = ["hi", "hii", "hiii", "hello", "hey", "good morning", "good afternoon"]
    if any(word == query_lower for word in greetings):
        return {"next_step": "local_greeting_shortcut"}

    # Intent Classification Matrix
    if any(w in query_lower for w in ["email", "mail", "gmail", "send to", "draft a message to"]):
        next_step = "email_agent"
    elif any(w in query_lower for w in ["won", "match", "score", "weather", "latest", "today", "yesterday", "ipl", "live", "who is", "current", "news"]):
        next_step = "web_scraper"
    else:
        next_step = "rag_modulator"
        
    return {"next_step": next_step}

def rag_modulator_node(state: AgentState) -> Dict[str, Any]:
    """Agent 1 (RAG Modulator): Evaluates your vector database for document tracking segments."""
    logger.info("📁 Agent 1 (RAG Modulator): Scanning local vector indices for background chunks...")
    context = ""
    try:
        context = rag_engine.retrieve_context(state["query"], top_k=2) if hasattr(rag_engine, 'retrieve_context') else ""
    except Exception as e:
        logger.error(f"RAG file lookup error: {e}")

    # THE FEEDBACK LOOP LAYER: If RAG context is empty or unindexed, auto-route straight to Web Scraper!
    if not context or "0 chunks" in context:
        logger.warning("⚠️ RAG Agent detected empty files context. Executing self-correction loop to Web Scraper!")
        return {"retrieved_context": "", "next_step": "web_scraper"}
        
    return {"retrieved_context": context, "next_step": "sarvam_synthesizer"}

def web_scraper_node(state: AgentState) -> Dict[str, Any]:
    """Agent 2 (Web Scraper): Triggers live search crawlers using absolute time context."""
    logger.info("🌐 Agent 2 (Web Scraper): Running live web search crawlers...")
    query_lower = state["query"].lower()
    search_query = state["query"]
    
    # Original time-relative constraints logic for accurate current season indexing
    if "ipl" in query_lower and not re.search(r"\b20\d{2}\b", query_lower):
        current_year = datetime.now().year
        search_query = f"{state['query']} IPL {current_year}"

    raw_context = ""
    source_links = ""
    try:
        search_data = search_tavily(search_query)
        raw_context = search_data.get("context", "")
        sources = search_data.get("sources", [])
        if sources:
            source_links = "\n\n🔗 Sources:\n" + "\n".join(
                [f"- [{src.get('title','source')}]({src.get('url','#')})" for src in sources]
            )
    except Exception as e:
        logger.error(f"Tavily retrieval crash caught: {e}")
        raw_context = f"Web scraper failed: {str(e)}"

    # Attach any tracked links straight onto the background results string channel
    complete_web_data = raw_context + source_links if raw_context else ""
    return {"raw_search_results": complete_web_data, "next_step": "sarvam_web_summarizer"}

def email_agent_node(state: AgentState) -> Dict[str, Any]:
    """Agent 5 (Email): Generates professional email copy schemas with structured link deep-linking."""
    logger.info("✉️ Agent 5 (Email): Constructing tailored corporate communications drafts...")
    email_prompt = (
        f"Write a professional corporate email based on this request: '{state['query']}'.\n"
        f"Respond in this format:\n[RECIPIENT: email]\n[SUBJECT: subject]\n[BODY: complete body]"
    )
    try:
        api_res = sarvam_client.chat_complete(messages=[{"role": "user", "content": email_prompt}], model="sarvam-30b")
        ai_draft = api_res["choices"][0].get("message", {}).get("content", "") if "choices" in api_res else ""
    except Exception:
        ai_draft = "Placeholder email workspace backup draft template."

    gmail_link = f"https://mail.google.com/mail/?view=cm&fs=1&body={urllib.parse.quote(ai_draft)}"
    final_output = f"{ai_draft}\n\n🔗 **[Open Email in Gmail]({gmail_link})**"
    
    # Sync straight to tracking state structures
    return {"final_output": final_output, "next_step": "commit_to_memory"}

def sarvam_synthesizer_node(state: AgentState) -> Dict[str, Any]:
    """Agent 3 (Sarvam Core Synthesizer): Locks down multi-lingual scripts for localized RAG outputs."""
    logger.info("⚡ Agent 3 (Sarvam Core): Running language-locked text generation step...")
    
    system_prompt = (
        "You are a professional corporate virtual assistant. Your responses must be clear and business-appropriate.\n"
        f"CRITICAL DIRECTIVE: You MUST formulate your entire final response natively using the {state['target_directive']} alphabet characters.\n"
        "If the user does not specify any dates or timeframes, prioritize the most recent relevant information available.\n"
        "DO NOT write in Romanized phonetic script. Translate all provided reference text data into that script explicitly."
    )
    
    messages_payload = [{"role": "system", "content": system_prompt}]
    for turn in state["history"]:
        messages_payload.append({"role": "user", "content": turn["user"]})
        messages_payload.append({"role": "assistant", "content": turn["bot"]})
        
    messages_payload.append({
        "role": "user",
        "content": f"DOCUMENT CONTEXT:\n{state['retrieved_context']}\n\nUSER QUESTION:\n{state['query']}"
    })

    try:
        api_res = sarvam_client.chat_complete(messages=messages_payload, model="sarvam-30b", temperature=0.5)
        llm_response = api_res["choices"][0].get("message", {}).get("content", "") if "choices" in api_res else ""
    except Exception as e:
        llm_response = f"Failed to complete synthesis layer tracking: {str(e)}"

    return {"final_output": llm_response, "next_step": "commit_to_memory"}

def sarvam_web_summarizer_node(state: AgentState) -> Dict[str, Any]:
    """Agent 3 Fallback (Web Data Synthesizer): Formats live crawled contexts into preferred scripts."""
    logger.info("🌐⚡ Agent 3 (Web Synthesizer): Generating language-aware online summary...")
    try:
        llm_response = summarize_web_data(state["query"], state["raw_search_results"], target_language=state["extracted_lang"])
    except Exception as e:
        llm_response = f"Web content processing failed: {str(e)}"
    return {"final_output": llm_response, "next_step": "commit_to_memory"}

def local_greeting_node(state: AgentState) -> Dict[str, Any]:
    """Local Route: Instantly fires clean greeting dictionaries without wasting remote token requests."""
    language_replies = {
        "english": "Hello! How can I assist your corporate workflow today?",
        "hindi": "नमस्ते! आज मैं आपके कार्यप्रवाह में किस प्रकार सहायता कर सकता हूँ?",
        "bengali": "হ্যালো! আজ আমি আপনার কর্পোরেট ওয়ার্কফ্লোতে কীভাবে সহায়তা করতে পারি?",
        "tamil": "வணக்கம்! இன்று உங்கள் கார்ப்பரேட் பணிப்பாய்வுக்கு நான் எவ்வாறு உதவ முடியும்?",
        "telugu": "నమస్తే! ఈరోజు మీ కార్పొరేట్ వర్క్‌ఫ్లోలో నేను మీకు ఎలా సహాయపడగలను?",
        "kannada": "ನಮಸ್ಕಾರ! ಇಂದು ನಿಮ್ಮ ಕಾರ್ಪೊರೇಟ್ ಕೆಲಸದ ಹರಿವಿಗೆ ನಾನು ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು?",
        "malayalam": "ഹലോ! இன்று നിങ്ങളുടെ കോർപ്പറേറ്റ് വർക്ക്ഫ്ലോയിൽ എനിക്ക് എങ്ങനെ സഹായിക്കാനാകും?",
        "marathi": "नमस्कार! आज मी तुमच्या कॉर्पोरेट वर्कफ्लोमध्ये कशी मदत करू शकतो?",
        "gujarati": "હેલો! આજે હું તમારા કોર્પોરેట్ વર્કફ્લોમાં કેવી રીતે મદદ કરી શકું?",
        "punjabi": "ਸਤਿ ਸ਼੍ਰੀ ਅਕਾਲ! ਅੱਜ ਮੈਂ ਤੁਹਾਡੇ ਕਾਰਪੋਰੇਟ ਵਰਕਫਲੋ ਵਿੱਚ ਕਿਸ ਤਰ੍ਹਾਂ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ?"
    }
    reply = language_replies.get(state["extracted_lang"].lower(), "Hello! How can I assist your corporate workflow today?")
    return {"final_output": reply, "next_step": "commit_to_memory"}

def commit_cache_persistence_node(state: AgentState) -> Dict[str, Any]:
    """Persistence Layer: Syncs active execution logs into your persistent cache folders on disk."""
    logger.info("💾 Syncing conversational logs safely to persistent JSON memory assets...")
    
    cache_db = load_json_db(CACHE_FILE)
    history_db = load_json_db(HISTORY_FILE)
    
    # Save output into local caching tracking mechanisms
    cache_db[state["cache_key"]] = state["final_output"]
    history_db.setdefault(state["session_id"], []).append({"user": state["query"], "bot": state["final_output"]})
    
    save_json_db(CACHE_FILE, cache_db)
    save_json_db(HISTORY_FILE, history_db)
    return {"next_step": "end"}

# ─── 3. WIRED SYSTEM CONFIGURED COMPILATION GRAPH ───
workflow = StateGraph(AgentState)

# Register All Multi-Agent Nodes
workflow.add_node("memory_agent", memory_agent_node)
workflow.add_node("supervisor_agent", supervisor_agent_node)
workflow.add_node("rag_modulator", rag_modulator_node)
workflow.add_node("web_scraper", web_scraper_node)
workflow.add_node("email_agent", email_agent_node)
workflow.add_node("sarvam_synthesizer", sarvam_synthesizer_node)
workflow.add_node("sarvam_web_summarizer", sarvam_web_summarizer_node)
workflow.add_node("local_greeting_shortcut", local_greeting_node)
workflow.add_node("commit_to_memory", commit_cache_persistence_node)

# Set Core Entrance
workflow.set_entry_point("memory_agent")
workflow.add_edge("memory_agent", "supervisor_agent")

def router_edge(state: AgentState) -> str:
    return state["next_step"]

# Set Conditional Router Paths for Supervisor Agent
workflow.add_conditional_edges(
    "supervisor_agent",
    router_edge,
    {
        "local_greeting_shortcut": "local_greeting_shortcut",
        "rag_modulator": "rag_modulator",
        "web_scraper": "web_scraper",
        "email_agent": "email_agent"
    }
)

# Set Conditional Feedback loops for RAG Modulator Agent
workflow.add_conditional_edges(
    "rag_modulator",
    router_edge,
    {
        "web_scraper": "web_scraper",
        "sarvam_synthesizer": "sarvam_synthesizer"
    }
)

# Connect specialist execution routes directly to their processing stages
workflow.add_edge("web_scraper", "sarvam_web_summarizer")

# Converge all completed agent operations onto the file storage tracking memory node
workflow.add_edge("local_greeting_shortcut", "commit_to_memory")
workflow.add_edge("email_agent", "commit_to_memory")
workflow.add_edge("sarvam_synthesizer", "commit_to_memory")
workflow.add_edge("sarvam_web_summarizer", "commit_to_memory")

# Set Absolute Terminal End Points Configuration
workflow.add_conditional_edges("commit_to_memory", router_edge, {"end": END})

corporate_agent_graph = workflow.compile()