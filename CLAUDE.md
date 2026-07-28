# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 개발 문서 업데이트 규칙

코드 변경 커밋 시 아래 항목이 바뀌었다면 **이 파일(CLAUDE.md)과 PRD/PRD.md를 함께 업데이트**한다:

- 핵심 아키텍처/패턴 변경 (세션 수집기 로직, 타임아웃 값, 대기 전략 등)
- GUI 동작 규칙 변경 (표시 형식, 포커스 처리, 창 동작 등)
- install.py 명령 생성 방식 변경
- 새 함수/클래스/파일 추가로 구조가 바뀐 경우
- 엣지 케이스 처리 방식 변경

변경 범위가 작고 코드에서 자명한 경우(변수명 변경, 로그 추가 등)는 생략 가능.

## Project Overview

Windows 탐색기 우클릭 컨텍스트 메뉴에서 이미지→PDF 변환 및 PDF 병합을 수행하는 유틸리티. **관리자 권한 불필요(HKCU 레지스트리 사용)**, Python 없는 환경에서도 동작하는 단일 exe 배포.

전체 사양은 [PRD/PRD.md](PRD/PRD.md)를 참조.

## Tech Stack

- **Python** + **PyMuPDF (fitz)** — 이미지/PDF 단일 처리 인터페이스
- **Tkinter** — GUI (내장, 추가 의존성 없음)
- **pywin32 (win32com)** — HWP→PDF 변환용 한컴오피스 COM (변환·병합 모두, 한컴 설치 PC에서만 동작)
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

1. 각 프로세스가 **자기 엔트리 파일** `TEMP/pdf_maker_{mode}_session/{pid}_{ns}.txt`에 경로를 1회 write
2. `TEMP/pdf_maker_{mode}_lock.txt` 없으면 → lock 생성(마스터) → adaptive wait → 엔트리들 수집 → 엔트리/lock 삭제 → 작업 실행
3. lock 있으면 → 조용히 종료
4. lock 파일 생성 후 **15초** 초과 시 스테일 처리 (이전 크래시 대비). 엔트리는 30초 초과 시 이전 크래시 잔재로 무시·청소.

⚠ **공유 session.txt에 동시 append 금지** — Windows에서 프로세스 간 append는 원자적이지 않아, onedir로 startup이 빨라지자 N개 동시 쓰기가 겹쳐 줄 유실/뒤섞임 발생(개수 부족·깨진 경로 에러). 그래서 **프로세스마다 별도 파일**에 쓰고 마스터가 디렉터리를 glob해 수집한다(경쟁 원천 제거). 15프로세스×10회 동시성 테스트 통과.

**Adaptive wait**: 새 엔트리가 감지될 때마다 deadline 600ms 연장. Explorer가 순차적으로 exe를 실행할 때 모든 파일이 수집될 때까지 대기.

마스터 선출 직후 **"파일 수집 중..." 인디케이터 팝업** 표시 (`_run_with_indicator`).

**⚡ 시작 반응성**: `main.py`는 최상단에서 `converter`(무거운 fitz)를 import하지 않는다. 슬레이브는 _try_master 후 즉시 종료(fitz 로드 안 함), 마스터는 인디케이터 창을 먼저 띄운 *뒤* fitz를 로드한다 → 클릭 즉시 "실행 중" 피드백.

코드 구조 (`main.py`):
- `_session_dir(mode)` → 엔트리 파일 디렉터리 경로
- `_try_master(mode, file_path)` → 엔트리 파일 기록 + lock 선점, bool 반환
- `_collect_master(mode)` → adaptive wait 후 엔트리 수집·정리, 경로 목록 반환
- `_run_with_indicator(mode, root, label)` → 백그라운드 collect + 인디케이터 UI

**convert 모드**: 마스터가 수집된 파일 일괄 변환 → 통합 완료 팝업 1개  
**merge 모드**: 마스터가 병합 GUI 실행

## converter.py 핵심 패턴

```python
import fitz  # PyMuPDF — 이미지/PDF 모두 fitz.open() 단일 처리

SUPPORTED_IMG = {".jpg", ".jpeg", ".png", ".bmp"}
SUPPORTED_HWP = {".hwp", ".hwpx"}  # 한컴 COM 필요 (convert·merge 양쪽)
SUPPORTED_ALL = SUPPORTED_IMG | {".pdf"} | SUPPORTED_HWP  # gui.py도 여기서 import

def image_to_pdf(img_path: Path) -> Path:
    doc = fitz.open()
    img_doc = fitz.open(str(img_path))
    rect = img_doc[0].rect
    img_doc.close()
    page = doc.new_page(width=rect.width, height=rect.height)
    # img_doc.tobytes()(Document.write, PDF 직렬화 전용)를 이미지 문서에 쓰면
    # PyMuPDF 1.27+에서 _as_pdf_document assert 실패로 매번 크래시(2026-07-28 발견).
    # insert_image(stream=...)는 원본 인코딩 바이트가 필요하므로 파일을 직접 읽는다.
    page.insert_image(page.rect, stream=img_path.read_bytes())
    output = resolve_output_path(img_path.with_suffix(".pdf"))
    doc.save(str(output))
    doc.close()
    return output

def merge_files(file_paths, output_path, progress_cb=None, cancel_flag=None):
    result = fitz.open()
    errors = []
    for i, path in enumerate(file_paths):
        if cancel_flag and cancel_flag.is_set():
            result.close(); raise CancelledError()
        try:
            src = fitz.open(str(path))
            if src.is_pdf:
                result.insert_pdf(src)
            else:
                pdf_bytes = src.convert_to_pdf()
                pdf_src = fitz.open("pdf", pdf_bytes)
                result.insert_pdf(pdf_src)
                pdf_src.close()
            src.close()
        except Exception as e:
            errors.append((path, e))   # 실패 파일 건너뛰고 계속
        if progress_cb:
            progress_cb(i + 1, len(file_paths), path.name)
    result.save(str(output_path))
    result.close()
    return errors  # 빈 리스트면 전체 성공
```

## HWP → PDF 변환 (한컴 COM, convert·merge 양쪽)

`.hwp`/`.hwpx`는 fitz가 못 여므로 한컴오피스 COM으로 PDF 변환한다. **convert(각각 개별 PDF)·merge(1개로 병합) 모두 지원.**

- `_hwp_session_convert(jobs, progress_cb)` → 코어. `jobs=[(src, dst)]`를 한컴 **1세션**으로 각각 `dst`에 PDF 저장 (승인창 1회·성능). `(성공 dst 목록, [(src, 예외)])` 반환. pywin32/한컴 미설치·개별 실패는 예외로 잡아 스킵.
- `_hwp_save_pdf(hwp, dst)` → 현재 문서를 PDF로 저장하는 헬퍼. **`SaveAs("PDF")` 금지** — 한컴에 저장된 인쇄 '모아 찍기' 설정(`PrintMethod=4`=2쪽)을 물려받아 **2-up 가로 PDF**로 나온다(원본 6쪽→가로 3장). 대신 `PrintToPDFEx` 액션 + `PrintMethod=0`(1쪽씩)으로 원본 쪽 구성 그대로 저장. 프린터 스풀은 비동기라 `_wait_for_file`로 파일 생성 대기. `Execute`가 실패(프린터 부재 등)하면 `SaveAs`로 폴백(2-up이라도 PDF는 생성).
- `hwp_batch_to_pdf(paths, cb)` → **convert 모드**: 각 HWP를 원본 옆 `.pdf`(충돌 시 `_N`)로 개별 변환.
- `hwp_to_pdf(path)` → 단일 변환 (main.py 단일파일 merge 경로용).
- `merge_files`: 루프 진입 전 HWP를 TEMP에 임시 PDF 일괄 변환(`pdfmaker_hwp_*.pdf`) → 루프에서 `insert_pdf` → `finally`에서 임시 PDF 정리.
- COM 주의: merge/convert는 워커 스레드에서 도므로 `pythoncom.CoInitialize()`/`CoUninitialize()` 짝 필수. **취소(cancel_flag)는 HWP 세션 중간엔 안 먹음**(세션 단위).
- **팝업 3종 억제** (모두 우리 자동화 인스턴스 한정 — 사용자의 일반 한글엔 영향 없음):
  1. 보안 '모두 허용' → `RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")` (1st=모듈유형, 2nd=레지스트리 `HKCU\Software\HNC\HwpAutomation\Modules`에 등록된 DLL ID). **그 레지스트리 값이 있어야 효과** → `install.py`가 **번들된 `FilePathCheckerModule.dll`(217KB, `src/`에 포함, 빌드 시 `_internal`)을 [메뉴 등록] 시 자동 등록**(`_register_security_module`). 파이썬/pyhwpx 불필요.
  2. '상위 버전에서 작성한 문서' → `Open(path, "", "versionwarning:False;suspendpassword:True")` (3번째 인자, inflearn 검증).
  3. 확인만 있는 기타 정보성 팝업 → `SetMessageBoxMode(0x1)` (OK-only 자동확인. ⚠ `0xFFFFFF`는 '자동설정 해제'라 반대 효과).
- PDF 저장은 `_hwp_save_pdf`(PrintToPDFEx), 문서 닫기는 `hwp.Clear(1)`.
- **실조건검증(2026-07-20)**: `[.hwp+.pdf+.png]` 병합 5쪽 통과 + `3×.hwp` 개별 변환 각각 통과(쪽수·순서 보존, errors 없음). **`.hwpx`만 미검증**(로직은 `.hwp`와 동일 경로).
- **2-up 모아찍기 수정(2026-07-22)**: `SaveAs("PDF")`가 `PrintMethod=4`를 물려받아 6쪽 원본이 가로 3장 2-up으로 나오던 버그를 `PrintToPDFEx`+`PrintMethod=0`으로 해결. 실조건검증: 실제 원본으로 `6쪽 / 595×841 세로 / errors 없음`, 1쪽=표지 단독 렌더 확인. 근거: 한컴 개발자 포럼 `forum.developer.hancom.com/t/saveas-pdf/1670`.

## Output Rules

- 출력 위치: 첫 번째 파일과 같은 폴더 (GUI에서 파일 추가해도 고정)
- 출력 파일명 충돌: `merged_1.pdf`, `merged_2.pdf`... / 이미지변환: `a_1.pdf`, `a_2.pdf`...
- 페이지 크기 = 이미지 원본 해상도 (여백 없음, 메타데이터 없음)
- merge 모드에서 파일 1개: GUI 없이 즉시 처리 (이미지→변환, PDF→복사)
- 병합 초기 파일 순서: 파일명 오름차순 (세션 수집 순서가 비결정적이므로)

## GUI Rules

- ESC = 취소/닫기, Enter = 확인/실행
- 파일 목록: **번호 포함** (`1. filename.jpg`) 표시, 마우스 오버 시 전체 경로 툴팁
- 중복 파일 추가 허용 (같은 파일 2회 = 2페이지)
- 진행바 팝업: 모달 아님, 항상 topmost
- 취소/X 클릭 시: 확인 없이 즉시 취소 → 부분 생성 파일 삭제
- ProgressPopup: threading.Thread + queue.Queue + after(50, _poll) 패턴으로 Tkinter 스레드 안전성 확보
- `_FileListFrame._refresh_display()`: 파일 추가/제거/이동 후 Listbox 전체 갱신 (번호 재정렬 + 선택 복원)
- `MergeWindow`: 초기화 시 topmost+focus_force → 200ms 후 topmost 해제 (포커스 보장)
- `_center()`: withdraw/deiconify 패턴으로 창 위치 설정 시 깜빡임 제거
- `show_result_popup(parent, title, message, outputs)`: 변환/병합 **완료 팝업**(기존 `messagebox.showinfo` 대체). 버튼 `[폴더 열기]`(`explorer /select,<첫 파일>`)·`[PDF 열기]`(`os.startfile`로 outputs 전부 열기 — 개수 제한 없음)·`[닫기]`. **세 버튼 모두 클릭 시 창을 닫는다**(2026-07-28: 3개 중 하나만 고르면 되므로 열기 버튼도 클릭 즉시 닫히도록 변경 — 이전엔 열기 후에도 창이 남아있어 따로 닫기를 눌러야 했음). `outputs` 중 **실제 존재하는 것만** 열기 대상이고, 하나도 없으면 열기 버튼 숨김. `Enter`=PDF 열기(후 닫힘) / `ESC`=닫기. `wait_visibility()`→`grab_set()`→`wait_window()`로 모달(호출측이 이후 `root.destroy()` 해도 클릭 시간 보장). convert 일괄·merge 병합·단일파일 즉시처리 4곳 모두 이 팝업 사용.

## Registry Keys (install.py)

```
HKCU\Software\Classes\SystemFileAssociations\.{jpg,jpeg,png,bmp}\shell\pdf_maker_convert\
  MUIVerb = "이미지 → PDF 변환"
  command = "<exe경로>" convert "%1"
  MultiSelectModel = Player

HKCU\Software\Classes\SystemFileAssociations\.{hwp,hwpx}\shell\pdf_maker_convert\
  MUIVerb = "HWP → PDF 변환"      # 라벨만 다름, 동일 convert 서브커맨드 (각각 개별 PDF)
  command = "<exe경로>" convert "%1"
  MultiSelectModel = Player

HKCU\Software\Classes\SystemFileAssociations\.{jpg,jpeg,png,bmp,pdf,hwp,hwpx}\shell\pdf_maker_merge\
  MUIVerb = "PDF로 병합"
  command = "<exe경로>" merge "%1"
  MultiSelectModel = Player
```

PyInstaller frozen 환경에서 exe 경로는 `sys.executable`로 자동 감지. 개발 모드에서는 `pythonw.exe` 우선 사용(콘솔 창 방지). 이미 등록된 경우 조용히 덮어쓰기.

`install()`은 우클릭 메뉴 등록 후 `_register_security_module()`도 호출 → 번들 DLL 경로를 `HKCU\Software\HNC\HwpAutomation\Modules\FilePathCheckerModule`에 기록해 '모두 허용' 팝업을 억제한다(DLL은 frozen이면 `sys._MEIPASS`(_internal), dev면 `src/`에서 탐색; 없으면 조용히 스킵). uninstall은 이 값을 지우지 않는다(다른 한글 자동화 도구가 같은 표준 값명을 쓸 수 있어, 삭제 위험 > 잔재 무해).
