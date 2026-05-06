@echo off
title Semantic Matcher Full Startup
echo =======================================================
echo   Semantic Matcher - Full Startup Script
echo =======================================================

echo.
echo [1/4] Starting Milvus (Docker Compose)...
cd milvus-setup
docker-compose up -d
cd ..

echo.
echo [2/4] Running Jupyter Notebook (datasets_v2.ipynb)...
echo NOTE: This might take a few minutes if it's processing embeddings...
jupyter nbconvert --to notebook --execute datasets_v2.ipynb --inplace

echo.
echo [3/4] Resetting and Starting FastAPI Backend on Port 8001...
echo Killing any existing process on port 8001...
FOR /F "tokens=5" %%T IN ('netstat -a -n -o ^| find "LISTENING" ^| findstr :8001') DO (
    TaskKill.exe /PID %%T /F >nul 2>&1
)

echo Starting Uvicorn in a new window...
cd backend
start "Semantic Matcher Backend" cmd /k "uvicorn main:app --reload --port 8001"
cd ..

echo.
echo [4/4] Opening Web UI...
echo Waiting 5 seconds for backend to start...
timeout /t 5 /nobreak >nul
start http://localhost:8001

echo.
echo =======================================================
echo   All services started!
echo   - Milvus is running in Docker.
echo   - Data ingestion completed.
echo   - Backend is running in a separate window.
echo   - Web UI has been opened in your browser.
echo =======================================================
pause
