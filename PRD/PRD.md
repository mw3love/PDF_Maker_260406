# PDF Maker PRD

## 제품 목적
Windows 탐색기에서 파일 선택 → 우클릭만으로 이미지→PDF 변환 및 다파일 PDF 병합을 완료하는 유틸리티.
**핵심 철학: 사용자 동선 최소화. 별도 앱 실행 없이 탐색기 컨텍스트 메뉴에서 즉시 완결.**

---

## 기술 스택
| 항목 | 선택 | 이유 |
|------|------|------|
| 언어 | Python | 빠른 개발, 라이브러리 풍부 |
| PDF | PyMuPDF (fitz) | 이미지/PDF 모두 `fitz.open()` 단일 처리 |
| GUI | Tkinter | Python 내장, 의존성 없음 |
| 배포 | PyInstaller 단일 exe | Python 없는 환경에서 실행 |
| 레지스트리 | HKCU | **관리자 권한 불필요** (UX 마찰 제거) |

---

## 프로젝트 구조
```
pdf_maker/
├── src/
│   ├── main.py      # CLI 진입점 + 세션 수집기
│   ├── converter.py # 변환/병합 순수 로직
│   ├── gui.py       # GUI 3종 (도우미/병합/진행바)
│   └── install.py   # 레지스트리 등록/해제
├── build.bat        # PyInstaller 빌드
└── requirements.txt # PyMuPDF>=1.23.0
```

---

## exe 실행 모드
```
pdf_maker.exe           → 도우미 GUI (더블클릭)
pdf_maker.exe convert "file" → 이미지→PDF 변환 (우클릭)
pdf_maker.exe merge "file"   → PDF 병합 GUI (우클릭)
pdf_maker.exe install        → 레지스트리 등록
pdf_maker.exe uninstall      → 레지스트리 삭제
```

---

## 우클릭 메뉴 등록

**위치**: Windows 11 "추가 옵션 표시" 안 (시스템 전체 변경 없이 안전)

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

---

## 핵심 패턴: 세션 수집기

`MultiSelectModel = Player`로 인해 **파일 n개 선택 시 exe가 n번 호출**됨.
→ 모든 프로세스가 거의 동시에 실행되므로, lock 파일 방식으로 하나만 마스터로 선출:

```
각 프로세스:
  1. TEMP/pdf_maker_{mode}_session/{pid}_{ns}.txt 에 경로 1회 write (프로세스별 파일)
  2. TEMP/pdf_maker_{mode}_lock.txt 없으면 → lock 생성 (마스터)
       → adaptive wait → 엔트리 디렉터리 수집 → 엔트리/lock 삭제 → 작업 실행
  3. lock 있으면 → 조용히 종료

Adaptive wait: 새 엔트리 감지 시 deadline을 600ms 연장 (Explorer 순차 실행 대응)
스테일 처리: lock 15초 / 엔트리 30초 초과 시 무효화 (이전 크래시 대비)
```

⚠ **프로세스별 파일 방식인 이유**: 공유 session.txt에 N개가 동시 append하면 Windows에서
프로세스 간 append가 원자적이지 않아 줄 유실/뒤섞임 발생(개수 부족·에러). onedir로 startup이
빨라지자 이 race가 드러나, 프로세스마다 별도 파일에 쓰고 마스터가 glob 수집하도록 변경.

마스터 선출 직후 "파일 수집 중..." 인디케이터 팝업 표시 (indeterminate 진행바).
→ 시작 반응성: main.py는 무거운 fitz를 인디케이터 창 표시 *뒤*에 로드(클릭 즉시 창).

**convert 모드**: 마스터가 수집된 모든 파일 일괄 변환 → 통합 완료 팝업 1개
**merge 모드**: 마스터가 병합 GUI 실행

---

## 지원 형식 및 출력 규칙

- **입력**: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.pdf`, `.hwp`, `.hwpx`
- **HWP → PDF**: 한컴오피스 COM(`HWPFrame.HwpObject`) `PrintToPDFEx`(PrintMethod=0, 1쪽씩)로 변환. `SaveAs("PDF")`는 한컴 인쇄 '모아 찍기' 설정(2쪽)을 물려받아 2-up 가로 PDF가 나오므로 쓰지 않는다(프린터 부재 시에만 폴백). **한컴오피스 설치 PC 전용** — 미설치/pywin32 미설치 시 해당 파일만 건너뛰고(errors) 나머지는 계속.
  - **convert 모드**: 여러 HWP를 **각각 개별 PDF**로 일괄 변환 (원본 옆 `.pdf`). 우클릭 메뉴 라벨 "HWP → PDF 변환". 보안모듈 등록 PC에서는 승인창 없이 무음성 동작.
  - **merge 모드**: HWP를 임시 PDF로 변환 후 다른 파일과 **1개로 병합**.
- **비지원 형식**: 무시 (지원 파일만 처리). 지원 파일이 0개면 오류 팝업 후 종료.
- **출력 위치**: 첫 번째 파일과 같은 폴더 (GUI에서 추가한 파일에도 고정)
- **출력 파일명**: `merged.pdf` → 충돌 시 `merged_1.pdf`, `merged_2.pdf`...
- **이미지→PDF 충돌**: `a_1.pdf`, `a_2.pdf`... (덮어쓰기 안 함)
- **페이지 크기**: 이미지 원본 해상도 = 페이지 크기 (여백 없음)
- **PDF 메타데이터**: 없음 (콘텐츠만)

---

## 단일 파일 예외 처리
`merge` 모드에서 파일 1개만 선택 시:
- 이미지 → PDF 변환 (GUI 없이 바로)
- HWP/HWPX → PDF 변환 (GUI 없이 바로, 한컴 COM)
- PDF → `merged.pdf`로 복사 (GUI 없이 바로)

---

## converter.py 설계

```python
import fitz  # PyMuPDF

def image_to_pdf(img_path: Path) -> Path:
    doc = fitz.open()
    img_doc = fitz.open(str(img_path))   # 이미지를 1페이지 문서로 열어 크기만 조회
    rect = img_doc[0].rect
    img_doc.close()
    page = doc.new_page(width=rect.width, height=rect.height)
    # insert_image(stream=...)는 원본 인코딩 바이트가 필요 — img_doc.tobytes()는
    # PDF 직렬화 전용이라 이미지 문서에 쓰면 PyMuPDF 1.27+에서 크래시(2026-07-28 수정)
    page.insert_image(page.rect, stream=img_path.read_bytes())
    output = resolve_output_path(img_path.with_suffix(".pdf"))
    doc.save(str(output))
    return output

def merge_files(file_paths: List[Path], output_path: Path,
                progress_cb=None, cancel_flag=None):
    result = fitz.open()
    errors = []
    for i, path in enumerate(file_paths):
        if cancel_flag and cancel_flag.is_set():
            result.close(); raise CancelledError()
        try:
            src = fitz.open(str(path))  # 이미지/PDF 모두 동일 처리
            result.insert_pdf(src)
        except Exception as e:
            errors.append((path, e))   # 실패 파일 건너뛰고 계속
        if progress_cb:
            progress_cb(i + 1, len(file_paths), path.name)
    result.save(str(output_path))
    return errors  # 빈 리스트면 전체 성공
```

---

## GUI 명세

### 공통 규칙
- 기본 Tkinter 테마
- **ESC = 취소/닫기, Enter = 확인/실행**
- 파일 목록: 파일명만 표시, 마우스 오버 시 전체 경로 툴팁
- 중복 파일 추가 허용 (같은 파일 2회 = 2페이지)
- 창 크기 기억 없음

### 도우미 GUI (더블클릭)
```
┌───────────────────────────────────────┐
│  PDF 변환 도구                  [X]   │
├───────────────────────────────────────┤
│  ┌──────────────────────────┐  [▲]   │
│  │ (파일을 추가하세요)       │  [▼]   │
│  └──────────────────────────┘  [+추가]│
│                                [−제거]│
│  ○ 각 파일을 별도 PDF로 변환          │
│  ● 하나의 PDF로 병합                  │
│  저장 파일명: [merged.pdf          ] │  ← 빈칸 이탈 시 기본값 복원
│  저장 위치: 첫 번째 파일의 폴더       │
│  ☐ 완료 후 폴더 열기                  │  ← 기본 off (2026-08-03)
│  ─────────────────────────────────── │
│  [메뉴 등록]  [메뉴 제거]            │  ← install.py 호출
│            [취소]  [실행]            │
└───────────────────────────────────────┘
```
- "개별 변환" 선택 시 파일명 입력란 비활성화
- [실행] 후 도우미 GUI 유지, 진행바 별도 팝업
- 작업 완료 후 파일 목록 유지 (자동 초기화 없음)
- [메뉴 등록]: 조용히 덮어쓰기 → "등록 완료 (※ exe 이동 시 재등록 필요)" 팝업

### 병합 GUI (우클릭 merge, 파일 2개 이상)
```
┌───────────────────────────────────────┐
│  PDF 병합                       [X]   │
├───────────────────────────────────────┤
│  ┌──────────────────────────┐  [▲]   │
│  │ 01_intro.jpg             │  [▼]   │
│  │ 02_chapter.pdf           │  [+추가]│
│  └──────────────────────────┘  [−제거]│
│  저장 파일명: [merged.pdf          ] │
│  저장 위치: 첫 번째 파일의 폴더       │
│  ☐ 완료 후 폴더 열기                  │  ← 기본 off (2026-08-03)
│       [취소]        [병합 시작]       │  ← 파일 0개면 비활성화
└───────────────────────────────────────┘
```
- 초기 파일 순서: **파일명 오름차순** (세션 수집 순서는 비결정적이므로)
- [+추가]: `askopenfilenames` (다중 선택 지원)

### 진행바 팝업
```
┌──────────────────────────────┐
│  변환 중...          topmost │
│  [████████░░░░░░]           │
│  3 / 10 파일                │
│  photo_003.jpg              │
│          [취소]             │
└──────────────────────────────┘
```
- **모달 아님, 항상 화면 위(topmost)**
- 파일 1개도 표시 (일관성)
- [취소] / [X]: 확인 없이 즉시 취소 → 부분 생성 파일 삭제
- 완료 시: 팝업 닫힘 → 성공 메시지 팝업 → 종료

### 오류/완료 메시지
- **변환 성공**: "5개 파일이 PDF로 변환되었습니다."
- **병합 성공**: "merged.pdf 생성 완료\nC:\경로\merged.pdf"
- **부분 실패**: 성공 메시지 + 실패 파일 목록 (나머지는 계속 진행)
- **전체 실패 / 지원 파일 없음**: 오류 팝업 후 종료

**완료 팝업** (`show_result_popup`, 2026-08-03 개정): 변환/병합 완료 처리.
- **PDF는 항상 자동으로 열린다**(`os.startfile`, 개수 제한 없음 — 탭형 뷰어면 탭으로 열림). 이전엔 `[PDF 열기]` 버튼 클릭이 필요했으나, 사용자가 매번 눌러야 하는 번거로움을 없애기 위해 완료 즉시 자동 실행으로 변경.
- **성공 시엔 팝업 창 자체가 뜨지 않는다** — PDF가 자동으로 열리는 것 자체가 완료 확인이므로 별도 알림 불필요. **에러/부분실패일 때만** 팝업이 뜬다(실패 파일 목록은 팝업 없이는 알 수 없는 정보라서).
- `[폴더 열기]` 버튼(탐색기에서 결과 파일 선택 상태로 열기)은 **사전 설정 창(체크박스)이 없는 흐름의 실패 팝업에서만** 노출: 우클릭 단일파일 병합, 우클릭 일괄변환. `MergeWindow`·`HelperWindow`를 거치는 흐름은 그 창의 "완료 후 폴더 열기" 체크박스(기본 off)가 이미 결정하므로 팝업엔 버튼을 두지 않는다.
- `[닫기]` 버튼은 제거 — 우상단 X로 닫기.
- 결과 파일이 실제로 존재할 때만 열기 대상. `Enter`/`ESC` 모두 닫기.
- **우클릭 다중파일 병합(`MergeWindow`)은 성공 시 팝업이 없어지면서 그 뒤의 자동 창닫기 로직이 곧바로 실행돼, 창뿐 아니라 프로그램 프로세스 자체가 클릭 없이 완전히 종료된다**(실측 확인, 2026-08-03). `HelperWindow`(도우미 GUI)는 여러 배치를 연속 처리하는 용도로 의도적으로 계속 열려있어 이 자동종료 대상이 아니다.

---

## install.py 동작

```python
# winreg 사용, HKCU → 관리자 권한 불필요
# PyInstaller frozen 환경: sys.executable 로 exe 경로 자동 감지
# 개발 모드: pythonw.exe 우선 사용 (콘솔 창 미표시)
# 이미 등록된 경우: 조용히 덮어쓰기
```

등록 키 경로:
```
HKCU\Software\Classes\SystemFileAssociations\.{jpg,jpeg,png,bmp}\shell\pdf_maker_convert\
HKCU\Software\Classes\*\shell\pdf_maker_merge\
```

---

## 빌드

```bat
pip install PyMuPDF pywin32 pyinstaller
pyinstaller --onedir --windowed --name pdf_maker ^
  --hidden-import win32com --hidden-import win32com.client ^
  --hidden-import pythoncom --hidden-import pywintypes ^
  --add-data "src/FilePathCheckerModule.dll;." ^
  src/main.py
```
※ `pywin32`는 HWP→PDF 변환(한컴 COM)용. PyInstaller가 win32com을 누락하지 않도록 hidden-import 지정.
※ **`--onedir`** (이전 `--onefile`에서 변경): onefile은 매 실행마다 수백 MB를 압축해제해
  시작이 느리고, 다중선택 시 N개가 동시에 해제돼 특히 지연. onedir은 압축해제가 없어 시작이
  빠름. 배포는 `dist\pdf_maker` **폴더째** zip. 등록 exe = `dist\pdf_maker\pdf_maker.exe`.
※ **`--add-data`**: 한글 보안모듈 `FilePathCheckerModule.dll`(217KB, `src/`)을 번들 →
  [메뉴 등록] 시 자동 레지스트리 등록으로 '모두 허용' 팝업 억제. **대상 PC에 파이썬 불필요.**

### 사용자 설치 과정 (배포받는 사람)
1. `dist\pdf_maker` **폴더 전체**를 zip으로 받아 원하는 위치에 압축 해제 (exe만 떼면 실행 불가)
2. 폴더 안 `pdf_maker.exe` 더블클릭 → 도우미 GUI → **[메뉴 등록]** (우클릭 메뉴 + 보안모듈 자동 등록)
3. 탐색기 우클릭에서 즉시 사용 가능
4. HWP 기능은 그 PC에 한글(한컴오피스) 설치 시에만 동작 (없으면 이미지/PDF만, HWP는 스킵)

⚠ **압축 해제 위치는 로컬 디스크로 — 클라우드 동기화 드라이브(구글 드라이브 등) 금지.** `[메뉴 등록]`은 그 순간의 exe 경로를 레지스트리에 그대로 박는데, 경로가 클라우드 동기화 가상 드라이브면 파일시스템 필터 드라이버 오버헤드로 우클릭 실행 시작이 **로컬 디스크 대비 8배 이상 느려진다**(2026-08-03 실측). 개발 PC 기준 배포 위치는 `C:\Users\minwoo\Dev\PDF_Maker_260406`.

---

## 엣지 케이스 정리

| 상황 | 처리 |
|------|------|
| 파일 없는 폴더 경로 | 세션 수집 시 필터링 |
| 한글 경로 | PyMuPDF/Tkinter 모두 UTF-8 기본 지원, 통합 테스트 우선 검증 |
| lock 파일 15초 초과 | 스테일 처리 (크래시 대비) |
| 출력 파일명 충돌 | suffix 숫자 증가 (`_1`, `_2`...) |
| exe 이동 후 메뉴 | 작동 안 됨 → 등록 완료 메시지에 경고 포함 |
| 병합 목록 빈 상태 | [병합 시작] 비활성화 |
| 빈 파일명 입력란 | 포커스 이탈 시 `merged.pdf` 자동 복원 |
| 중복 파일 | 허용 (중복 페이지 생성) |
| 취소 후 부분 파일 | 자동 삭제 |
| HWP인데 한컴 미설치 | 해당 파일만 스킵(errors), 나머지 병합 진행 |
| HWP 변환 임시 PDF | 병합 후 `finally`에서 정리 (TEMP/`pdfmaker_hwp_*.pdf`) |
