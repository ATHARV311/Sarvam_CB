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
    use_rag: bool
    fallback_message: str

# Local DB persistence tracks
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
import tempfile
DB_DIR = os.path.join(tempfile.gettempdir(), "sarvam_chat_db")
os.makedirs(DB_DIR, exist_ok=True)
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

def extract_token_usage(api_res: dict) -> str:
    usage = api_res.get("usage", {}) if isinstance(api_res, dict) else {}
    if usage:
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", prompt + completion)
        if prompt > 0 or completion > 0:
            return f"\n\n[TOKEN_USAGE: {prompt} incoming | {completion} responding]"
    return ""

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
    
    # ─── STATEFUL "MORE INFO" CHECK ───
    query_lower = query.lower()
    history = state.get("history", [])
    more_info_markers = [
        "yes/no", "yes or no", "हाँ/नहीं", "हो/नाही", "ஆம்/இல்லை", 
        "అవును/కాదు", "હા/ના", "হ্যাঁ/না", "ਹਾਂ/ਨਹੀਂ",
        "ಹೌದು/ಇಲ್ಲ", "അതെ/ഇല്ല"
    ]
    
    if history:
        last_exchange = history[-1]
        last_bot_msg = last_exchange.get("bot", "").lower()
        if any(marker in last_bot_msg for marker in more_info_markers):
            affirmative_words = [
                "yes", "y", "yeah", "yep", "haan", "ha", "yes please", 
                "more info", "more information", "yes more info", "want more info", "get more info",
                "हाँ", "हो", "ஆம்", "అవును", "હા", "হ্যাঁ", "ਹਾਂ", "ಹೌದು", "അതെ"
            ]
            clean_query = re.sub(r'[^\w\s]', '', query_lower).strip()
            if any(clean_query == w or clean_query.startswith(w + " ") for w in affirmative_words):
                previous_query = last_exchange.get("user", "")
                logger.info(f"User accepted more info. Routing to WEB scraper with previous query: {previous_query}")
                return {"query": previous_query, "next_step": "web_scraper"}
    # ─────────────────────────────────────
    
    prompt = f"""Classify this query into one of these exact categories: CHAT, RAG, WEB, EMAIL, OFF_TOPIC.
- OFF_TOPIC: user asks for coding scripts (python, html, etc.), programming help, recipes, entertainment, or anything completely unrelated to corporate operations, company products, or professional assistance.
- EMAIL: user wants to draft, write, or send an email.
- WEB: user asks for latest news, live scores, current affairs, or anything requiring live internet/external data.
- RAG: user asks about uploaded documents, company policy, HR rules, internal pdfs, OR user enters a specific text snippet, quote, or phrase from a document they want to find/explain.
- CHAT: user specifically says hello, greetings, or asks for date/time.

Query: '{query}'
Reply ONLY with the category name (CHAT, RAG, WEB, EMAIL, or OFF_TOPIC) and nothing else."""

    try:
        res = sarvam_client.chat_complete(messages=[{"role": "user", "content": prompt}], model="sarvam-30b", temperature=0.1)
        intent = res["choices"][0].get("message", {}).get("content", "").strip().upper()
    except Exception as e:
        logger.error(f"Supervisor LLM classification failed: {e}")
        intent = "RAG" if state.get("use_rag", True) else "CHAT"
        
    logger.info(f"🎯 Supervisor Intent Evaluated: {intent}")

    if "OFF_TOPIC" in intent:
        return {"next_step": "guardrail_agent"}
    elif "EMAIL" in intent:
        return {"next_step": "email_agent"}
    elif "CHAT" in intent:
        return {"next_step": "general_chat_agent"}
    else:
        # For both RAG and WEB intents, prioritize RAG if it's turned ON.
        # If RAG finds nothing, it will automatically fallback to the web scraper.
        if state.get("use_rag", True):
            return {"next_step": "rag_modulator"}
        else:
            logger.info("RAG is OFF. Routing to Web Scraper.")
            return {"next_step": "web_scraper"}


def guardrail_agent_node(state: AgentState) -> Dict[str, Any]:
    """Agent: Firewall for off-topic queries."""
    logger.info("🛡️ Agent (Guardrail): Blocking off-topic query...")
    return {"agent_response": "I'm Prixgen-AI which is built for enterprise management and help and I'm not authorized to provide things beyond our products.", "agent_type": "GUARDRAIL", "next_step": "supervisor_synthesizer"}

def general_chat_agent_node(state: AgentState) -> Dict[str, Any]:
    """Agent: Handles generic chatting and dynamic date/time injection."""
    logger.info("💬 Running General Chat Agent...")
    query_lower = state.get("query", "").lower()
    
    if "date" in query_lower or "time" in query_lower or "day" in query_lower or "today" in query_lower:
        now = datetime.now().strftime("%B %d, %Y, %I:%M %p")
        response = f"Today's date and time is: {now}."
    else:
        history = state.get("history", [])
        target_lang = state.get("target_directive", "English")
        
        messages = [
            {"role": "system", "content": f"You are a friendly, intelligent corporate assistant. Have a natural, concise conversation with the user. Output your response entirely in: {target_lang}."}
        ]
        
        for turn in history:
            bot_msg = turn.get("bot", "")
            bot_msg = bot_msg.replace("⚠️ *Not present in knowledge base. Going for web search...*\n\n", "")
            bot_msg = bot_msg.replace("⚠️ *RAG error occurred. Falling back to web search...*\n\n", "")
            # Prevent token hallucination by stripping old tokens
            bot_msg = re.sub(r"\[TOKEN_USAGE:.*?\]", "", bot_msg)
            bot_msg = re.sub(r"<div class='text-xs.*?</div>", "", bot_msg)
            
            messages.append({"role": "user", "content": turn.get("user", "")})
            messages.append({"role": "assistant", "content": bot_msg})
            
        messages.append({"role": "user", "content": state.get("query", "")})
        
        try:
            res = sarvam_client.chat_complete(messages=messages, model="sarvam-30b", temperature=0.7)
            if res.get("error"):
                response = f"⚠️ **API Error:** {res.get('message', 'API failed.')}"
            else:
                response = res["choices"][0]["message"]["content"]
                response += extract_token_usage(res)
        except Exception as e:
            logger.error(f"Chat LLM failed: {e}")
            response = "Hello! How can I assist your corporate workflow today?"
        
    return {"agent_response": response, "agent_type": "CHAT", "next_step": "supervisor_synthesizer"}


def rag_modulator_node(state: AgentState) -> Dict[str, Any]:
    """Agent 1 (RAG Modulator): Scans document embeddings."""
    logger.info("📁 Agent 1 (RAG Modulator): Extracting local document vector data segments...")
    errors = list(state.get("errors", []))
    try:
        context = rag_engine.retrieve_context(state["query"], top_k=2) if hasattr(rag_engine, 'retrieve_context') else ""
        if not context or "0 chunks" in context:
            logger.info("No relevant context found in RAG. Redirecting to Web Scraper.")
            return {"agent_response": "", "agent_type": "WEB", "next_step": "web_scraper", "fallback_message": "⚠️ *Not present in knowledge base. Going for web search...*\n\n"}
        return {"agent_response": context, "agent_type": "RAG", "next_step": "supervisor_synthesizer"}
    except Exception as e:
        logger.error(f"RAG Modulator Pipeline Interrupted: {e}")
        errors.append(f"rag_failed: {str(e)}")
        return {"agent_response": "", "agent_type": "WEB", "errors": errors, "next_step": "web_scraper", "fallback_message": "⚠️ *RAG error occurred. Falling back to web search...*\n\n"}


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
    history_text = "\n".join([f"User: {t.get('user', '')}\nBot: {t.get('bot', '')}" for t in state.get("history", [])])
    if not history_text.strip():
        history_text = "(No prior chat history available)"
        
    email_prompt = (
        f"You are a strict email drafting agent. Your ONLY job is to draft a business email based on the user's request.\n"
        f"Use the chat history as context if the user asks to summarize the conversation.\n\n"
        f"--- CHAT HISTORY ---\n{history_text}\n--------------------\n\n"
        f"USER REQUEST: '{state['query']}'\n\n"
        f"CRITICAL INSTRUCTION: You must write the email completely in this language: {target_lang}.\n"
        f"CRITICAL INSTRUCTION: You may reason about your response, but you MUST place all reasoning inside <think>...</think> tags.\n"
        f"After you finish thinking, you MUST output the final email wrapped in a ```json markdown block.\n\n"
        f"FORMAT YOU MUST FOLLOW:\n"
        f"<think>\n"
        f"Planning the email structure here...\n"
        f"</think>\n"
        f"```json\n"
        f"{{\n"
        f'  "recipient": "manager@example.com",\n'
        f'  "subject": "Relevant Subject Line",\n'
        f'  "body": "The email text body goes here."\n'
        f"}}\n"
        f"```\n\n"
        f"START OUTPUT NOW:"
    )
    try:
        messages = [
            {"role": "system", "content": "You are an email drafting agent. Think before generating, and always output the final email in a ```json block."},
            {"role": "user", "content": email_prompt}
        ]
        api_res = sarvam_client.chat_complete(messages=messages, model="sarvam-30b", temperature=0.2)
        ai_draft = api_res["choices"][0].get("message", {}).get("content", "") if "choices" in api_res else ""
        token_str = extract_token_usage(api_res)
    except Exception:
        ai_draft = ""
        token_str = ""

    # Extract JSON safely
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", ai_draft, re.DOTALL | re.IGNORECASE)
    if json_match:
        clean_json_str = json_match.group(1).strip()
    else:
        # Try to find anything that looks like a JSON dictionary
        fallback_match = re.search(r"(\{.*\})", ai_draft, re.DOTALL)
        clean_json_str = fallback_match.group(1).strip() if fallback_match else "{}"

    recipient = "manager@example.com"
    subject = "Draft Email"
    body_text = "Failed to generate email content. Please try again."

    try:
        parsed = json.loads(clean_json_str)
        recipient = parsed.get("recipient", recipient)
        subject = parsed.get("subject", subject)
        body_text = parsed.get("body", body_text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON email from AI: {clean_json_str}")
        # Never leak raw AI thought process to the body
        pass

    # Truncate for URL safety (Gmail and Mailto have limits ~2000 chars)
    url_body = body_text if len(body_text) < 1500 else body_text[:1500] + "\n\n[...Truncated due to length limit...]"

    safe_rec = urllib.parse.quote(recipient)
    safe_sub = urllib.parse.quote(subject)
    safe_body = urllib.parse.quote(url_body)

    mailto_link = f"mailto:{safe_rec}?subject={safe_sub}&body={safe_body}"
    gmail_link = f"https://mail.google.com/mail/u/0/?view=cm&fs=1&to={safe_rec}&su={safe_sub}&body={safe_body}"
    
    final_output = f"""[EMAIL_CARD]
RECIPIENT:{recipient}
SUBJECT:{subject}
BODY:{body_text}
MAILTO:{mailto_link}
GMAIL:{gmail_link}
[/EMAIL_CARD]{token_str}"""
    
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

    if agent_type == "EMAIL" or agent_type == "CHAT" or agent_type == "GUARDRAIL":
        # Handled natively, pass through.
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
            bot_msg = turn.get("bot", "")
            bot_msg = bot_msg.replace("⚠️ *Not present in knowledge base. Going for web search...*\n\n", "")
            bot_msg = bot_msg.replace("⚠️ *RAG error occurred. Falling back to web search...*\n\n", "")
            messages_payload.append({"role": "user", "content": turn.get("user", "")})
            messages_payload.append({"role": "assistant", "content": bot_msg})
        messages_payload.append({"role": "user", "content": f"DOCUMENT DATA CONTEXT:\n{agent_response}\n\nUSER PROMPT:\n{state['query']}"})

        try:
            api_res = sarvam_client.chat_complete(messages=messages_payload, model="sarvam-30b", temperature=0.6)
            if api_res.get("error"):
                final_output = f"⚠️ **Sarvam API Error:** {api_res.get('message', 'Credits exhausted or API failed.')}"
                token_str = ""
            else:
                final_output = api_res["choices"][0].get("message", {}).get("content", "") if "choices" in api_res else ""
                token_str = extract_token_usage(api_res)
        except Exception as e:
            logger.error(f"Upstream Sarvam API gateway error handled: {e}")
            final_output = "System updates are currently processing. Please retry."
            token_str = ""
            
        extracted_lang = state.get("extracted_lang", "English")
        prompt_translations = {
            "English": "Do you want more information? (Yes/No)",
            "Hindi": "क्या आप अधिक जानकारी चाहते हैं? (हाँ/नहीं)",
            "Marathi": "तुम्हाला अधिक माहिती हवी आहे का? (हो/नाही)",
            "Tamil": "மேலும் தகவல் வேண்டுமா? (ஆம்/இல்லை)",
            "Telugu": "మీకు మరింత సమాచారం కావాలా? (అవును/కాదు)",
            "Gujarati": "શું તમને વધુ માહિતી જોઈએ છે? (હા/ના)",
            "Bengali": "আপনি কি আরও তথ্য চান? (হ্যাঁ/না)",
            "Punjabi": "ਕੀ ਤੁਸੀਂ ਹੋਰ ਜਾਣਕਾਰੀ ਚਾਹੁੰਦੇ ਹੋ? (ਹਾਂ/ਨਹੀਂ)",
            "Kannada": "ನಿಮಗೆ ಹೆಚ್ಚಿನ ಮಾಹಿತಿ ಬೇಕೇ? (ಹೌದು/ಇಲ್ಲ)",
            "Malayalam": "നിങ്ങൾക്ക് കൂടുതൽ വിവരങ്ങൾ വേണോ? (അതെ/ഇല്ല)"
        }
        more_info_prompt = prompt_translations.get(extracted_lang, prompt_translations["English"])
        
        if final_output:
            final_output += f"\n\n**{more_info_prompt}**"
            final_output += token_str

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
                if api_res.get("error"):
                    clean_summary = f"⚠️ **Sarvam API Error:** {api_res.get('message', 'Credits exhausted or API failed.')}"
                    token_str = ""
                else:
                    clean_summary = api_res["choices"][0].get("message", {}).get("content", "") if "choices" in api_res else ""
                    token_str = extract_token_usage(api_res)
                
                # Extract only the content inside the final_answer tags
                match = re.search(r"<final_answer>(.*?)</final_answer>", clean_summary, re.DOTALL)
                if match:
                    clean_summary = match.group(1).strip()
                elif "INDIA NEWS:" in clean_summary:
                    # Fallback to the LAST occurrence if tags are missing
                    clean_summary = clean_summary[clean_summary.rfind("INDIA NEWS:"):]
            except Exception:
                clean_summary = ""
                token_str = ""

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
                if api_res.get("error"):
                    clean_summary = f"⚠️ **Sarvam API Error:** {api_res.get('message', 'Credits exhausted or API failed.')}"
                    token_str = ""
                else:
                    clean_summary = api_res["choices"][0].get("message", {}).get("content", "") if "choices" in api_res else ""
                    token_str = extract_token_usage(api_res)
            except Exception:
                clean_summary = main_text_context
                token_str = ""

        final_output = f"{clean_summary.strip()}\n{sources_section}\n{token_str}"

    fallback_msg = state.get("fallback_message", "")
    if fallback_msg:
        final_output = fallback_msg + final_output

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
workflow.add_node("guardrail_agent", guardrail_agent_node)
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
        "email_agent": "email_agent",
        "guardrail_agent": "guardrail_agent"
    }
)

# All worker agents flow perfectly back to the Supervisor Bridge
workflow.add_edge("general_chat_agent", "supervisor_synthesizer")
workflow.add_conditional_edges(
    "rag_modulator",
    router_edge,
    {
        "supervisor_synthesizer": "supervisor_synthesizer",
        "web_scraper": "web_scraper"
    }
)
workflow.add_edge("web_scraper", "supervisor_synthesizer")
workflow.add_edge("email_agent", "supervisor_synthesizer")
workflow.add_edge("guardrail_agent", "supervisor_synthesizer")

# Final persistence and end
workflow.add_edge("supervisor_synthesizer", "commit_to_memory")
workflow.add_edge("commit_to_memory", END)

corporate_agent_graph = workflow.compile()