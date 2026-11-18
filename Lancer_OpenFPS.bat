@echo off
cd /d "%~dp0"
py -3 --version >nul 2>&1
if %errorlevel%==0 (
    start "" pyw -3 run_openfps.py
    exit /b
)
python --version >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw run_openfps.py
    exit /b
)
echo Python nest pas installe.
echo Installe-le depuis https://www.python.org/downloads/ (coche "Add python.exe to PATH"),
echo puis relance ce fichier.
pause
