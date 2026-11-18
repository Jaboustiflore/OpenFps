@echo off
cd /d "%~dp0"
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw run_openfps.py
    exit /b
)
where py >nul 2>&1
if %errorlevel%==0 (
    start "" pyw -3 run_openfps.py
    exit /b
)
where python >nul 2>&1
if %errorlevel%==0 (
    python run_openfps.py
    if errorlevel 1 pause
    exit /b
)
echo Python nest pas installe.
echo Installe-le depuis le Microsoft Store (cherche "Python 3.13"),
echo puis relance ce fichier.
pause
