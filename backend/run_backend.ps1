#!/usr/bin/env pwsh
<#
PowerShell helper to run the backend without a virtual environment.

This script:
- moves to the `backend` folder
- ensures `python` is available on PATH
- installs `requirements.txt` into the user site-packages (`--user`) to avoid needing a venv
- runs the FastAPI app using `uvicorn` as a module

Usage (PowerShell):
  cd path\to\project\backend
  .\run_backend.ps1
#>

$ErrorActionPreference = 'Stop'

# scriptDir is the folder containing this script (backend/)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

Write-Host "Launching backend from: $PWD"

# Verify python exists
try {
    $pythonCmd = Get-Command python -ErrorAction Stop
} catch {
    Write-Error "Python executable not found in PATH. Install Python or add it to PATH."
    exit 1
}

Write-Host "Using: $($pythonCmd.Path)"

Write-Host "Installing requirements (user site-packages)..."
& python -m pip install --upgrade pip
& python -m pip install --user -r requirements.txt

Write-Host "Starting uvicorn (app.main:app) on 127.0.0.1:8000..."
& python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
