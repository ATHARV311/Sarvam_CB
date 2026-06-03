Launching the backend without a virtual environment
-------------------------------------------------

If you prefer not to use a virtualenv, the repo includes helper scripts that install required packages into your user site-packages and launch the FastAPI app.

Files added:
- run_backend.ps1 — PowerShell script (Windows PowerShell / PowerShell Core)
- run_backend.bat — Windows CMD batch script

How to run (PowerShell):

1. Open PowerShell and change to the backend folder:

   cd path\to\project\backend

2. Run the script:

   .\run_backend.ps1

How to run (Command Prompt / CMD):

1. Open CMD and change to the backend folder:

   cd /d path\to\project\backend

2. Run the batch file:

   run_backend.bat

Notes:
- Scripts install dependencies using `pip install --user -r requirements.txt` to avoid modifying system-wide packages.
- Running without a venv may lead to package version conflicts with other projects. Prefer a venv if you can.
- The server starts uvicorn on `127.0.0.1:8000` with `--reload` for development.
