# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Windows 탐색기 우클릭 컨텍스트 메뉴에서 이미지→PDF 변환 및 PDF 병합을 수행하는 유틸리티. **관리자 권한 불필요(HKCU 레지스트리 사용)**, Python 없는 환경에서도 동작하는 단일 exe 배포.

전체 사양은 [PRD/PRD.md](PRD/PRD.md)를 참조.

## Tech Stack

- **Python** + **PyMuPDF (fitz)** — 이미지/PDF 단일 처리 인터페이스
- **Tkinter** — GUI (내장, 추가 의존성 없음)
- **PyInstaller** — 단일 exe 빌드
- **winreg (HKCU)** — 레지스트리 등록/해제

## Project Structure

```
pdf_maker/
├── src/
│   ├── main.py      # CLI 진입점 + 세션 수집기 (마스터 선출 로직)
│   ├── converter.py # 변환/병합 순수 로직 (fitz 사용)
│   ├── gui.py       # GUI 3종: 도우미/병합/진행바 팝업
│   └── install.py   # 레지스트리 등록/해제 (winreg, sys.executable 감지)
├── build.bat        # PyInstaller 빌드
└── requirements.txt # PyMuPDF>=1.23.0
```

## Commands

```bat
# 의존성 설치
pip install PyMuPDF pyinstaller

# exe 빌드
build.bat

# 개발 중 직접 실행
python src/main.py                        # 도우미 GUI
python src/main.py convert "파일경로"     # 이미지→PDF 변환
python src/main.py merge "파일경로"       # 병합 GUI
python src/main.py install                # 레지스트리 등록
python src/main.py uninstall             # 레지스트리 삭제
```

## Key Architecture: 세션 수집기 (Session Collector)

`MultiSelectModel = Player` 때문에 파일 n개 선택 시 exe가 n번 동시 호출됨. Lock 파일로 마스터 프로세스 1개를 선출하는 패턴:

1. `TEMP/pdf_maker_{mode}_session.txt`에 파일경로 원자적 append
2. `TEMP/pdf_maker_{mode}_lock.txt` 없으면 → lock 생성(마스터) → 400ms 대기 → session.txt 읽기 → lock/session 삭제 → 작업 실행
3. lock 있으면 → 조용히 종료
4. lock 파일 생성 후 5초 초과 시 스테일 처리 (이전 크래시 대비)

**convert 모드**: 마스터가 수집된 파일 일괄 변환 → 통합 완료 팝업 1개  
**merge 모드**: 마스터가 병합 GUI 실행

## converter.py 핵심 패턴

```python
import fitz  # PyMuPDF — 이미지/PDF 모두 fitz.open() 단일 처리

def image_to_pdf(img_path: Path) -> Path:
    doc = fitz.open()
    img_doc = fitz.open(str(img_path))   # 이미지를 1페이지 PDF로 열기
    rect = img_doc[0].rect
    page = doc.new_page(width=rect.width, height=rect.height)
    page.show_pdf_page(page.rect, img_doc, 0)
    output = resolve_output_path(img_path.with_suffix(".pdf"))
    doc.save(str(output))
    return output

def merge_files(file_paths, output_path, progress_cb=None, cancel_flag=None):
    result = fitz.open()
    errors = []
    for i, path in enumerate(file_paths):
        if cancel_flag and cancel_flag.is_set():
            result.close(); raise CancelledError()
        try:
            src = fitz.open(str(path))
            result.insert_pdf(src)
        except Exception as e:
            errors.append((path, e))   # 실패 파일 건너뛰고 계속
        if progress_cb:
            progress_cb(i + 1, len(file_paths), path.name)
    result.save(str(output_path))
    return errors  # 빈 리스트면 전체 성공
```

## Output Rules

- 출력 위치: 첫 번째 파일과 같은 폴더 (GUI에서 파일 추가해도 고정)
- 출력 파일명 충돌: `merged_1.pdf`, `merged_2.pdf`... / 이미지변환: `a_1.pdf`, `a_2.pdf`...
- 페이지 크기 = 이미지 원본 해상도 (여백 없음, 메타데이터 없음)
- merge 모드에서 파일 1개: GUI 없이 즉시 처리 (이미지→변환, PDF→복사)
- 병합 초기 파일 순서: 파일명 오름차순 (세션 수집 순서가 비결정적이므로)

## GUI Rules

- ESC = 취소/닫기, Enter = 확인/실행
- 파일 목록: 파일명만 표시, 마우스 오버 시 전체 경로 툴팁
- 중복 파일 추가 허용 (같은 파일 2회 = 2페이지)
- 진행바 팝업: 모달 아님, 항상 topmost
- 취소/X 클릭 시: 확인 없이 즉시 취소 → 부분 생성 파일 삭제
- ProgressPopup: threading.Thread + queue.Queue + after(50, _poll) 패턴으로 Tkinter 스레드 안전성 확보

## Registry Keys (install.py)

```
HKCU\Software\Classes\SystemFileAssociations\.{jpg,jpeg,png,bmp}\shell\pdf_maker_convert\
  MUIVerb = "이미지 → PDF 변환"
  command = "<exe경로>" convert "%1"
  MultiSelectModel = Player

HKCU\Software\Classes\*\shell\pdf_maker_merge\
  MUIVerb = "PDF로 병합"
  command = "<exe경로>" merge "%1"
  MultiSelectModel = Player
```

PyInstaller frozen 환경에서 exe 경로는 `sys.executable`로 자동 감지. 이미 등록된 경우 조용히 덮어쓰기.
