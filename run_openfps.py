"""Point d'entrée utilisé par PyInstaller pour fabriquer OpenFPS.exe."""
import sys

from openfps.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
