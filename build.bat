rem --onedir: 매 실행 압축해제 없음 → 시작 빠름 (우클릭 다중선택 시 특히).
rem 배포는 dist\pdf_maker 폴더 통째로(zip). 등록 exe = dist\pdf_maker\pdf_maker.exe
rem --add-data: 한글 보안모듈 DLL 번들 → install 시 자동 등록('모두 허용' 팝업 억제, 파이썬 불필요)
pyinstaller --onedir --windowed --name pdf_maker ^
  --hidden-import win32com --hidden-import win32com.client ^
  --hidden-import pythoncom --hidden-import pywintypes ^
  --add-data "src/FilePathCheckerModule.dll;." ^
  src/main.py
