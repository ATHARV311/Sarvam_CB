import sqlite3
import os
import json
import logging
from threading import Lock

logger = logging.getLogger(__name__)

# Ensure DB directory exists
import tempfile
DB_DIR = tempfile.gettempdir()

DB_PATH = os.path.join(DB_DIR, "jobs.db")
db_lock = Lock()

def get_connection():
    # timeout=10 helps prevent "database is locked" errors during high concurrency
    return sqlite3.connect(DB_PATH, timeout=10)

def init_db():
    with db_lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    start_time REAL
                )
            ''')
            conn.commit()

def create_job(job_id: str, status: str = "PENDING", start_time: float = None):
    with db_lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO jobs (job_id, status, start_time)
                VALUES (?, ?, ?)
            ''', (job_id, status, start_time))
            conn.commit()

def update_job_status(job_id: str, status: str, result: dict = None, error: str = None, part_id: str = None):
    with db_lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            if part_id and result:
                cursor.execute('SELECT start_time, result FROM jobs WHERE job_id = ?', (job_id,))
                row = cursor.fetchone()
                existing_result = {}
                start_time = None
                if row:
                    start_time = row[0]
                    if row[1]:
                        try:
                            existing_result = json.loads(row[1])
                        except json.JSONDecodeError:
                            pass
                        
                parts = existing_result.get('parts', {})
                parts[part_id] = result
                existing_result['parts'] = parts
                
                # Aggregate global progress
                total = sum(p.get("total_chunks", 0) for p in parts.values())
                processed = sum(p.get("progress_chunks", 0) for p in parts.values())
                
                existing_result["progress_chunks"] = processed
                existing_result["total_chunks"] = total
                
                # Check for auto-completion
                total_parts = existing_result.get("total_parts", 1)
                all_completed = (len(parts) == total_parts) and all(p.get("status") == "COMPLETED" for p in parts.values())
                
                if all_completed:
                    status = "COMPLETED"
                    import time
                    if start_time:
                        existing_result["processing_time_seconds"] = round(time.time() - start_time, 2)
                elif status != "FAILED":
                    status = "PROCESSING"
                
                result_str = json.dumps(existing_result)
            else:
                result_str = json.dumps(result) if result else None
                
            cursor.execute('''
                UPDATE jobs 
                SET status = ?, result = ?, error = ?
                WHERE job_id = ?
            ''', (status, result_str, error, job_id))
            conn.commit()

def get_job(job_id: str) -> dict:
    with db_lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT status, result, error, start_time FROM jobs WHERE job_id = ?', (job_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            status, result_str, error, start_time = row
            job_data = {"status": status}
            
            if start_time:
                job_data["start_time"] = start_time
            if result_str:
                try:
                    job_data["result"] = json.loads(result_str)
                except json.JSONDecodeError:
                    job_data["result"] = result_str
            if error:
                job_data["error"] = error
                
            return job_data

def clear_jobs():
    with db_lock:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM jobs')
            conn.commit()

# Initialize the table when the module loads
init_db()
