@echo off
cd /d "%~dp0"
echo [%date% %time%] demarrage > openfps_log.txt
where python >> openfps_log.txt 2>&1
python --version >> openfps_log.txt 2>&1
python -c "import tkinter, sys; print(tkinter ok, sys.version)" >> openfps_log.txt 2>&1
python -c "import PIL; print(pillow ok)" >> openfps_log.txt 2>&1
if errorlevel 1 python -m pip install --quiet --user pillow >> openfps_log.txt 2>&1
python run_openfps.py >> openfps_log.txt 2>&1
if errorlevel 1 (
    echo.
    echo Une erreur est survenue. Detail dans openfps_log.txt :
    type openfps_log.txt
    pause
)
