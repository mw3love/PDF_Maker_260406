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
  1. TEMP/pdf_maker_{mode}_session.txt 에 파일경로 append (원자적)
  2. TEMP/pdf_maker_{mode}_lock.txt 없으면 → lock 생성 (마스터)
       → adaptive wait → session.txt 읽기 → lock/session 삭제 → 작업 실행
  3. lock 있으면 → 조용히 종료

Adaptive wait: 새 파일이 감지될 때마다 deadline을 600ms 연장 (Explorer 순차 실행 대응)
스테일 처리: lock 파일 생성 후 15초 초과 시 무효화 (이전 크래시 대비)
```

마스터 선출 직후 "파일 수집 중..." 인디케이터 팝업 표시 (indeterminate 진행바).

**convert 모드**: 마스터가 수집된 모든 파일 일괄 변환 → 통합 완료 팝업 1개
**merge 모드**: 마스터가 병합 GUI 실행

---

## 지원 형식 및 출력 규칙

- **입력**: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.pdf`
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
- PDF → `merged.pdf`로 복사 (GUI 없이 바로)

---

## converter.py 설계

```python
import fitz  # PyMuPDF

def image_to_pdf(img_path: Path) -> Path:
    doc = fitz.open()
    img_doc = fitz.open(str(img_path))   # 이미지를 1페이지 PDF로 열기
    rect = img_doc[0].rect
    page = doc.new_page(width=rect.width, height=rect.height)
    page.show_pdf_page(page.rect, img_doc, 0)
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
pip install PyMuPDF pyinstaller
pyinstaller --onefile --windowed --name pdf_maker src/main.py
```

### 사용자 설치 과정
1. `pdf_maker.exe` 원하는 폴더에 저장
2. 더블클릭 → 도우미 GUI → [메뉴 등록]
3. 탐색기 우클릭에서 즉시 사용 가능

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
