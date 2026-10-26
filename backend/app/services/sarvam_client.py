import requests
import logging
import re
import os
from dotenv import load_dotenv


from app.config import settings

# Force load the .env file globally across the system
# This checks both the inner app folder and outer backend directory
load_dotenv()
load_dotenv(dotenv_path=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")))
load_dotenv(dotenv_path=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

# ... (Leave the rest of your original SarvamClient code exactly as it is below this)

logger = logging.getLogger(__name__)

class SarvamClient:
    def __init__(self):
        self.api_key = os.getenv("SARVAM_API_KEY")
        self.base_url = "https://api.sarvam.ai"
        
        # Determine if we are in demo mode
        self.is_demo = not self.api_key or len(self.api_key.strip()) < 10
        if self.is_demo:
            logger.warning("SARVAM_API_KEY not found. Running in DEMO MODE (Mock Responses).")
            
    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
    def chat_complete(self, messages, model="sarvam-30b", temperature=0.7, max_tokens=4000):
        """
        Calls the Sarvam AI Chat Completions API.
        Compatible with OpenAI chat payloads.
        """
        if self.is_demo:
            return self._get_demo_chat_response(messages)
            
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        try:
            response = requests.post(url, json=payload, headers=self._get_headers(), timeout=60)
            if response.status_code == 200:
                data = response.json()
                # Ensure choices content is never empty if reasoning_content is present
                if "choices" in data:
                    for choice in data["choices"]:
                        msg = choice.get("message", {})
                        if msg and not msg.get("content") and msg.get("reasoning_content"):
                            msg["content"] = msg["reasoning_content"]
                return data
            else:
                logger.error(f"Sarvam API error: Status {response.status_code} - {response.text}")
                return {
                    "error": True,
                    "message": f"Sarvam API responded with status {response.status_code}: {response.text}"
                }
        except Exception as e:
            logger.error(f"Exception during Sarvam Chat Completion: {e}")
            return {
                "error": True,
                "message": f"Exception connecting to Sarvam AI: {str(e)}"
            }
            
    def speech_to_text(self, audio_bytes, filename="audio.wav", mode="transcribe", language_code="hi-IN"):
        """
        Calls Sarvam Saaras v3 Spech-to-Text API.
        Supports transcribing / translating Indian language speech.
        """
        if self.is_demo:
            return {
                "transcript": "Hello, this is a placeholder transcription since Sarvam AI is in demo mode.",
                "language_code": language_code,
                "confidence": 0.95
            }
            
        url = f"{self.base_url}/speech-to-text"
        headers = {
            "api-subscription-key": self.api_key
            # Do NOT specify Content-Type here, requests will set multipart boundary
        }
        
        files = {
            "file": (filename, audio_bytes, "audio/wav")
        }
        data = {
            "model": "saaras:v3",
            "mode": mode,
            "language_code": language_code
        }
        
        try:
            response = requests.post(url, headers=headers, files=files, data=data, timeout=30)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Sarvam STT API error: Status {response.status_code} - {response.text}")
                return {
                    "error": True,
                    "message": f"STT failed with status {response.status_code}"
                }
        except Exception as e:
            logger.error(f"Exception during Sarvam STT: {e}")
            return {
                "error": True,
                "message": f"Exception connecting to Sarvam STT: {str(e)}"
            }
    def _chunk_text(self, text, max_chars=450):
        """Slices a long text into chunks of at most max_chars characters."""
        # Simple split by punctuation or sentence ends (. ! ? | \n)
        raw_sentences = re.split(r'(?<=[.!?।\n])\s+', text)
        segments = []
        current_chunk = ""
        for sentence in raw_sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            # If a single sentence is longer than max_chars, hard-split it by spaces/words
            if len(sentence) > max_chars:
                if current_chunk:
                    segments.append(current_chunk)
                    current_chunk = ""
                words = sentence.split(" ")
                sub_chunk = ""
                for word in words:
                    if len(sub_chunk) + len(word) + 1 <= max_chars:
                        sub_chunk += (" " if sub_chunk else "") + word
                    else:
                        segments.append(sub_chunk)
                        sub_chunk = word
                if sub_chunk:
                    current_chunk = sub_chunk
            else:
                if len(current_chunk) + len(sentence) + 1 <= max_chars:
                    current_chunk += (" " if current_chunk else "") + sentence
                else:
                    segments.append(current_chunk)
                    current_chunk = sentence
        if current_chunk:
            segments.append(current_chunk)
        return segments

    def text_to_speech(self, text, language_code="hi-IN", speaker="ritu", pace=1.0):
        """
        Calls Sarvam Bulbul v3 Text-to-Speech API.
        Returns base64 encoded audio or raw bytes depending on design.
        We'll fetch raw audio bytes to stream or encode as base64 for frontend.
        """
        if self.is_demo:
            # We don't have synthesized voice in demo, we return mock status
            return {
                "is_demo": True,
                "audio_url": None,
                "message": "TTS requires a valid Sarvam API Key."
            }
            
        # Dynamically chunk text to comply with the 500 character API limit per segment
        if hasattr(text, "strip"):
            inputs = self._chunk_text(text)
        else:
            inputs = text
            
        url = f"{self.base_url}/text-to-speech"
        payload = {
            "inputs": inputs,
            "model": "bulbul:v3",
            "target_language_code": language_code,
            "speaker": speaker,
            "pace": pace,
            "temperature": 0.6
        }
        
        try:
            response = requests.post(url, json=payload, headers=self._get_headers(), timeout=60)
            if response.status_code == 200:
                # The response contains base64 audios or a link.
                # Let's inspect typical structure or return the JSON response directly.
                return response.json()
            else:
                logger.error(f"Sarvam TTS API error: Status {response.status_code} - {response.text}")
                return {
                    "error": True,
                    "message": f"TTS failed with status {response.status_code}"
                }
        except Exception as e:
            logger.error(f"Exception during Sarvam TTS: {e}")
            return {
                "error": True,
                "message": f"Exception connecting to Sarvam TTS: {str(e)}"
            }
            
    def digitize_document(self, file_bytes: bytes, file_name: str, language_code: str = "en-IN") -> dict:
        """
        Orchestrates document digitization. For PDFs larger than 10 pages,
        splits the document into chunks, processes sequentially, and concatenates results.
        """
        if self.is_demo:
            return self._digitize_single_file(file_bytes, file_name, language_code)

        try:
            if file_name.lower().endswith('.pdf'):
                import io
                from pypdf import PdfReader, PdfWriter
                
                reader = PdfReader(io.BytesIO(file_bytes))
                total_pages = len(reader.pages)
                
                if total_pages > 10:
                    logger.info(f"PDF has {total_pages} pages. Splitting into 10-page chunks...")
                    full_text = ""
                    chunk_jobs = []
                    
                    for i in range(0, total_pages, 10):
                        writer = PdfWriter()
                        for j in range(i, min(i + 10, total_pages)):
                            writer.add_page(reader.pages[j])
                            
                        chunk_bytes_io = io.BytesIO()
                        writer.write(chunk_bytes_io)
                        chunk_bytes = chunk_bytes_io.getvalue()
                        
                        chunk_name = f"{os.path.splitext(file_name)[0]}_part_{i//10 + 1}.pdf"
                        logger.info(f"Processing chunk {i//10 + 1}: pages {i+1} to {min(i + 10, total_pages)}")
                        
                        res = self._digitize_single_file(chunk_bytes, chunk_name, language_code)
                        if res.get("error"):
                            logger.error(f"Chunk processing failed: {res.get('message')}")
                            return {"error": True, "message": f"Failed to process PDF chunk {i//10 + 1}: {res.get('message')}"}
                        
                        full_text += f"\n\n<!-- PDF CHUNK {i//10 + 1} -->\n\n" + res.get("text", "")
                        chunk_jobs.append(res.get("job_id"))
                        
                    return {
                        "success": True,
                        "text": full_text.strip(),
                        "job_id": ",".join([str(j) for j in chunk_jobs if j])
                    }
        except Exception as e:
            logger.error(f"Error handling PDF chunking: {e}")
            return {"error": True, "message": f"Failed to split and process PDF: {str(e)}"}

        # If not PDF or <= 10 pages, process normally
        return self._digitize_single_file(file_bytes, file_name, language_code)

    def _digitize_single_file(self, file_bytes: bytes, file_name: str, language_code: str = "en-IN") -> dict:
        """
        Orchestrates the entire asynchronous Document Digitization (OCR) workflow:
        1. POST /doc-digitization/job/v1 to initialize the job and get a job_id.
        2. POST /doc-digitization/job/v1/upload-files to get signed Azure upload URL for the job.
        3. PUT file_bytes to Azure signed upload URL with x-ms-blob-type: BlockBlob header.
        4. POST /doc-digitization/job/v1/{job_id}/start to begin processing.
        5. Poll GET /doc-digitization/job/v1/{job_id}/status until job_state is Completed.
        6. POST /doc-digitization/job/v1/{job_id}/download-files to get download URL for output zip.
        7. Fetch the zip file and extract the document.md text in-memory.
        """
        if self.is_demo:
            return {
                "success": True,
                "text": (
                    "📷 **[DEMO MODE OCR RESULT]**\n\n"
                    "Since the system is running in **Demo Mode** (missing `SARVAM_API_KEY`), "
                    "no actual OCR call was made to the Sarvam Vision APIs.\n\n"
                    "In production, uploading an image (JPEG, PNG, scanned PDF) will trigger the "
                    "asynchronous Document Digitization workflow. Sarvam Vision will extract the text, "
                    "structure all complex tables into clean Markdown grids, preserve reading hierarchy, "
                    "and deliver a beautifully structured representation of your document across "
                    "22 Indian languages and English!"
                )
            }

        headers = self._get_headers()
        import time
        import zipfile
        import io

        try:
            # 1. Initialize the Digitization Job
            logger.info("Initializing document digitization job on Sarvam AI...")
            create_url = f"{self.base_url}/doc-digitization/job/v1"
            create_payload = {
                "job_parameters": {
                    "language": language_code if language_code else "en-IN",
                    "output_format": "md"
                }
            }
            create_res = requests.post(create_url, json=create_payload, headers=headers)
            if create_res.status_code != 202:
                logger.error(f"Failed to create digitization job: {create_res.status_code} - {create_res.text}")
                return {"error": True, "message": f"Create job request failed: {create_res.text}"}
                
            job_data = create_res.json()
            job_id = job_data.get("job_id")
            if not job_id:
                logger.error(f"Missing job_id in create response: {job_data}")
                return {"error": True, "message": "Missing job_id from Sarvam AI response."}
                
            logger.info(f"Digitization job initialized with ID: {job_id}")

            # 2. Get signed S3/Azure Upload URL
            logger.info("Requesting pre-signed S3/Azure upload URL...")
            upload_url_endpoint = f"{self.base_url}/doc-digitization/job/v1/upload-files"
            upload_payload = {
                "job_id": job_id,
                "files": [file_name]
            }
            
            res = requests.post(upload_url_endpoint, json=upload_payload, headers=headers)
            if res.status_code != 200:
                logger.error(f"Failed to get upload URL: {res.text}")
                return {"error": True, "message": f"Signed upload URL request failed: {res.text}"}
            
            upload_data = res.json()
            file_info = upload_data.get("upload_urls", {}).get(file_name, {})
            presigned_url = file_info.get("file_url") if isinstance(file_info, dict) else file_info
            
            if not presigned_url:
                logger.error(f"Missing upload URL in response: {upload_data}")
                return {"error": True, "message": "Missing presigned upload URL from Sarvam."}
                
            # 3. PUT file_bytes to pre-signed URL (requires Azure BlockBlob header)
            logger.info(f"Uploading file binary to presigned URL (Job: {job_id})...")
            content_type = "application/pdf" if file_name.lower().endswith(".pdf") else "image/png"
            put_headers = {
                "Content-Type": content_type,
                "x-ms-blob-type": "BlockBlob"
            }
            
            put_res = requests.put(presigned_url, data=file_bytes, headers=put_headers)
            if put_res.status_code not in [200, 201]:
                logger.error(f"Binary upload failed: {put_res.status_code} - {put_res.text}")
                return {"error": True, "message": f"S3 binary upload failed with status {put_res.status_code}"}
                
            # 4. Start Document processing job
            logger.info("Triggering async document intelligence job...")
            start_url = f"{self.base_url}/doc-digitization/job/v1/{job_id}/start"
            
            start_res = requests.post(start_url, json={}, headers=headers)
            if start_res.status_code not in [200, 202]:
                logger.error(f"Failed to start digitization job: {start_res.text}")
                return {"error": True, "message": f"Job start failed: {start_res.text}"}
                
            # 5. Polling for Job completion status
            status_url = f"{self.base_url}/doc-digitization/job/v1/{job_id}/status"
            max_retries = 30
            polling_interval = 2.0
            
            logger.info(f"Polling job {job_id} for completion...")
            for attempt in range(max_retries):
                time.sleep(polling_interval)
                status_res = requests.get(status_url, headers=headers)
                if status_res.status_code != 200:
                    logger.error(f"Status poll failed: {status_res.text}")
                    return {"error": True, "message": f"Job status polling failed: {status_res.text}"}
                
                status_data = status_res.json()
                job_status = status_data.get("job_state") or status_data.get("status")
                logger.info(f"Job {job_id} state on attempt {attempt+1}: {job_status}")
                
                if job_status and job_status.upper() == "COMPLETED":
                    break
                elif job_status and job_status.upper() == "FAILED":
                    logger.error(f"Sarvam Vision job failed: {status_data}")
                    return {"error": True, "message": "Document digitization job failed on Sarvam AI."}
            else:
                logger.error(f"Digitization job {job_id} timed out.")
                return {"error": True, "message": "Document digitization job timed out."}
                
            # 6. Fetch pre-signed download URLs for completed job files
            logger.info("Retrieving pre-signed download URLs...")
            download_url = f"{self.base_url}/doc-digitization/job/v1/{job_id}/download-files"
            download_res = requests.post(download_url, json={}, headers=headers)
            if download_res.status_code != 200:
                logger.error(f"Failed to get download URLs: {download_res.text}")
                return {"error": True, "message": f"Download URL retrieval failed: {download_res.text}"}
                
            download_data = download_res.json()
            download_urls = download_data.get("download_urls", download_data)
            
            output_url = None
            if isinstance(download_urls, dict):
                for fname, durl in download_urls.items():
                    actual_url = durl.get("file_url") if isinstance(durl, dict) else durl
                    if fname.endswith(".zip") or fname.endswith(".md"):
                        output_url = actual_url
                        break
                if not output_url and download_urls:
                    first_val = next(iter(download_urls.values()))
                    output_url = first_val.get("file_url") if isinstance(first_val, dict) else first_val
            
            if not output_url:
                logger.error(f"Missing output file in download links: {download_data}")
                return {"error": True, "message": "Could not find digitised output file link in download payload."}
                
            # 7. Download and extract in-memory zip file to retrieve markdown contents
            logger.info("Downloading OCR results archive...")
            file_res = requests.get(output_url)
            if file_res.status_code != 200:
                logger.error(f"Failed to download extracted file: {file_res.status_code}")
                return {"error": True, "message": "Failed to download OCR markdown file from S3."}
                
            # Parse ZIP archive strictly in-memory
            zip_bytes = io.BytesIO(file_res.content)
            with zipfile.ZipFile(zip_bytes) as z:
                namelist = z.namelist()
                md_file = next((name for name in namelist if name.endswith(".md")), None)
                if md_file:
                    extracted_text = z.read(md_file).decode("utf-8")
                else:
                    logger.error(f"No markdown file found in output archive. Available files: {namelist}")
                    return {"error": True, "message": "No markdown file found in the output archive."}

            return {
                "success": True,
                "text": extracted_text,
                "job_id": job_id
            }
            
        except Exception as e:
            logger.error(f"Exception during Document Digitization: {e}")
            return {
                "error": True,
                "message": f"Exception orchestrating document digitization: {str(e)}"
            }
            
    def _get_demo_chat_response(self, messages):
        """
        Returns a beautifully formatted mock response to allow frontend test runs without a key.
        """
        last_user_message = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        
        # Simple rule-based mock engine to feel interactive
        lowered = last_user_message.lower()
        
        greeting_response = (
            "नमस्ते! Hello there! 🌟\n\n"
            "Welcome to the **Sarvam AI Corporate Assistant** demo!\n\n"
            "Currently, the system is running in **Demo Mode** because the `SARVAM_API_KEY` was not detected in the environment settings.\n\n"
            "Once configured with your Sarvam API Key, this chatbot will connect directly to the high-performance **`sarvam-30b`** or **`sarvam-105b`** LLMs, enabling high-quality multi-lingual reasoning, translation, and localized Indian context."
        )
        
        rag_response = (
            "🔍 **Document Knowledge Base Query (Demo Mode)**\n\n"
            "I noticed you are asking questions. In full deployment, this chatbot utilizes a **Retrieval-Augmented Generation (RAG)** pipeline to index company documentation (PDFs, Handbooks) locally.\n\n"
            "When you ask a question, the backend will fetch relevant text passages, inject them into the LLM context, and answer grounded strictly in your upload files."
        )
        
        voice_response = (
            "🎙️ **Speech Integration (Demo Mode)**\n\n"
            "This chatbot is built to support the revolutionary **Saaras v3 (STT)** and **Bulbul v3 (TTS)** models. "
            "In production, you can speak in 22 Indian languages, have it auto-translated, and hear the chatbot speak back in highly expressive voices (like Ritu, Aditya, Shubh) across multiple languages."
        )
        
        if "hello" in lowered or "hi" in lowered or "hey" in lowered or "greeting" in lowered or "नमस्ते" in lowered:
            text = greeting_response
        elif "document" in lowered or "file" in lowered or "upload" in lowered or "pdf" in lowered or "rag" in lowered:
            text = rag_response
        elif "voice" in lowered or "speech" in lowered or "audio" in lowered or "speak" in lowered or "stt" in lowered or "tts" in lowered:
            text = voice_response
        else:
            text = (
                f"🤖 **[DEMO MODE ACTIVE]**\n\n"
                f"You asked: *\"{last_user_message}\"*\n\n"
                f"To unlock real AI responses using Sarvam AI models, please edit the backend `.env` file and set a valid `SARVAM_API_KEY`.\n\n"
                f"Meanwhile, feel free to explore the interactive visual elements, change chat themes, upload documents to index, and experiment with the UI layout."
            )
            
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": text
                    },
                    "finish_reason": "stop"
                }
            ],
            "demo": True
        }
def summarize_web_data(query: str, web_data: str, target_language: str = "English") -> str:
    """
    Takes raw text/snippets from the web search engine and uses Sarvam AI
    to synthesize a clean, coherent answer for the user in their preferred language.
    """
    # If the web search failed or returned an error message, pass it through
    if "error" in web_data.lower() or "failed" in web_data.lower():
        return web_data

    # Map readable names to explicit language directives to stop token corruption/Pinyin crossing
    language_directives = {
        "English": "English text output format",
        "Hindi": "Hindi (हिंदी - देवनागरी लिपि)",
        "Bengali": "Bengali (বাংলা)",
        "Tamil": "Tamil (தமிழ்)",
        "Telugu": "Telugu (తెలుగు)",
        "Kannada": "Kannada (ಕನ್ನಡ)",
        "Malayalam": "Malayalam (മലയാളം)",
        "Marathi": "Marathi (मराठी)",
        "Gujarati": "Gujarati (ગુજરાતી)",
        "Punjabi": "Punjabi (ਪੰਜਾਬੀ)"
    }
    directive = language_directives.get(target_language, "English text output format")

    # Create an explicit multilingual synthesis prompt
    web_prompt = f"""You are a corporate assistant. Synthesize a clean, professional, and direct answer 
to the user's query using the live web search results provided below.

CRITICAL DIRECTIVE: You MUST formulate your entire final output response natively using the {directive} alphabet characters. 
DO NOT write in Romanized phonetic script or any other language. Completely translate the facts into that script.

User Query: {query}

Web Search Results:
{web_data}

Answer:"""
    
    try:
        # Use an explicit system message alongside the user payload to clamp down on instructions
        payload_messages = [
            {
                "role": "system", 
                "content": f"You are a helpful assistant. You must respond entirely in the native alphabet of {directive}."
            },
            {"role": "user", "content": web_prompt}
        ]
        
        api_response = sarvam_client.chat_complete(messages=payload_messages)
        api_response = sarvam_client.chat_complete(messages=payload_messages)
        
        # Standard, safe evaluation block to stop syntax crashing
        if isinstance(api_response, dict) and "choices" in api_response and len(api_response["choices"]) > 0:
            return api_response["choices"][0].get("message", {}).get("content", "")
        return f"Here is what I found on the web:\n\n{web_data}"
    except Exception as e:
        logger.error(f"Error in summarize_web_data synthesis loop: {e}")
        return f"Here is what I found on the web:\n\n{web_data}"
sarvam_client = SarvamClient()
