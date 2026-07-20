pyinstaller --onefile --windowed --name pdf_maker ^
  --hidden-import win32com --hidden-import win32com.client ^
  --hidden-import pythoncom --hidden-import pywintypes ^
  src/main.py
