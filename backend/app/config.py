import os
from dotenv import load_dotenv

# Calculate structural runtime directory anchors
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))      # backend/app
BASE_DIR = os.path.dirname(CURRENT_DIR)                       # backend

# ─── EXPLICIT MULTI-PATH DOTENV OVERRIDE ───
# Check backend/.env first
env_path_primary = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_path_primary):
    load_dotenv(dotenv_path=env_path_primary, override=True)
else:
    # Check backend/app/.env as a backup
    env_path_secondary = os.path.join(CURRENT_DIR, ".env")
    load_dotenv(dotenv_path=env_path_secondary, override=True)

class Settings:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Sarvam AI API Configurations
    SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
    SARVAM_BASE_URL = os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai")
    
    # Chat History Config
    MAX_HISTORY_LEN = int(os.getenv("MAX_HISTORY_LEN", 8))
    
    # Server configs
    PORT = int(os.getenv("PORT", 8000))
    HOST = os.getenv("HOST", "127.0.0.1")
    
    # Storage settings for document uploads & database
    UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
    DB_DIR = os.path.join(BASE_DIR, "db")
    
    def __init__(self):
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
        os.makedirs(self.DB_DIR, exist_ok=True)
        
        # Runtime terminal validation print block
        if not self.SARVAM_API_KEY:
            print("\n[WARNING] SARVAM_API_KEY extracted as EMPTY string from configuration file.")
        else:
            print(f"\n[SUCCESS] API Configuration linked cleanly. Key signature: {self.SARVAM_API_KEY[:6]}...")

settings = Settings()