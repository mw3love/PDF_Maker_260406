rem Build rationale (--onedir / --add-data / non-ASCII comments removed here
rem to avoid cmd.exe batch-parser corruption on multi-byte REM lines) is
rem documented in CLAUDE.md's Build section. Keep this file ASCII-only.
rem "python -m PyInstaller" instead of bare "pyinstaller": the bare command
rem may be missing from PATH depending on how pip installed it (2026-08-03).
python -m PyInstaller --onedir --windowed --name pdf_maker --noconfirm ^
  --hidden-import win32com --hidden-import win32com.client ^
  --hidden-import pythoncom --hidden-import pywintypes ^
  --add-data "src/FilePathCheckerModule.dll;." ^
  src/main.py
