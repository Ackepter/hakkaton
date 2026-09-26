@echo off
echo Starting Smart Intersection...

REM Create venv if not exists
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt
)

REM Start backend in new window
start "Backend" cmd /k ".venv\Scripts\python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"

REM Start frontend in new window
if exist frontend\node_modules (
    start "Frontend" cmd /k "cd frontend && npm run dev"
) else (
    start "Frontend" cmd /k "cd frontend && npm install && npm run dev"
)

echo.
echo Backend:  http://localhost:8000
echo API Docs: http://localhost:8000/docs
echo Frontend: http://localhost:5173
echo.
pause
