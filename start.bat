@echo off
echo Starting MTG Purchase Optimizer...
echo Open http://localhost:8000 in your browser.
echo Press Ctrl+C to stop.
echo.
:: Try python from PATH first, then common Anaconda/Miniconda locations
where python >nul 2>nul
if %errorlevel% == 0 (
    python main.py
) else if exist "%USERPROFILE%\anaconda3\python.exe" (
    "%USERPROFILE%\anaconda3\python.exe" main.py
) else if exist "%USERPROFILE%\miniconda3\python.exe" (
    "%USERPROFILE%\miniconda3\python.exe" main.py
) else (
    echo ERROR: Python not found.
    echo Install Python 3.11+ or Anaconda, then run:
    echo   pip install -r requirements.txt
    echo   python -m playwright install chromium
)
pause
