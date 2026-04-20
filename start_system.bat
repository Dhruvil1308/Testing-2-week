@echo off
TITLE GuniVox System Launcher
echo ===================================================
echo   Starting GuniVox V3 System...
echo ===================================================

echo [1/3] Launching Python Backend...
start "GuniVox Backend" cmd /k "call .venv\Scripts\activate && pip install -r requirements.txt --quiet && python server.py"

echo [2/3] Launching Ngrok Tunnel...
if exist "D:\ngrok.exe" (
    start "Ngrok Tunnel" cmd /k "D:\ngrok.exe http 8000"
) else (
    start "Ngrok Tunnel" cmd /k "ngrok http 8000"
)

echo [3/3] Launching React Frontend...
start "GuniVox Frontend" cmd /k "npm run dev"

echo.
echo All servers are starting!
echo Please wait a moment for the frontend to load...
echo.
timeout /t 5
start http://localhost:3000

echo System is Live! You can close this window if you want, 
echo but keep the other 3 terminal windows open.
pause
