// ==========================================================================
// APPLICATION GLOBAL STATE & CONSTANTS
// ==========================================================================
const BASE_URL = "http://127.0.0.1:8000";

let state = {
    messages: [],
    sessions: [],
    currentSessionId: null,
    useRAG: true,
    isRecording: false,
    mediaRecorder: null,
    audioChunks: [],
    currentAudio: null,
    systemMode: "DEMO",
    indexedFiles: []
};

// ==========================================================================
// DOM SELECTORS
// ==========================================================================
const elements = {
    sidebarToggle: document.getElementById("sidebar-toggle"),
    systemMode: document.getElementById("system-mode"),
    apiStatus: document.getElementById("api-status"),
    indexedChunks: document.getElementById("indexed-chunks"),
    languageSelect: document.getElementById("language-select"),
    speakerSelect: document.getElementById("speaker-select"),
    voicePace: document.getElementById("voice-pace"),
    paceVal: document.getElementById("pace-val"),
    voiceOutputToggle: document.getElementById("voice-output-toggle"),
    dropzone: document.getElementById("dropzone"),
    fileInput: document.getElementById("file-input"),
    uploadProgressContainer: document.getElementById("upload-progress-container"),
    uploadProgressFill: document.getElementById("upload-progress-fill"),
    uploadProgressText: document.getElementById("upload-progress-text"),
    sourcesList: document.getElementById("sources-list"),
    clearDocsBtn: document.getElementById("clear-docs-btn"),
    darkThemeBtn: document.getElementById("dark-theme-btn"),
    lightThemeBtn: document.getElementById("light-theme-btn"),
    useRagToggle: document.getElementById("use-rag-toggle"),
    ragStatusText: document.getElementById("rag-status-text"),
    chatMessages: document.getElementById("chat-messages"),
    chatInputTextarea: document.getElementById("chat-input-textarea"),
    sendBtn: document.getElementById("send-btn"),
    micBtn: document.getElementById("mic-btn"),
    micRecordingUI: document.getElementById("mic-recording-ui"),
    recLangLabel: document.getElementById("rec-lang-label"),
    stopMicBtn: document.getElementById("stop-mic-btn"),
    cancelMicBtn: document.getElementById("cancel-mic-btn"),
    voicePlayerContainer: document.getElementById("voice-player-container"),
    voicePlayingLang: document.getElementById("voice-playing-lang"),
    audioPlayPauseBtn: document.getElementById("audio-play-pause-btn"),
    audioStopBtn: document.getElementById("audio-stop-btn"),
    globalAudioPlayer: document.getElementById("global-audio-player"),
    ocrBtn: document.getElementById("ocr-btn"),
    ocrFileInput: document.getElementById("ocr-file-input"),
    newChatBtn: document.getElementById("new-chat-btn"),
    sessionsList: document.getElementById("sessions-list")
};

// ==========================================================================
// AUTHENTICATION CHECK & GLOBAL FETCH OVERRIDE
// ==========================================================================
const token = localStorage.getItem('sarvam_jwt');
if (!token) {
    window.location.href = 'login.html';
}

const originalFetch = window.fetch;
window.fetch = async function() {
    let [resource, config] = arguments;
    if (typeof resource === 'string' && resource.startsWith(BASE_URL)) {
        config = config || {};
        // If config.body is FormData, don't set Content-Type header manually
        const isFormData = config.body instanceof FormData;
        
        if (!config.headers) {
            config.headers = {};
        }
        
        // Convert headers object to handle different ways it might have been passed
        const headersObj = new Headers(config.headers);
        const jwt = localStorage.getItem('sarvam_jwt');
        if (jwt) {
            headersObj.set('Authorization', `Bearer ${jwt}`);
        }
        
        config.headers = headersObj;
    }
    
    const response = await originalFetch(resource, config);
    if (response.status === 401) {
        localStorage.removeItem('sarvam_jwt');
        window.location.href = 'login.html';
    }
    return response;
};

// ==========================================================================
// APP INITIALIZATION
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
    // 1. Initial server scanning
    scanServerStatus();
    
    // Set Profile Info
    const displayUsername = document.getElementById('display-username');
    const displayRole = document.getElementById('display-role');
    if(displayUsername) displayUsername.innerText = localStorage.getItem('sarvam_username') || 'User';
    if(displayRole) displayRole.innerText = localStorage.getItem('sarvam_role') || 'Customer'; // we need to save role in auth.js!
    
    const logoutBtn = document.getElementById('logout-btn');
    if(logoutBtn) {
        logoutBtn.onclick = () => {
            localStorage.removeItem('sarvam_jwt');
            localStorage.removeItem('sarvam_username');
            localStorage.removeItem('sarvam_role');
            window.location.href = 'login.html';
        };
    }
    
    // 2. Setup Action Listeners
    setupThemeHandlers();
    setupChatInputHandlers();
    setupRAGHandlers();
    setupPreferencesHandlers();
    setupSTTHandlers();
    setupOCRHandlers();
    setupSuggestedChips();
    
    // 3. Initialize dynamic dashboard data
    initializeSessions();
    setupSessionHandlers();
    loadDocuments();
});

async function loadDocuments() {
    try {
        const res = await fetch(`${BASE_URL}/api/documents`);
        if (res.ok) {
            const data = await res.json();
            const list = document.getElementById('user-documents-list');
            if (!list) return;
            list.innerHTML = '';
            if (data.documents.length === 0) {
                list.innerHTML = '<li class="empty-sources">No documents uploaded yet.</li>';
                return;
            }
            data.documents.forEach(doc => {
                const li = document.createElement('li');
                li.innerHTML = `
                    <div class="file-info">
                        <i class="fa-solid fa-file-pdf"></i>
                        <span title="${doc.filename}">${doc.filename}</span>
                    </div>
                `;
                list.appendChild(li);
            });
        }
    } catch(e) { console.error("Failed to load documents"); }
}

// ==========================================================================
// PREFERENCES & UTILITIES HANDLERS
// ==========================================================================
function setupPreferencesHandlers() {
    if (elements.voicePace) {
        elements.voicePace.addEventListener("input", (e) => {
            elements.paceVal.innerText = `${e.target.value}x`;
        });
    }

    if (elements.languageSelect) {
        elements.languageSelect.addEventListener("change", () => {
            const activeLangName = elements.languageSelect.options[elements.languageSelect.selectedIndex].text.split(" (")[0];
            showToast(`Language set to ${activeLangName}`);
        });
    }
}

// ==========================================================================
// TOAST NOTIFICATIONS
// ==========================================================================
function showToast(message) {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    const toast = document.createElement('div');
    toast.className = 'toast-notification';
    toast.innerHTML = `<i class="fa-solid fa-globe"></i> <span>${message}</span>`;
    
    container.appendChild(toast);
    
    // Trigger animation
    setTimeout(() => toast.classList.add('show'), 10);
    
    // Remove after 3 seconds
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ==========================================================================
// THEME & CHIP ACTIONS
// ==========================================================================
function setupThemeHandlers() {
    if (elements.darkThemeBtn && elements.lightThemeBtn) {
        elements.darkThemeBtn.addEventListener("click", () => {
            document.body.classList.add("dark-theme");
            document.body.classList.remove("light-theme");
            elements.darkThemeBtn.classList.add("active");
            elements.lightThemeBtn.classList.remove("active");
        });

        elements.lightThemeBtn.addEventListener("click", () => {
            document.body.classList.add("light-theme");
            document.body.classList.remove("dark-theme");
            elements.lightThemeBtn.classList.add("active");
            elements.darkThemeBtn.classList.remove("active");
        });
    }

    if (elements.sidebarToggle) {
        elements.sidebarToggle.addEventListener("click", () => {
            const sidebar = document.querySelector(".sidebar");
            sidebar.classList.toggle("collapsed");
        });
    }
}

function setupSuggestedChips() {
    document.querySelectorAll(".chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const query = chip.getAttribute("data-query");
            elements.chatInputTextarea.value = query;
            elements.chatInputTextarea.dispatchEvent(new Event("input"));
            submitUserMessage();
        });
    });
}

// ==========================================================================
// SERVER COMMUNICATOR & REFRESH STATS
// ==========================================================================
async function scanServerStatus() {
    try {
        const res = await fetch(`${BASE_URL}/api/status`);
        if (res.ok) {
            const data = await res.json();
            state.systemMode = data.mode;
            
            if (elements.systemMode) {
                elements.systemMode.innerText = data.mode === "PROD" ? "Production" : "Demo Mode";
                elements.systemMode.className = `badge status-badge ${data.mode === "PROD" ? "prod-badge" : "demo-badge"}`;
            }
            
            if (elements.apiStatus) {
                elements.apiStatus.innerHTML = `<span style="color: #10b981"><i class="fa-solid fa-circle-check"></i> Connected</span>`;
            }
            
            if (elements.indexedChunks) {
                const chunkCount = data.rag_stats.total_chunks || 0;
                elements.indexedChunks.innerText = `${chunkCount} chunk${chunkCount === 1 ? "" : "s"}`;
            }
            
            renderSourceFiles(data.rag_stats.files || []);
        } else {
            setOfflineStatus();
        }
    } catch (e) {
        console.error("Connection failed with server:", e);
        setOfflineStatus();
    }
}

function setOfflineStatus() {
    if (elements.apiStatus) elements.apiStatus.innerHTML = `<span style="color: #ef4444"><i class="fa-solid fa-triangle-exclamation"></i> Offline</span>`;
    if (elements.systemMode) {
        elements.systemMode.innerText = "Offline";
        elements.systemMode.className = "badge status-badge demo-badge";
    }
    if (elements.indexedChunks) elements.indexedChunks.innerText = "N/A";
}


function renderSourceFiles(files) {
    state.indexedFiles = files;
    if (!elements.sourcesList) return;
    elements.sourcesList.innerHTML = "";
    
    if (files.length === 0) {
        elements.sourcesList.innerHTML = `<li class="empty-sources">No documents uploaded yet.</li>`;
        return;
    }
    
    files.forEach(filename => {
        const li = document.createElement("li");
        li.innerHTML = `
            <div class="file-info">
                <i class="fa-solid fa-file-invoice"></i>
                <span title="${filename}">${filename}</span>
            </div>
        `;
        elements.sourcesList.appendChild(li);
    });
}

// ==========================================================================
// CHAT LAYOUT & CONVERSATION LOOP
// ==========================================================================
function setupChatInputHandlers() {
    if (!elements.chatInputTextarea) return;

    elements.chatInputTextarea.addEventListener("input", (e) => {
        e.target.style.height = "auto";
        e.target.style.height = `${e.target.scrollHeight - 10}px`;
        if (elements.sendBtn) elements.sendBtn.disabled = !e.target.value.trim();
    });

    elements.chatInputTextarea.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submitUserMessage();
        }
    });

    if (elements.sendBtn) {
        elements.sendBtn.addEventListener("click", () => {
            submitUserMessage();
        });
    }
}

function formatMarkdown(text) {
    if (!text) return "";
    
    let formatted = String(text);
    
    // Remove <thought> or <think> internal reasoning blocks completely
    formatted = formatted.replace(/<(?:thought|think)>[\s\S]*?(?:<\/(?:thought|think)>|$)/g, "");
    
    // Check for Email Card Payload BEFORE escaping HTML
    const emailMatch = formatted.match(/\[EMAIL_CARD\]\nRECIPIENT:(.*?)\nSUBJECT:(.*?)\nBODY:([\s\S]*?)\nMAILTO:(.*?)\nGMAIL:(.*?)\n\[\/EMAIL_CARD\]/);
    let emailHtml = "";
    if (emailMatch) {
        const [fullMatch, rec, sub, body, mailto, gmail] = emailMatch;
        formatted = formatted.replace(fullMatch, "[[EMAIL_CARD_PLACEHOLDER]]");
        
        // Build the sleek UI Card
        emailHtml = `
            <div class="email-draft-card" style="border: 1px solid var(--border-color); border-radius: 12px; padding: 20px; background-color: var(--bg-tertiary); margin-top: 15px; margin-bottom: 15px;">
                <div style="display: flex; align-items: center; margin-bottom: 12px; border-bottom: 1px solid var(--border-color); padding-bottom: 12px;">
                    <i class="fa-solid fa-envelope" style="color: var(--accent-primary); font-size: 1.2rem; margin-right: 12px;"></i>
                    <h3 style="margin: 0; font-size: 1rem; color: var(--text-primary);">Email Draft Ready</h3>
                </div>
                <div style="margin-bottom: 8px; font-size: 0.9rem;">
                    <strong style="color: var(--text-secondary);">To:</strong> <span style="color: var(--text-primary);">${rec.trim()}</span>
                </div>
                <div style="margin-bottom: 15px; font-size: 0.9rem;">
                    <strong style="color: var(--text-secondary);">Subject:</strong> <span style="color: var(--text-primary); font-weight: 500;">${sub.trim()}</span>
                </div>
                <div style="padding: 15px; background-color: var(--bg-primary); border: 1px solid var(--border-color); border-radius: 8px; white-space: pre-wrap; font-family: 'Inter', sans-serif; font-size: 0.9rem; line-height: 1.5; color: var(--text-primary); margin-bottom: 20px;">${body.trim()}</div>
                <div style="display: flex; gap: 12px; flex-wrap: wrap;">
                    <a href="${mailto.trim()}" class="btn-primary" style="text-decoration: none; padding: 8px 16px; border-radius: 6px; display: inline-flex; align-items: center; gap: 8px; font-size: 0.85rem; font-weight: 500; transition: all 0.2s;">
                        <i class="fa-regular fa-paper-plane"></i> Send via Default App
                    </a>
                    <a href="${gmail.trim()}" target="_blank" class="btn-secondary" style="text-decoration: none; padding: 8px 16px; border-radius: 6px; display: inline-flex; align-items: center; gap: 8px; font-size: 0.85rem; font-weight: 500; transition: all 0.2s;">
                        <i class="fa-brands fa-google"></i> Send via Gmail
                    </a>
                </div>
            </div>
        `;
    }

    formatted = formatted
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
        
    if (emailHtml) {
        formatted = formatted.replace("[[EMAIL_CARD_PLACEHOLDER]]", emailHtml);
    }
    
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    formatted = formatted.replace(/\*(.*?)\*/g, "<em>$1</em>");
    formatted = formatted.replace(/`(.*?)`/g, "<code>$1</code>");
    formatted = formatted.replace(/!\[(.*?)\]\((.*?)\)/g, '<img src="$2" alt="$1" style="max-height: 180px; border-radius: 8px; margin-top: 10px;">');
    formatted = formatted.replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank" class="chat-link"><i class="fa-solid fa-arrow-up-right-from-square"></i> $1</a>');
    
    // Safely parse the Token Usage placeholder into HTML
    formatted = formatted.replace(/\[TOKEN_USAGE: (.*?)\]/g, "<div class='text-xs text-gray-500 mt-2 text-right' style='opacity: 0.6;'>🪙 Tokens: $1</div>");
    
    // Recover old tokens from history that got HTML-escaped
    formatted = formatted.replace(/&lt;div class='text-xs text-gray-500 mt-2 text-right' style='opacity: 0\.6;'&gt;🪙 Tokens: (.*?)&lt;\/div&gt;/g, "<div class='text-xs text-gray-500 mt-2 text-right' style='opacity: 0.6;'>🪙 Tokens: $1</div>");

    // Clean up hidden system action payload parameters before generating layouts
    formatted = formatted.replace(/\[EMAIL_START\]/g, "");
    formatted = formatted.replace(/\[SUBJECT:.*?\]/g, "");
    formatted = formatted.replace(/\[BODY:([\s\S]*?)\]/g, "$1");
    formatted = formatted.replace(/\[EMAIL_END\]/g, "");

    // Parse headers
    formatted = formatted.replace(/^### (.*$)/gim, '<h3>$1</h3>');
    formatted = formatted.replace(/^## (.*$)/gim, '<h2>$1</h2>');
    formatted = formatted.replace(/^# (.*$)/gim, '<h1>$1</h1>');

    const blocks = formatted.split(/\n\n+/);
    return blocks.map(block => {
        block = block.trim();
        if (!block) return "";
        
        let lines = block.split(/\n/);
        let inUl = false;
        let inOl = false;
        let html = '';
        
        for (let line of lines) {
            line = line.trim();
            if (!line) continue;
            
            let isUl = line.startsWith('- ') || line.startsWith('* ');
            let isOl = line.match(/^\d+\.\s+/);
            
            if (isUl) {
                if (inOl) { html += '</ol>'; inOl = false; }
                if (!inUl) { html += '<ul>'; inUl = true; }
                html += `<li>${line.substring(2)}</li>`;
            } else if (isOl) {
                if (inUl) { html += '</ul>'; inUl = false; }
                if (!inOl) { html += '<ol>'; inOl = true; }
                html += `<li>${line.replace(/^\d+\.\s+/, '')}</li>`;
            } else {
                if (inUl) { html += '</ul>'; inUl = false; }
                if (inOl) { html += '</ol>'; inOl = false; }
                if (line.startsWith('<h') || line.startsWith('<div')) {
                    html += line;
                } else {
                    html += `<p>${line}</p>`;
                }
            }
        }
        
        if (inUl) html += '</ul>';
        if (inOl) html += '</ol>';
        
        return html;
    }).join("");
}

function appendMessageBubble(role, content, extra = {}) {
    if (!elements.chatMessages) return null;
    
    const isWelcome = elements.chatMessages.querySelector(".system-welcome");
    if (isWelcome) isWelcome.remove();

    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${role === "user" ? "user" : "bot"}`;
    
    const avatarIcon = role === "user" ? '<i class="fa-solid fa-user-astronaut"></i>' : '<i class="fa-solid fa-robot"></i>';
    let bubbleContent = `<div class="message-bubble">`;
    
    if (extra.isTyping) {
        bubbleContent += `
            <div class="typing-indicator" id="active-typing">
                <span></span><span></span><span></span>
            </div>`;
    } else {
        if (extra.reasoning_content && extra.reasoning_content !== content) {
            bubbleContent += `
                <details class="thinking-block">
                    <summary><i class="fa-solid fa-brain"></i> Thinking Process</summary>
                    <div class="thinking-content">${formatMarkdown(extra.reasoning_content)}</div>
                </details>`;
        }
        
        bubbleContent += formatMarkdown(content);
        
        // ==========================================================================
        // SEAMLESS INTEGRATION DISPLAY CARD FOR COPILOT AGENT WORKFLOW
        // ==========================================================================
        if (content && typeof content === "string" && content.includes("[EMAIL_START]")) {
            try {
                const subjectMatch = content.match(/\[SUBJECT:\s*(.*?)\s*\]/);
                const bodyMatch = content.match(/\[BODY:\s*([\s\S]*?)\s*\]/);
                
                if (subjectMatch && bodyMatch) {
                    const subjectText = subjectMatch[1];
                    let bodyText = bodyMatch[1].replace(/\[EMAIL_END\]/g, "").trim();
                    const UIBodyHTML = bodyText.replace(/\n/g, "<br>");
                    
                    bubbleContent += `
                        <div class="email-draft-card" style="margin-top: 16px; border: 1px solid var(--border-color, #e2e8f0); border-radius: 8px; background: rgba(255, 255, 255, 0.03); overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                            <div class="email-card-header" style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: rgba(0, 0, 0, 0.15); border-bottom: 1px solid var(--border-color, #e2e8f0);">
                                <span style="font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted, #94a3b8);">
                                    <i class="fa-solid fa-envelope-open-text" style="margin-right: 6px;"></i> Copilot Execution
                                </span>
                            </div>
                            <div class="email-card-body" style="padding: 16px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; font-size: 0.95rem; line-height: 1.6; color: var(--text-main, #f8fafc);">
                                <div class="email-field-line" style="margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.05);">
                                    <strong style="color: var(--accent-primary, #6366f1);">Subject:</strong> ${subjectText}
                                </div>
                                <div class="email-body-content" style="white-space: pre-line; word-break: break-word;">
                                    ${UIBodyHTML}
                                </div>
                            </div>
                        </div>`;
                }
            } catch (err) {
                console.error("Error creating integration card visual layout:", err);
            }
        }
        
        // ==========================================================================
        // GROUNDED SOURCE SUB-LINKS CLICKABLE BADGES
        // ==========================================================================
        if (extra.rag_applied && extra.rag_sources && extra.rag_sources.length > 0) {
            bubbleContent += `
                <div class="citation-block">
                    <div class="citation-title"><i class="fa-solid fa-book-bookmark"></i> Grounded Sources</div>
                    <div class="citation-chips-container">
                        ${extra.rag_sources.map(src => {
                            const urlMatch = src.match(/\((https?:\/\/[^\)]+)\)/);
                            if (urlMatch) {
                                const url = urlMatch[1];
                                const cleanText = src.replace(/\s*\(https?:\/\/[^\)]+\)/, "");
                                return `<a href="${url}" target="_blank" class="citation-badge clickable-badge" title="Open Source URL"><i class="fa-solid fa-arrow-up-right-from-square" style="font-size: 0.65rem; margin-right: 4px;"></i> ${cleanText}</a>`;
                            }
                            return `<span class="citation-badge">${src}</span>`;
                        }).join("")}
                    </div>
                </div>`;
        }
        
        if (role === "bot" && content) {
            bubbleContent += `
                <button class="tts-trigger-btn" title="Speak Response" onclick="synthesizeText(this, '${content.replace(/'/g, "\\'").replace(/"/g, '&quot;').replace(/\n/g, " ")}')">
                    <i class="fa-solid fa-volume-low"></i>
                </button>`;
        }
    }
    
    bubbleContent += `</div>`;
    msgDiv.innerHTML = `<div class="msg-avatar">${avatarIcon}</div>${bubbleContent}`;
    
    elements.chatMessages.appendChild(msgDiv);
    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
    
    return msgDiv;
}

async function submitUserMessage() {
    const text = elements.chatInputTextarea.value.trim();
    if (!text) return;
    
    elements.chatInputTextarea.value = "";
    elements.chatInputTextarea.dispatchEvent(new Event("input"));
    
    appendMessageBubble("user", text);
    state.messages.push({ role: "user", content: text });
    
    const currentSession = state.sessions.find(s => s.session_id === state.currentSessionId);
    if (currentSession) {
        if (currentSession.messages.length === 1 || currentSession.title === "New Chat") {
            const titleText = text.length > 25 ? text.substring(0, 22) + "..." : text;
            currentSession.title = titleText;
            renderSessionsList();
        }
        currentSession.messages = state.messages;
        localStorage.setItem("sarvam_chat_sessions", JSON.stringify(state.sessions));
    }
    
    const typingBubble = appendMessageBubble("bot", "", { isTyping: true });
    
    try {
        const payload = {
            session_id: state.currentSessionId || "default_session",
            query: text,
            target_language: elements.languageSelect.value,
            use_rag: state.useRAG
        };
        
        const res = await fetch(`${BASE_URL}/api/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (typingBubble) typingBubble.remove();
        
        if (res.ok) {
            const data = await res.json();
            
            // ─── 🛠️ FRONTEND GMAIL AUTO-OPEN INTELLIGENT INTERCEPT ───
            if (data.source === "gmail_copilot" && data.response) {
                // Regex parsing maps out the raw URL wrapped within markdown syntax [Text](URL)
                const urlRegex = /\((https:\/\/mail\.google\.com\/mail\/[^)]+)\)/;
                const linkMatch = data.response.match(urlRegex);
                if (linkMatch && linkMatch[1]) {
                    // Fires open a dedicated native browser window target instantly
                    window.open(linkMatch[1], '_blank');
                }
            }
            // ────────────────────────────────────────────────────────
            
            let botResponse = data.response;
            let reasoning = data.reasoning_content || "";
            let ragApplied = data.source === "rag_engine" || !!data.rag_applied;
            let ragSources = data.rag_sources || [];

            if (!botResponse && data.choices) {
                const choice = data.choices[0];
                botResponse = choice.message.content;
                reasoning = choice.message.reasoning_content || reasoning;
                ragApplied = data.rag_applied;
                ragSources = data.rag_sources || [];
            }
            
            if (!botResponse && reasoning) {
                botResponse = reasoning;
            }
            
            appendMessageBubble("bot", botResponse, {
                rag_applied: ragApplied,
                rag_sources: ragSources,
                reasoning_content: reasoning
            });
            
            state.messages.push({
                role: "assistant",
                content: botResponse || reasoning || "",
                rag_applied: ragApplied,
                rag_sources: ragSources,
                reasoning_content: reasoning
            });
            
            if (currentSession) {
                currentSession.messages = state.messages;
                localStorage.setItem("sarvam_chat_sessions", JSON.stringify(state.sessions));
            }
            
            if (elements.voiceOutputToggle && elements.voiceOutputToggle.checked) {
                playVoiceResponse(botResponse);
            }
        } else {
            const err = await res.text();
            appendMessageBubble("bot", `⚠️ Failed to retrieve AI response. Server error: ${err}`);
        }
    } catch (e) {
        if (typingBubble) typingBubble.remove();
        console.error("Communication error:", e);
        appendMessageBubble("bot", `⚠️ Error communicating with server. Make sure the FastAPI backend is running on port 8000.`);
    }
}

// ==========================================================================
// TEXT-TO-SPEECH (TTS) AUDIO COMPONENT
// ==========================================================================
async function playVoiceResponse(text) {
    if (state.systemMode === "DEMO") return;
    const speechText = text.replace(/\[.*?\]\(.*?\)/g, "").replace(/[#*`]/g, "").substring(0, 1500);
    await requestSpeechSynthesis(speechText);
}

window.synthesizeText = async function(btn, text) {
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    await requestSpeechSynthesis(text);
    btn.innerHTML = '<i class="fa-solid fa-volume-low"></i>';
};

async function requestSpeechSynthesis(text) {
    try {
        const payload = {
            text: text,
            language_code: elements.languageSelect.value,
            speaker: elements.speakerSelect.value,
            pace: parseFloat(elements.voicePace.value)
        };
        
        const res = await fetch(`${BASE_URL}/api/tts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        if (res.ok) {
            const data = await res.json();
            if (data.is_demo) {
                appendMessageBubble("bot", "🎙️ Text-to-Speech voice synthesis requires a valid SARVAM_API_KEY.");
                return;
            }
            const base64Audio = data.audios ? data.audios[0] : (data.audio || null);
            if (base64Audio) playBase64Audio(base64Audio);
        }
    } catch (e) {
        console.error("Error invoking TTS service:", e);
    }
}

function playBase64Audio(base64Data) {
    stopAudioPlayback();
    if (!elements.globalAudioPlayer) return;
    
    elements.globalAudioPlayer.src = `data:audio/mp3;base64,${base64Data}`;
    const activeLangName = elements.languageSelect.options[elements.languageSelect.selectedIndex].text;
    const activeSpeaker = elements.speakerSelect.options[elements.speakerSelect.selectedIndex].text.split(" ")[0];
    
    if (elements.voicePlayingLang) elements.voicePlayingLang.innerText = `${activeLangName} Voice (${activeSpeaker})`;
    if (elements.voicePlayerContainer) elements.voicePlayerContainer.classList.remove("hidden");
    
    elements.globalAudioPlayer.play()
        .then(() => {
            if (elements.audioPlayPauseBtn) elements.audioPlayPauseBtn.innerHTML = '<i class="fa-solid fa-pause"></i>';
        })
        .catch(e => {
            console.error(e);
            if (elements.voicePlayerContainer) elements.voicePlayerContainer.classList.add("hidden");
        });
        
    elements.globalAudioPlayer.onended = () => {
        if (elements.voicePlayerContainer) elements.voicePlayerContainer.classList.add("hidden");
    };
    
    if (elements.audioPlayPauseBtn) {
        elements.audioPlayPauseBtn.onclick = () => {
            if (elements.globalAudioPlayer.paused) {
                elements.globalAudioPlayer.play();
                elements.audioPlayPauseBtn.innerHTML = '<i class="fa-solid fa-pause"></i>';
            } else {
                elements.globalAudioPlayer.pause();
                elements.audioPlayPauseBtn.innerHTML = '<i class="fa-solid fa-play"></i>';
            }
        };
    }
    
    if (elements.audioStopBtn) {
        elements.audioStopBtn.onclick = stopAudioPlayback;
    }
}

function stopAudioPlayback() {
    if (elements.globalAudioPlayer) {
        elements.globalAudioPlayer.pause();
        elements.globalAudioPlayer.currentTime = 0;
        elements.globalAudioPlayer.src = "";
    }
    if (elements.voicePlayerContainer) elements.voicePlayerContainer.classList.add("hidden");
}

// ==========================================================================
// SPEECH-TO-TEXT (STT) RECORDING COMPONENT
// ==========================================================================
function setupSTTHandlers() {
    if (!elements.micBtn) return;
    elements.micBtn.addEventListener("click", startVoiceRecording);
    elements.stopMicBtn.addEventListener("click", stopVoiceRecording);
    elements.cancelMicBtn.addEventListener("click", cancelVoiceRecording);
}

async function startVoiceRecording() {
    if (state.isRecording) return;
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        state.isRecording = true;
        state.audioChunks = [];
        state.mediaRecorder = new MediaRecorder(stream);
        
        state.mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) state.audioChunks.push(event.data);
        };
        
        state.mediaRecorder.onstop = processRecordedAudio;
        state.mediaRecorder.start();
        
        const activeLangName = elements.languageSelect.options[elements.languageSelect.selectedIndex].text;
        if (elements.recLangLabel) elements.recLangLabel.innerText = activeLangName;
        if (elements.micRecordingUI) elements.micRecordingUI.classList.remove("hidden");
    } catch (e) {
        alert("Microphone permission required.");
    }
}

function stopVoiceRecording() {
    if (!state.isRecording || !state.mediaRecorder) return;
    state.mediaRecorder.stop();
    state.mediaRecorder.stream.getTracks().forEach(track => track.stop());
    state.isRecording = false;
    if (elements.micRecordingUI) elements.micRecordingUI.classList.add("hidden");
}

function cancelVoiceRecording() {
    if (!state.isRecording || !state.mediaRecorder) return;
    state.mediaRecorder.onstop = null;
    state.mediaRecorder.stop();
    state.mediaRecorder.stream.getTracks().forEach(track => track.stop());
    state.isRecording = false;
    state.audioChunks = [];
    if (elements.micRecordingUI) elements.micRecordingUI.classList.add("hidden");
}

async function processRecordedAudio() {
    const audioBlob = new Blob(state.audioChunks, { type: "audio/wav" });
    state.audioChunks = [];
    const typingBubble = appendMessageBubble("bot", "", { isTyping: true });
    
    try {
        const formData = new FormData();
        formData.append("file", audioBlob, "voice_input.wav");
        formData.append("mode", "transcribe");
        formData.append("language_code", elements.languageSelect.value);
        
        const res = await fetch(`${BASE_URL}/api/stt`, { method: "POST", body: formData });
        if (typingBubble) typingBubble.remove();
        
        if (res.ok) {
            const data = await res.json();
            const transcript = data.transcript || data.text || "";
            if (transcript.trim()) {
                elements.chatInputTextarea.value = transcript;
                elements.chatInputTextarea.dispatchEvent(new Event("input"));
                submitUserMessage();
            }
        }
    } catch (e) {
        if (typingBubble) typingBubble.remove();
    }
}

// ==========================================================================
// DOCUMENT DIGITIZATION & OCR (SARVAM VISION) COMPONENT
// ==========================================================================
function setupOCRHandlers() {
    if (!elements.ocrBtn) return;
    elements.ocrBtn.addEventListener("click", (e) => {
        e.preventDefault();
        elements.ocrFileInput.click();
    });
    elements.ocrFileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) handleOCRUpload(e.target.files[0]);
    });
}

async function pollJobStatus(jobId, onComplete, onError, onProgress) {
    let isDone = false;
    const interval = setInterval(async () => {
        if (isDone) return;
        try {
            const res = await fetch(`${BASE_URL}/api/job/${jobId}`);
            if (res.ok) {
                const data = await res.json();
                if (data.status === "COMPLETED") {
                    isDone = true;
                    clearInterval(interval);
                    onComplete(data.result);
                } else if (data.status === "FAILED") {
                    isDone = true;
                    clearInterval(interval);
                    onError(data.error || "Job failed");
                } else if (data.status === "PROCESSING" && data.result) {
                    if (onProgress) onProgress(data.result);
                }
            } else {
                isDone = true;
                clearInterval(interval);
                onError("Failed to fetch job status");
            }
        } catch (e) {
            isDone = true;
            clearInterval(interval);
            onError("Network error during polling");
        }
    }, 5000);
}

async function handleOCRUpload(file) {
    const allowedExts = [".pdf", ".png", ".jpg", ".jpeg", ".webp"];
    const ext = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
    
    if (!allowedExts.includes(ext) || file.size > 50 * 1024 * 1024) {
        alert("Invalid file structure or size exceeds 50MB limit.");
        return;
    }
    
    const userMsgContent = file.type.startsWith("image/") ? `📷 **[Uploaded Document for OCR]**` : `📷 **[Uploaded PDF for OCR]**\n\n📄 *\"${file.name}\"*`;
    
    if (file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = (e) => {
            appendMessageBubble("user", `${userMsgContent}\n\n![Uploaded Image](${e.target.result})`);
        };
        reader.readAsDataURL(file);
    } else {
        appendMessageBubble("user", userMsgContent);
    }

    state.messages.push({ role: "user", content: userMsgContent });
    const typingBubble = appendMessageBubble("bot", "", { isTyping: true });
    
    try {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("language_code", elements.languageSelect.value);
        
        const res = await fetch(`${BASE_URL}/api/ocr`, { method: "POST", body: formData });
        
        if (res.ok) {
            const data = await res.json();
            pollJobStatus(data.job_id, (result) => {
                if (typingBubble) typingBubble.remove();
                const textResult = result.text ? `📷 **[Extracted OCR Content]**\n\n${result.text}` : `📷 **[Digitization Failed]**`;
                appendMessageBubble("bot", textResult);
                state.messages.push({ role: "assistant", content: textResult });
            }, (error) => {
                if (typingBubble) typingBubble.remove();
                appendMessageBubble("bot", `📷 **[Error]** ${error}`);
            });
        }
    } catch (e) {
        if (typingBubble) typingBubble.remove();
        appendMessageBubble("bot", "📷 **[Connection Error]**");
    }
}

// ==========================================================================
// RAG GROUNDING / DOCUMENT UPLOAD COMPONENT
// ==========================================================================
function setupRAGHandlers() {
    if (!elements.useRagToggle || !elements.dropzone) return;
    
    elements.useRagToggle.addEventListener("click", () => {
        state.useRAG = !state.useRAG;
        elements.useRagToggle.className = `action-btn ${state.useRAG ? "active" : ""}`;
        elements.ragStatusText.innerText = state.useRAG ? "ON" : "OFF";
    });

    const dropzone = elements.dropzone;
    dropzone.addEventListener("click", () => elements.fileInput.click());
    dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) handleFileUpload(e.dataTransfer.files[0]);
    });
    
    elements.fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) handleFileUpload(e.target.files[0]);
    });

    elements.clearDocsBtn.addEventListener("click", clearRAGKnowledge);
}

async function handleFileUpload(file) {
    const allowedExts = [".pdf", ".txt", ".md", ".json", ".docx"];
    const ext = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
    if (!allowedExts.includes(ext) || file.size > 50 * 1024 * 1024) return;
    
    const userMsgContent = `📚 **[Uploaded to Knowledge Base]**\n\n📄 *"${file.name}"*`;
    appendMessageBubble("user", userMsgContent);
    state.messages.push({ role: "user", content: userMsgContent });
    
    elements.uploadProgressContainer.innerHTML = "";
    elements.uploadProgressContainer.classList.remove("hidden");
    
    try {
        const formData = new FormData();
        formData.append("file", file);
        const res = await fetch(`${BASE_URL}/api/upload`, { method: "POST", body: formData });
        
        if (res.ok) {
            const data = await res.json();
            pollJobStatus(data.job_id, (result) => {
                
                let progressBubble = document.getElementById(`progress-${data.job_id}`);
                if (progressBubble) progressBubble.remove();
                
                const timeMsg = result.processing_time_seconds ? `\n\n⏱️ **Processing Time:** ${result.processing_time_seconds} seconds` : "";
                const msgContent = `✅ **[Knowledge Base Updated]**\n\nSuccessfully indexed: *${file.name}*${timeMsg}`;
                appendMessageBubble("bot", msgContent);
                state.messages.push({ role: "assistant", content: msgContent });

                setTimeout(() => {
                    elements.uploadProgressContainer.classList.add("hidden");
                    scanServerStatus();
                }, 1000);
            }, (error) => {
                elements.uploadProgressContainer.classList.add("hidden");
                appendMessageBubble("bot", `⚠️ **[Upload Error]** ${error}`);
            }, (progressResult) => {
                const parts = progressResult.parts;
                if (!parts) return;
                
                let html = "";
                for (const partId in parts) {
                    const p = parts[partId];
                    let percent = 0;
                    let color = "var(--primary)"; // blue
                    let label = `Part ${partId} (Processing)`;
                    
                    if (p.status === "QUEUED") {
                        color = "#f39c12"; // yellow
                        label = `Part ${partId} (Waiting in Queue)`;
                    } else if (p.status === "COMPLETED") {
                        percent = 100;
                        color = "var(--success)"; // green
                        label = `Part ${partId} (Completed)`;
                    } else if (p.total_chunks > 0) {
                        percent = Math.min(99, Math.round((p.progress_chunks / p.total_chunks) * 100));
                        label = `Part ${partId} (Processing - ${percent}%)`;
                    }
                    
                    html += `
                    <div style="margin-bottom: 12px;">
                        <span style="font-size: 0.85rem; font-weight: 500; margin-bottom: 6px; display: block;">${label}</span>
                        <div class="upload-progress-bar" style="background: var(--surface); height: 8px; border-radius: 4px; overflow: hidden;">
                            <div class="upload-progress-fill" style="width: ${percent}%; background: ${color}; height: 100%; transition: width 0.3s ease;"></div>
                        </div>
                    </div>`;
                }
                elements.uploadProgressContainer.innerHTML = html;
                
                // Update the chat bubble progress text
                let progressBubble = document.getElementById(`progress-${data.job_id}`);
                
                if (data.status === "COMPLETED") {
                    if (!progressBubble) {
                        progressBubble = document.createElement("div");
                        progressBubble.id = `progress-${data.job_id}`;
                        progressBubble.className = "message bot";
                        elements.chatMessages.appendChild(progressBubble);
                    }
                    
                    let filename = "Document";
                    if (progressResult.parts) {
                        const firstPart = Object.values(progressResult.parts)[0];
                        if (firstPart && firstPart.file_name) filename = firstPart.file_name;
                    }
                    const procTime = progressResult.processing_time_seconds ? progressResult.processing_time_seconds : "0.00";
                    
                    progressBubble.innerHTML = `
                    <div class="message-content">
                        ✅ <strong>[Knowledge Base Updated]</strong><br><br>
                        Successfully indexed: <em>${filename}</em><br><br>
                        ⏱️ <span style="color: #0dcaf0;">Processing Time:</span> ${procTime} seconds
                    </div>`;
                    
                    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
                } else if (progressResult.total_chunks > 0) {
                    const globalPercent = Math.min(99, Math.round((progressResult.progress_chunks / progressResult.total_chunks) * 100));
                    const statusText = `Processed ${progressResult.progress_chunks} / ${progressResult.total_chunks} chunks... (${globalPercent}%)`;
                    
                    if (!progressBubble) {
                        progressBubble = document.createElement("div");
                        progressBubble.id = `progress-${data.job_id}`;
                        progressBubble.className = "message bot";
                        elements.chatMessages.appendChild(progressBubble);
                    }
                    progressBubble.innerHTML = `<div class="message-content">⏳ <strong>Processing Multi-Part Document:</strong> ${statusText}</div>`;
                    elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
                }
            });
        }
    } catch (e) {
        elements.uploadProgressContainer.classList.add("hidden");
    }
}

async function clearRAGKnowledge() {
    if (!confirm("Clear database?")) return;
    try {
        const res = await fetch(`${BASE_URL}/api/clear-docs`, { method: "POST" });
        if (res.ok) scanServerStatus();
    } catch (e) { console.error(e); }
}

// ==========================================================================
// CHAT SESSION & CONVERSATION HISTORY MANAGEMENT
// ==========================================================================
async function initializeSessions() {
    try {
        const res = await fetch(`${BASE_URL}/api/history`);
        if (res.ok) {
            const data = await res.json();
            state.sessions = data.sessions;
        }
    } catch(e) {
        console.error("Failed to load history");
    }
    
    const storedCurrentId = localStorage.getItem("sarvam_chat_current_session_id");
    
    if (state.sessions.length > 0) {
        state.currentSessionId = storedCurrentId || state.sessions[0].session_id;
        const currentSession = state.sessions.find(s => s.session_id === state.currentSessionId) || state.sessions[0];
        state.messages = currentSession.messages || [];
        renderChatMessages();
        renderSessionsList();
    } else {
        createNewSession();
    }
}

function setupSessionHandlers() {
    if (elements.newChatBtn) elements.newChatBtn.addEventListener("click", () => createNewSession());
    
    const historyHeader = document.getElementById("history-header");
    const historyContent = document.getElementById("history-content");
    const historyToggleIcon = document.getElementById("history-toggle-icon");
    
    if (historyHeader && historyContent) {
        historyHeader.addEventListener("click", () => {
            historyContent.classList.toggle("collapsed");
            if (historyToggleIcon) {
                historyToggleIcon.classList.toggle("rotated");
            }
        });
    }
}

async function deleteSession(sessionId) {
    try {
        const res = await fetch(`${BASE_URL}/api/history/${sessionId}`, { method: 'DELETE' });
        if (res.ok) {
            state.sessions = state.sessions.filter(s => s.session_id !== sessionId);
            if (state.currentSessionId === sessionId) {
                if (state.sessions.length > 0) {
                    state.currentSessionId = state.sessions[0].session_id;
                    state.messages = state.sessions[0].messages || [];
                    localStorage.setItem("sarvam_chat_current_session_id", state.currentSessionId);
                } else {
                    createNewSession();
                    return;
                }
            }
            renderSessionsList();
            renderChatMessages();
        } else {
            console.error("Failed to delete session");
        }
    } catch(e) { console.error(e); }
}

function createNewSession() {
    const sessionId = "session_" + Date.now();
    const newSession = { session_id: sessionId, title: "New Chat", messages: [] };
    state.sessions.unshift(newSession);
    state.currentSessionId = sessionId;
    state.messages = [];
    
    localStorage.setItem("sarvam_chat_current_session_id", sessionId);
    renderSessionsList();
    renderChatMessages();
}

function renderSessionsList() {
    if (!elements.sessionsList) return;
    elements.sessionsList.innerHTML = "";
    
    state.sessions.forEach(session => {
        const li = document.createElement("li");
        li.className = session.session_id === state.currentSessionId ? "active" : "";
        li.innerHTML = `
            <div class="session-title">
                <i class="fa-regular fa-message"></i>
                <span title="${session.title}">${session.title}</span>
            </div>
            <button class="delete-session-btn" title="Delete Chat"><i class="fa-solid fa-trash-can"></i></button>
        `;
        
        li.addEventListener("click", (e) => {
            if (e.target.closest(".delete-session-btn")) {
                deleteSession(session.session_id);
                return;
            }
            state.currentSessionId = session.session_id;
            state.messages = session.messages || [];
            localStorage.setItem("sarvam_chat_current_session_id", session.session_id);
            renderSessionsList();
            renderChatMessages();
        });
        
        elements.sessionsList.appendChild(li);
    });
}

function renderChatMessages() {
    if (!elements.chatMessages) return;
    elements.chatMessages.innerHTML = "";
    
    if (state.messages.length === 0) {
        renderWelcomeScreen();
        return;
    }
    
    state.messages.forEach(msg => {
        appendMessageBubble(msg.role === "user" ? "user" : "bot", msg.content, {
            rag_applied: msg.rag_applied,
            rag_sources: msg.rag_sources,
            reasoning_content: msg.reasoning_content
        });
    });
}

function renderWelcomeScreen() {
    elements.chatMessages.innerHTML = `
        <div class="message system-welcome">
            <div class="welcome-card card">
                <div class="welcome-icon-wrapper"><i class="fa-solid fa-sparkles"></i></div>
                <h2>How can I assist you today?</h2>
                <p>Corporate assistant powered by <strong>Sarvam AI</strong>.</p>
                <div class="suggested-queries">
                    <div class="suggestion-chips">
                        <button class="chip" data-query="Explain how RAG grounding works.">💡 RAG Grounding</button>
                        <button class="chip" data-query="Help me write a professional leave request email.">📝 Leave Request Email</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    setupSuggestedChips();
}

// ==========================================================================
// KNOWLEDGE BASE CLEAR HANDLER
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
    const clearDocsBtn = document.getElementById("clear-docs-btn");
    if (clearDocsBtn) {
        clearDocsBtn.addEventListener("click", async () => {
            const confirmClear = confirm("Are you sure you want to completely erase the corporate knowledge base?");
            if (!confirmClear) return;
            
            try {
                clearDocsBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Clearing...`;
                const res = await fetch(`${BASE_URL}/api/rag/clear`, {
                    method: "DELETE"
                });
                
                if (res.ok) {
                    showToast("Knowledge Base successfully cleared.");
                    
                    // Clear UI visual elements
                    const docsList = document.getElementById("user-documents-list");
                    if (docsList) {
                        docsList.innerHTML = '<li class="empty-sources">No documents uploaded yet.</li>';
                    }
                    
                    const chunkStatus = document.getElementById("indexed-chunks");
                    if (chunkStatus) {
                        chunkStatus.innerText = "0 chunks";
                    }
                } else {
                    showToast("Failed to clear Knowledge Base.");
                }
            } catch (err) {
                console.error(err);
                showToast("Error clearing Knowledge Base.");
            } finally {
                clearDocsBtn.innerHTML = `<i class="fa-solid fa-trash-can"></i> Clear Knowledge Base`;
            }
        });
    }
});