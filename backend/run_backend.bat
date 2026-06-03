@echo off
rem Batch helper to run the backend without a virtual environment.
rem Usage: open cmd.exe, cd to the backend folder and run run_backend.bat

cd /d %~dp0

where python >nul 2>&1
if errorlevel 1 (
  echo Python not found in PATH. Install Python or add it to PATH.
  exit /b 1
)

echo Installing requirements (user site-packages)...
python -m pip install --upgrade pip
python -m pip install --user -r requirements.txt

echo Starting uvicorn (app.main:app) on 127.0.0.1:8000...
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
