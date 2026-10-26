import os
import sys
import time
import logging
from celery import Celery

# Setup paths so we can import app modules
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from app.services.job_manager import update_job_status

# Delay imports to avoid circular dependencies and ensure they load inside the worker process
def get_services():
    from app.services.sarvam_client import sarvam_client
    from app.services.rag_engine import rag_engine
    return sarvam_client, rag_engine

logger = logging.getLogger(__name__)

from kombu import Exchange, Queue

# Initialize Celery pointing to RabbitMQ
celery_app = Celery(
    'corporate_assistant_tasks',
    broker='amqp://guest:guest@localhost:5672//'
)

# Optional configuration
celery_app.conf.update(
    task_queues=(
        Queue('sarvam', Exchange('Prix', type='direct'), routing_key='sarvam'),
    ),
    task_routes={
        'master_upload_task': {'queue': 'sarvam', 'routing_key': 'sarvam'},
        'process_upload_task': {'queue': 'sarvam', 'routing_key': 'sarvam'},
        'process_ocr_task': {'queue': 'sarvam', 'routing_key': 'sarvam'},
    },
    task_default_queue='sarvam',
    task_default_exchange='Prix',
    task_default_routing_key='sarvam',
    task_serializer='json',
    accept_content=['json'],  
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    worker_prefetch_multiplier=1, # Fetch 1 task at a time
    worker_enable_remote_control=False, # FIX FOR RABBITMQ 4.x ERROR
    worker_send_task_events=False
)

# Force declare the progress_updates queue immediately on startup
from kombu import Connection
try:
    with Connection(celery_app.conf.broker_url) as conn:
        channel = conn.channel()
        exchange = Exchange('Prix', type='direct', durable=True)
        queue = Queue('progress_updates', exchange, routing_key='progress', durable=True)
        queue.declare(channel=channel)
        print("[RabbitMQ] Successfully pre-declared 'progress_updates' queue.")
except Exception as e:
    print(f"[RabbitMQ] Could not pre-declare queue: {e}")

DB_DIR = os.path.join(BACKEND_ROOT, "db")

from kombu import Connection, Producer

def publish_progress_to_rabbitmq(job_id, file_name, processed, total):
    """Explicitly publishes a progress payload back into RabbitMQ."""
    try:
        with Connection(celery_app.conf.broker_url) as conn:
            import json
            producer = Producer(conn)
            payload = {
                "event": "chunk_progress",
                "job_id": job_id,
                "file_name": file_name,
                "progress_chunks": processed,
                "total_chunks": total,
                "status": "PROCESSING"
            }
            # Force RabbitMQ to create the queue if it doesn't exist yet
            progress_exchange = Exchange('Prix', type='direct', durable=True)
            progress_queue = Queue('progress_updates', progress_exchange, routing_key='progress', durable=True)
            
            producer.publish(
                json.dumps(payload),
                exchange=progress_exchange,
                routing_key='progress',
                declare=[progress_queue],
                content_type='application/json',
                content_encoding='utf-8'
            )
            print(f"[RabbitMQ] Published Progress Payload -> {payload}")
    except Exception as e:
        print(f"[RabbitMQ] Failed to publish progress: {e}")

@celery_app.task(name='master_upload_task')
def master_upload_task(job_id: str, file_path: str, file_name: str, start_time: float):
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    print(f"\n[Master] Intercepted upload {file_name} ({file_size_mb:.2f} MB)")
    
    num_parts = 1
    if file_name.lower().endswith('.pdf'):
        if file_size_mb >= 25:
            num_parts = 4
        elif file_size_mb >= 20:
            num_parts = 2
            
    if num_parts > 1:
        print(f"[Master] Splitting massive PDF {file_name} into {num_parts} sub-tasks...")
        try:
            from pypdf import PdfReader, PdfWriter
            with open(file_path, "rb") as f:
                reader = PdfReader(f)
                total_pages = len(reader.pages)
                
                pages_per_part = total_pages // num_parts
                parts_data = {}
                
                for part_idx in range(num_parts):
                    part_num = str(part_idx + 1)
                    writer = PdfWriter()
                    
                    start_page = part_idx * pages_per_part
                    # Last part takes all remaining pages to handle rounding
                    end_page = total_pages if part_idx == num_parts - 1 else (part_idx + 1) * pages_per_part
                    
                    for i in range(start_page, end_page):
                        writer.add_page(reader.pages[i])
                        
                    part_path = file_path.replace(".pdf", f"_part{part_num}.pdf")
                    with open(part_path, "wb") as f_out:
                        writer.write(f_out)
                        
                    parts_data[part_num] = {"status": "QUEUED", "progress_chunks": 0, "total_chunks": 0}
            
            print(f"[Master] Split successful: {total_pages} pages into {num_parts} parts. Dispatching to RabbitMQ...")
            
            # Preemptively register parts so the frontend sees them as QUEUED
            update_job_status(job_id, "PROCESSING", result={
                "total_parts": num_parts,
                "parts": parts_data
            })
            
            for part_num in parts_data.keys():
                part_path = file_path.replace(".pdf", f"_part{part_num}.pdf")
                process_upload_task.delay(job_id, part_path, file_name.replace(".pdf", f"_part{part_num}.pdf"), start_time, part_num)
                
            return
        except Exception as e:
            logger.error(f"[Master] Failed to split PDF: {e}. Falling back to single task.")
            
    # Standard single task fallback
    update_job_status(job_id, "PROCESSING", result={
        "total_parts": 1,
        "parts": {"1": {"status": "QUEUED", "progress_chunks": 0, "total_chunks": 0}}
    })
    process_upload_task.delay(job_id, file_path, file_name, start_time, "1")

@celery_app.task(name='process_upload_task')
def process_upload_task(job_id: str, file_path: str, file_name: str, start_time: float, part_id: str = "1"):
    print(f"\n[RabbitMQ Payload] Received job '{job_id}' (Part {part_id}) for file: {file_name}")
    update_job_status(job_id, "PROCESSING", result={"status": "PROCESSING", "progress_chunks": 0, "total_chunks": 0}, part_id=part_id)
    
    def on_progress(processed, total):
        print(f"[RabbitMQ Payload] ChromaDB Progress (Part {part_id}): Stored {processed}/{total} chunks.")
        update_job_status(job_id, "PROCESSING", result={"status": "PROCESSING", "progress_chunks": processed, "total_chunks": total}, part_id=part_id)
        publish_progress_to_rabbitmq(job_id, file_name, processed, total)
        
    try:
        sarvam_client, rag_engine = get_services()
        
        # Read the massive file from disk instead of passing it through RabbitMQ
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        is_scanned_pdf = False
        if file_name.lower().endswith('.pdf'):
            try:
                import io
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(file_bytes))
                
                # Check the first few pages for native text
                extracted_text = ""
                pages_to_check = min(5, len(reader.pages))
                for i in range(pages_to_check):
                    page_text = reader.pages[i].extract_text()
                    if page_text:
                        extracted_text += page_text
                
                # If we couldn't find much text (less than 50 chars per page on average), 
                # it's likely a scanned image PDF
                if len(extracted_text.strip()) < (pages_to_check * 50):
                    is_scanned_pdf = True
                    
            except Exception as e:
                logger.error(f"Error checking PDF for text: {e}")

        if is_scanned_pdf:
            logger.info(f"PDF {file_name} contains images. Routing to Sarvam Vision (OCR).")
            ocr_result = sarvam_client.digitize_document(file_bytes=file_bytes, file_name=file_name, language_code="en-IN")
            text_content = ocr_result.get("text", "")
            if ocr_result.get("success") and text_content:
                base_name = os.path.splitext(file_name)[0]
                md_filename = f"{base_name}_ocr.md"
                import tempfile
                md_file_path = os.path.join(tempfile.gettempdir(), md_filename)
                with open(md_file_path, "w", encoding="utf-8") as f:
                    f.write(text_content)
                
                index_result = rag_engine.add_document(md_file_path, md_filename, progress_callback=on_progress) if hasattr(rag_engine, 'add_document') else "RAG indexed block."
                processing_time = round(time.time() - start_time, 2)
                
                update_job_status(job_id, "PROCESSING", result={
                    "status": "COMPLETED",
                    "filename": file_name, 
                    "success": True, 
                    "details": index_result, 
                    "ocr": True, 
                    "processing_time": processing_time
                }, part_id=part_id)
            else:
                raise Exception(ocr_result.get("message", "OCR Failed"))
        else:
            index_result = rag_engine.add_document(file_path, file_name, progress_callback=on_progress) if hasattr(rag_engine, 'add_document') else "RAG indexed block."
            processing_time = round(time.time() - start_time, 2)
            
            update_job_status(job_id, "PROCESSING", result={
                "status": "COMPLETED",
                "filename": file_name, 
                "success": True, 
                "details": index_result,
                "ocr": False,
                "processing_time": processing_time
            }, part_id=part_id)
            
    except Exception as e:
        logger.error(f"Upload task failed: {e}")
        update_job_status(job_id, "PROCESSING", result={"status": "FAILED", "error": str(e)}, part_id=part_id)

@celery_app.task(name='process_ocr_task')
def process_ocr_task(job_id: str, file_path: str, file_name: str, language_code: str, start_time: float):
    print(f"\n[RabbitMQ Payload] Received OCR job '{job_id}' for file: {file_name}")
    update_job_status(job_id, "PROCESSING")
    
    def on_progress(processed, total):
        print(f"[RabbitMQ Payload] ChromaDB Progress: Stored {processed}/{total} chunks.")
        update_job_status(job_id, "PROCESSING", result={"progress_chunks": processed, "total_chunks": total})
        publish_progress_to_rabbitmq(job_id, file_name, processed, total)
        
    try:
        sarvam_client, rag_engine = get_services()
        
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        ocr_result = sarvam_client.digitize_document(file_bytes=file_bytes, file_name=file_name, language_code=language_code)
        text_content = ocr_result.get("text", "")
        if ocr_result.get("success") and text_content:
            base_name = os.path.splitext(file_name)[0]
            md_filename = f"{base_name}_ocr.md"
            import tempfile
            md_file_path = os.path.join(tempfile.gettempdir(), md_filename)
            with open(md_file_path, "w", encoding="utf-8") as f:
                f.write(text_content)
                
            index_result = rag_engine.add_document(md_file_path, md_filename, progress_callback=on_progress) if hasattr(rag_engine, 'add_document') else "RAG indexed block."
            update_job_status(job_id, "COMPLETED", result={
                "filename": file_name, 
                "success": True, 
                "text": text_content, 
                "details": index_result
            })
        else:
            update_job_status(job_id, "COMPLETED", result={
                "filename": file_name, 
                "success": False, 
                "text": "", 
                "error": ocr_result.get("message", "OCR Failed")
            })
    except Exception as e:
        logger.error(f"OCR task failed: {e}")
        update_job_status(job_id, "FAILED", error=str(e))
