# backend/app/graphs/assistant_graph.py
import os
import re
import json
import logging
import urllib.parse
from datetime import datetime
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, END

# Import working service clients safely
from app.services.sarvam_client import sarvam_client
from app.services.rag_engine import rag_engine
from app.services.web_search_engine import search_tavily

logger = logging.getLogger(__name__)

# ─── 1. SYSTEM AGENT STATE DEFINITION ───
class AgentState(TypedDict):
    query: str
    session_id: str
    extracted_lang: str
    target_directive: str
    cache_key: str
    history: List[Dict[str, str]]
    
    # New bridging variables
    agent_response: str
    agent_type: str
    
    final_output: str
    next_step: str
    errors: List[str]

# Local DB persistence tracks
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

# ─── 2. THE MULTI-AGENT COOPERATIVE NODES ───

def memory_agent_node(state: AgentState) -> Dict[str, Any]:
    """Agent 6 (Memory): Loads conversation history for localized short-term context windowing."""
    logger.info("🧠 Agent 6 (Memory): Fetching short-term conversational session blocks...")
    history_db = load_json_db(HISTORY_FILE)
    session_history = history_db.get(state["session_id"], [])[-4:]  # Slice the last 4 exchanges
    return {"history": session_history, "next_step": "supervisor_agent"}


def supervisor_agent_node(state: AgentState) -> Dict[str, Any]:
    """
    Agent 4 (Supervisor Orchestrator): The central LLM-based router.
    Intelligently identifies user intent to pass work to the correct specialized agent.
    """
    logger.info("🤖 Agent 4 (Supervisor Monitor): Classifying intent via LLM...")
    query = state.get("query", "").strip()
    
    prompt = f"""Classify this query into one of these exact categories: CHAT, RAG, WEB, EMAIL.
- EMAIL: user wants to draft, write, or send an email.
- WEB: user asks for latest news, live scores, current affairs, or anything requiring live internet/external data.
- RAG: user asks about uploaded documents, company policy, HR rules, or internal pdfs.
- CHAT: user says hello, asks for date/time, or engages in casual conversation.

Query: '{query}'
Reply ONLY with the category name (CHAT, RAG, WEB, or EMAIL) and nothing else."""

    try:
        res = sarvam_client.chat_complete(messages=[{"role": "user", "content": prompt}], model="sarvam-30b", temperature=0.1)
        intent = res["choices"][0].get("message", {}).get("content", "").strip().upper()
    except Exception as e:
        logger.error(f"Supervisor LLM classification failed: {e}")
        intent = "CHAT"
        
    logger.info(f"🎯 Supervisor Intent Evaluated: {intent}")

    if "EMAIL" in intent:
        return {"next_step": "email_agent"}
    elif "WEB" in intent:
        return {"next_step": "web_scraper"}
    elif "RAG" in intent:
        return {"next_step": "rag_modulator"}
    else:
        return {"next_step": "general_chat_agent"}


def general_chat_agent_node(state: AgentState) -> Dict[str, Any]:
    """Agent: Handles generic chatting and dynamic date/time injection."""
    logger.info("💬 Running General Chat Agent...")
    query_lower = state.get("query", "").lower()
    
    if "date" in query_lower or "time" in query_lower or "day" in query_lower or "today" in query_lower:
        now = datetime.now().strftime("%B %d, %Y, %I:%M %p")
        response = f"Today's date and time is: {now}."
    else:
        language_replies = {
            "english": "Hello! How can I assist your corporate workflow today?",
            "hindi": "नमस्ते! आज मैं आपके कार्यप्रवाह में किस प्रकार सहायता कर सकता हूँ?",
            "bengali": "হ্যালো! আজ আমি আপনার কর্পোরেট ওয়ার্কফ্লোতে কীভাবে সহায়তা করতে পারি?",
            "tamil": "வணக்கம்! இன்று உங்கள் கார்ப்பரேட் பணிப்பாய்வுக்கு நான் எவ்வாறு உதவ முடியும்?",
            "telugu": "నమస్తే! ఈరోజు మీ కార్పొరేట్ వర్క్‌ఫ్లోలో నేను మీకు ఎలా సహాయపడగలను?",
            "kannada": "ನಮಸ್ಕಾರ! ಇಂದು ನಿಮ್ಮ ಕಾರ್ಪೊರೇಟ್ ಕೆಲಸದ ಹರಿವಿಗೆ ನಾನು ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು?",
            "malayalam": "ഹലോ! ഇന്ന് നിങ്ങളുടെ കോർപ്പറേറ്റ് വർക്ക്ഫ്ലോയിൽ എനിക്ക് എങ്ങനെ സഹായിക്കാനാകും?",
            "marathi": "नमस्कार! आज मी तुमच्या कॉर्पोरेट वर्कफ्लोमध्ये कशी मदत करू शकतो?",
            "gujarati": "હેલો! આજે હું તમારા કોર્પોરેట్ વર્કફ્লোમાં કેવી રીતે મદદ કરી શકું?",
            "punjabi": "ਸਤਿ ਸ਼੍ਰੀ ਅਕਾਲ! ਅੱਜ ਮੈਂ ਤੁਹਾਡੇ ਕਾਰਪੋਰੇਟ ਵਰਕਫਲੋ ਵਿੱਚ ਕਿਸ ਤਰ੍ਹਾਂ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ?"
        }
        response = language_replies.get(state.get("extracted_lang", "English").lower(), "Hello! How can I assist your corporate workflow today?")
        
    return {"agent_response": response, "agent_type": "CHAT", "next_step": "supervisor_synthesizer"}


def rag_modulator_node(state: AgentState) -> Dict[str, Any]:
    """Agent 1 (RAG Modulator): Scans document embeddings."""
    logger.info("📁 Agent 1 (RAG Modulator): Extracting local document vector data segments...")
    errors = list(state.get("errors", []))
    try:
        context = rag_engine.retrieve_context(state["query"], top_k=2) if hasattr(rag_engine, 'retrieve_context') else ""
        if not context or "0 chunks" in context:
            context = "No relevant context found in internal company documents."
        return {"agent_response": context, "agent_type": "RAG", "next_step": "supervisor_synthesizer"}
    except Exception as e:
        logger.error(f"RAG Modulator Pipeline Interrupted: {e}")
        errors.append(f"rag_failed: {str(e)}")
        return {"agent_response": "", "agent_type": "RAG", "errors": errors, "next_step": "supervisor_synthesizer"}


def web_scraper_node(state: AgentState) -> Dict[str, Any]:
    """Agent 2 (Web Scraper): Injects temporal search targets and appends strict markdown web references."""
    logger.info("🌐 Agent 2 (Web Scraper): Running optimized web search crawlers...")
    query_lower = state["query"].lower().strip()
    search_query = state["query"]
    errors = list(state.get("errors", []))
    
    current_year = datetime.now().year  

    if any(q in query_lower for q in ["today's news", "todays news", "news", "updates", "headlines"]):
        search_query = f"{search_query} latest breaking India world news headlines {current_year} Reuters NDTV politics financial metrics"
    elif "ipl" in query_lower and not re.search(r"\b20\d{2}\b", query_lower):
        search_query = f"{search_query} IPL {current_year} tournament scores details"

    try:
        search_data = search_tavily(search_query)
        raw_context = search_data.get("context", "") or ""
        sources = search_data.get("sources", []) or []
        
        raw_context = raw_context.replace("Summary Answer: ", "").strip()
        
        formatted_sources = []
        for src in sources[:10]:
            title = src.get("title") or "Verified Source Reference"
            url = src.get("url") or "#"
            formatted_sources.append(f"* [{title.strip()}]({url.strip()})")

        if formatted_sources:
            raw_context += "\n\n### Sources\n" + "\n".join(formatted_sources)
        
        logger.info(f"✅ Web Scraper extracted data from {len(formatted_sources)} reference nodes.")
        return {"agent_response": raw_context, "agent_type": "WEB", "next_step": "supervisor_synthesizer"}
    except Exception as e:
        logger.error(f"Web Scraper Pipeline Failure: {e}")
        errors.append(f"web_scraper_failed: {str(e)}")
        return {"agent_response": "", "agent_type": "WEB", "errors": errors, "next_step": "supervisor_synthesizer"}


def email_agent_node(state: AgentState) -> Dict[str, Any]:
    """Agent 5 (Email): Generates tailored communication schemas."""
    logger.info("✉️ Agent 5 (Email): Building tailored communications templates...")
    target_lang = state.get("target_directive", "English text output format")
    
    email_prompt = (
        f"Write a polished professional business email layout based on this request: '{state['query']}'.\n"
        f"CRITICAL REQUIREMENT: You must write the email completely in this language format: {target_lang}.\n"
        f"Respond using this exact plain structural alignment without extra comments:\n"
        f"[RECIPIENT: Email address entry]\n"
        f"[SUBJECT: Subject Line]\n"
        f"[BODY: Clear business message text]"
    )
    try:
        api_res = sarvam_client.chat_complete(messages=[{"role": "user", "content": email_prompt}], model="sarvam-30b")
        ai_draft = api_res["choices"][0].get("message", {}).get("content", "") if "choices" in api_res else ""
    except Exception:
        ai_draft = "[RECIPIENT: ]\n[SUBJECT: Backup Template]\n[BODY: Backup communications framework template container.]"

    recipient = ""
    subject = ""
    body_text = ai_draft

    rec_match = re.search(r"\[RECIPIENT:\s*(.*?)\]", ai_draft, re.IGNORECASE)
    sub_match = re.search(r"\[SUBJECT:\s*(.*?)\]", ai_draft, re.IGNORECASE)
    body_match = re.search(r"\[BODY:\s*(.*?)\]", ai_draft, re.IGNORECASE | re.DOTALL)

    if rec_match: recipient = rec_match.group(1).strip()
    if sub_match: subject = sub_match.group(1).strip()
    if body_match: body_text = body_match.group(1).strip()

    safe_rec = urllib.parse.quote(recipient)
    safe_sub = urllib.parse.quote(subject)
    safe_body = urllib.parse.quote(body_text)

    mailto_link = f"mailto:{safe_rec}?subject={safe_sub}&body={safe_body}"
    gmail_link = f"https://mail.google.com/mail/u/0/?view=cm&fs=1&to={safe_rec}&su={safe_sub}&body={safe_body}"
    
    final_output = f"{ai_draft}\n\n🔗 **[Open in Default App]({mailto_link})**  |  🔗 **[Open in Gmail]({gmail_link})**"
    
    return {"agent_response": final_output, "agent_type": "EMAIL", "next_step": "supervisor_synthesizer"}


def supervisor_synthesizer_node(state: AgentState) -> Dict[str, Any]:
    """
    Supervisor Synthesizer (The Bridge): Formats raw agent responses perfectly for the user.
    Handles distinct formats depending on the agent type (RAG vs WEB vs EMAIL).
    """
    logger.info("🌉 Supervisor Bridge: Synthesizing final outputs...")
    agent_type = state.get("agent_type", "CHAT")
    agent_response = state.get("agent_response", "")
    target_lang = state.get("target_directive", "English text output format")
    
    final_output = agent_response

    if agent_type == "EMAIL" or agent_type == "CHAT":
        # Email is already formatted natively and chat is precise.
        final_output = agent_response

    elif agent_type == "RAG":
        system_prompt = (
            "You are an elite corporate assistant. Answer the user based on the document context provided.\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. DO NOT include any internal thoughts, reasoning, meta-talk, or introductory phrases. Provide ONLY the direct answer.\n"
            "2. For simple factual questions, provide a very concise, direct answer (1-2 sentences). Only elaborate if the request is complex.\n"
            f"3. Output your final answer entirely in this language/format: {target_lang}. Do NOT discuss this instruction.\n"
            "4. Do not include any URLs or hyperlinks."
        )
        messages_payload = [{"role": "system", "content": system_prompt}]
        for turn in state.get("history", []):
            messages_payload.append({"role": "user", "content": turn.get("user", "")})
            messages_payload.append({"role": "assistant", "content": turn.get("bot", "")})
        messages_payload.append({"role": "user", "content": f"DOCUMENT DATA CONTEXT:\n{agent_response}\n\nUSER PROMPT:\n{state['query']}"})

        try:
            api_res = sarvam_client.chat_complete(messages=messages_payload, model="sarvam-30b", temperature=0.2)
            final_output = api_res["choices"][0].get("message", {}).get("content", "") if "choices" in api_res else ""
        except Exception as e:
            logger.error(f"Upstream Sarvam API gateway error handled: {e}")
            final_output = "System updates are currently processing. Please retry."

    elif agent_type == "WEB":
        # Split links away from main body text
        main_text_context = agent_response
        sources_section = ""
        source_pattern = r"(###\s*Sources)"
        split_match = re.split(source_pattern, main_text_context, flags=re.IGNORECASE)

        if len(split_match) > 1:
            main_text_context = split_match[0]
            sources_section = "\n\n### Sources\n" + split_match[-1].strip()

        premium_lines = []
        for line in main_text_context.split("\n"):
            line_strip = line.strip()
            if not line_strip or len(line_strip) < 20: continue
            if any(p in line_strip.lower() for p in ["image ", "flag ", "ov,", "scorecard", "vssunrisers", "ov ov", "summary answer:"]): continue
            premium_lines.append(line_strip)

        if not premium_lines:
            premium_lines = ["Live operational network streams are refreshing data updates online currently."]

        india_context = "\n".join([l for l in premium_lines if any(w in l.lower() for w in ["india", "delhi", "mumbai", "bengaluru", "modi", "rupee", "rbi", "isro"])][:6])
        world_context = "\n".join([l for l in premium_lines if any(w in l.lower() for w in ["ukraine", "trump", "world", "us ", "biden", "president", "russia", "global", "un "])][:6])

        if not india_context: india_context = "\n".join(premium_lines[:5])
        if not world_context: world_context = "\n".join(premium_lines[5:10]) if len(premium_lines) > 5 else india_context

        is_news_query = any(w in state['query'].lower() for w in ["news", "headline", "update", "current affair"])

        if is_news_query:
            summary_prompt = (
                f"You are a strict news formatting engine. Summarize the user request: '{state['query']}'.\n\n"
                f"DOMESTIC NEWS BLOCKS:\n{india_context}\n\n"
                f"GLOBAL NEWS BLOCKS:\n{world_context}\n\n"
                f"INSTRUCTIONS:\n"
                f"Extract the headlines from the NEWS BLOCKS and translate them to: {target_lang}.\n"
                f"Output exactly 4 to 5 numbered items for 'INDIA NEWS:' and 4 to 5 for 'Global NEWS:'.\n"
                f"Use this exact format for each item: 1. Translated Headline Text\n\n"
                f"CRITICAL RULES:\n"
                f"1. DO NOT include any URLs or markdown links in the headlines.\n"
                f"2. DO NOT include any internal thoughts, reasoning, or intro text.\n"
                f"3. You MUST wrap your ENTIRE output inside <final_answer> and </final_answer> tags.\n"
                f"4. Keep the exact headers 'INDIA NEWS:' and 'Global NEWS:'."
            )
            try:
                api_res = sarvam_client.chat_complete(messages=[{"role": "user", "content": summary_prompt}], model="sarvam-30b", temperature=0.1)
                clean_summary = api_res["choices"][0].get("message", {}).get("content", "") if "choices" in api_res else ""
                
                # Extract only the content inside the final_answer tags
                match = re.search(r"<final_answer>(.*?)</final_answer>", clean_summary, re.DOTALL)
                if match:
                    clean_summary = match.group(1).strip()
                elif "INDIA NEWS:" in clean_summary:
                    # Fallback to the LAST occurrence if tags are missing
                    clean_summary = clean_summary[clean_summary.rfind("INDIA NEWS:"):]
            except Exception:
                clean_summary = ""

            if not clean_summary.strip() or "INDIA NEWS:" not in clean_summary:
                clean_summary = f"INDIA NEWS:\n1. {premium_lines[0]}\n2. {premium_lines[1] if len(premium_lines)>1 else premium_lines[0]}\n\nGlobal NEWS:\n1. {premium_lines[-1]}\n2. {premium_lines[-2] if len(premium_lines)>1 else premium_lines[-1]}"
        else:
            summary_prompt = (
                f"You are an intelligent corporate web research assistant. Answer the user's request: '{state['query']}'.\n\n"
                f"RAW WEB CONTEXT:\n{main_text_context}\n\n"
                f"CRITICAL INSTRUCTIONS:\n"
                f"1. DO NOT include internal thoughts, reasoning, meta-talk, or phrases like 'I need to summarize' or 'Let me translate'.\n"
                f"2. For simple factual queries, give a short, direct answer. Only elaborate if the query asks for a detailed explanation.\n"
                f"3. Provide ONLY the final answer clearly in markdown.\n"
                f"4. Output your final answer entirely in this language/format: {target_lang}. Do NOT discuss this instruction."
            )
            try:
                api_res = sarvam_client.chat_complete(messages=[{"role": "user", "content": summary_prompt}], model="sarvam-30b", temperature=0.1)
                clean_summary = api_res["choices"][0].get("message", {}).get("content", "") if "choices" in api_res else ""
            except Exception:
                clean_summary = main_text_context

        final_output = f"{clean_summary.strip()}\n{sources_section}"

    return {"final_output": final_output.strip(), "next_step": "commit_to_memory"}


def commit_cache_persistence_node(state: AgentState) -> Dict[str, Any]:
    """Persistence Layer Node: Saves state configurations downstream onto flat disk profiles."""
    logger.info("💾 Saving active conversational parameters to persistence storage structures...")
    cache_db = load_json_db(CACHE_FILE)
    history_db = load_json_db(HISTORY_FILE)
    
    cache_db[state["cache_key"]] = state["final_output"]
    history_db.setdefault(state["session_id"], []).append({"user": state["query"], "bot": state["final_output"]})
    
    save_json_db(CACHE_FILE, cache_db)
    save_json_db(HISTORY_FILE, history_db)
    return {"next_step": "end"}

# ─── 3. STATE GRAPH WORKFLOW ORCHESTRATION ───
workflow = StateGraph(AgentState)

# Node Mapping Registers
workflow.add_node("memory_agent", memory_agent_node)
workflow.add_node("supervisor_agent", supervisor_agent_node)
workflow.add_node("general_chat_agent", general_chat_agent_node)
workflow.add_node("rag_modulator", rag_modulator_node)
workflow.add_node("web_scraper", web_scraper_node)
workflow.add_node("email_agent", email_agent_node)
workflow.add_node("supervisor_synthesizer", supervisor_synthesizer_node)
workflow.add_node("commit_to_memory", commit_cache_persistence_node)

workflow.set_entry_point("memory_agent")
workflow.add_edge("memory_agent", "supervisor_agent")

def router_edge(state: AgentState) -> str:
    return state["next_step"]

# Core Supervisor LLM conditional edge mappings
workflow.add_conditional_edges(
    "supervisor_agent",
    router_edge,
    {
        "general_chat_agent": "general_chat_agent",
        "rag_modulator": "rag_modulator",
        "web_scraper": "web_scraper",
        "email_agent": "email_agent"
    }
)

# All worker agents flow perfectly back to the Supervisor Bridge
workflow.add_edge("general_chat_agent", "supervisor_synthesizer")
workflow.add_edge("rag_modulator", "supervisor_synthesizer")
workflow.add_edge("web_scraper", "supervisor_synthesizer")
workflow.add_edge("email_agent", "supervisor_synthesizer")

# Final persistence and end
workflow.add_edge("supervisor_synthesizer", "commit_to_memory")
workflow.add_edge("commit_to_memory", END)

corporate_agent_graph = workflow.compile()