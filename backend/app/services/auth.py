import os
import time
from typing import Optional
from passlib.context import CryptContext
import jwt
from tinydb import TinyDB, Query
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

# Authentication Configuration
SECRET_KEY = os.environ.get("JWT_SECRET", "super-secret-sarvam-key-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

security = HTTPBearer()

# NoSQL Database Setup (TinyDB)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
import tempfile
DB_DIR = os.path.join(tempfile.gettempdir(), "sarvam_auth_db")
os.makedirs(DB_DIR, exist_ok=True)
db = TinyDB(os.path.join(DB_DIR, "users.json"))
users_table = db.table('users')
pending_users_table = db.table('pending_users')
history_table = db.table('history')
documents_table = db.table('documents')

import bcrypt

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[int] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_delta if expires_delta else ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def generate_otp() -> str:
    return str(random.randint(100000, 999999))

def send_otp_email(to_email: str, otp: str):
    smtp_email = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")
    
    if not smtp_email or not smtp_password:
        print("WARNING: SMTP credentials not found in .env file.")
        return False

    msg = MIMEMultipart()
    msg['From'] = smtp_email
    msg['To'] = to_email
    msg['Subject'] = "Your Sarvam AI Verification Code"

    body = f"""
    <h2>Sarvam AI Assistant</h2>
    <p>Your one-time verification code is: <strong>{otp}</strong></p>
    <p>This code will expire in 5 minutes.</p>
    """
    msg.attach(MIMEText(body, 'html'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def get_user(username: str):
    UserQuery = Query()
    results = users_table.search(UserQuery.username == username)
    if results:
        return results[0]
    return None

def create_user(username: str, email: str, password: str):
    if get_user(username):
        raise ValueError("Username already registered")
    
    hashed_password = get_password_hash(password)
    user_doc = {
        "username": username,
        "email": email,
        "hashed_password": hashed_password,
        "created_at": time.time()
    }
    users_table.insert(user_doc)
    return {"username": username, "email": email}

async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        
        user = get_user(username)
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
            
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
