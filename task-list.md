# PDF Maker Task List
> 작성일: 2026-04-06

## 개요
Windows 탐색기 우클릭 컨텍스트 메뉴에서 이미지→PDF 변환 및 다파일 PDF 병합을 완결하는 유틸리티.
Python + PyMuPDF + Tkinter로 구현하며, PyInstaller 단일 exe로 배포한다.
관리자 권한 없이 HKCU 레지스트리를 사용해 컨텍스트 메뉴를 등록/해제한다.

---

## Phase 현황

| Phase | 제목 | 상태 |
|-------|------|------|
| 1 | 프로젝트 기반 + converter.py | [ ] 미시작 |
| 2 | install.py (레지스트리 등록/해제) | [ ] 미시작 |
| 3 | gui.py (GUI 3종) | [x] 완료 |
| 4 | main.py (CLI 진입점 + 세션 수집기) | [x] 완료 |
| 5 | 통합 검증 | [ ] 미시작 |

---

## Phase 1 — 프로젝트 기반 + converter.py
> REF: PRD.md#프로젝트-구조, PRD.md#converterpY-설계, PRD.md#지원-형식-및-출력-규칙

- [ ] **프로젝트 뼈대 생성**
  - **수행 지침**: 프로젝트 루트에 `src/` 폴더 생성. `requirements.txt`(내용: `PyMuPDF>=1.23.0`) 및 `build.bat`(내용: `pyinstaller --onefile --windowed --name pdf_maker src/main.py`) 파일 생성.
  - **완료 기준**: Done When — `src/`, `requirements.txt`, `build.bat` 파일이 존재한다.

- [ ] **`resolve_output_path()` 구현**
  - **수행 지침**: `src/converter.py`에 `resolve_output_path(path: Path) -> Path` 함수 구현. 대상 경로가 존재하지 않으면 그대로 반환. 존재하면 stem에 `_1`, `_2`... suffix를 붙여 비어있는 경로를 반환.
  - **완료 기준**: Done When — `merged.pdf` 충돌 시 `merged_1.pdf`, `merged_2.pdf` 순서로 반환한다.

- [ ] **`image_to_pdf()` 구현**
  - **수행 지침**: `fitz.open()` 빈 문서 생성 → `fitz.open(str(img_path))`로 이미지 열기 → 원본 rect 크기 페이지 생성 → `page.show_pdf_page()` → `resolve_output_path(img_path.with_suffix(".pdf"))`로 출력 경로 결정 → `doc.save()`. 반환값: `Path`.
  - **완료 기준**: Done When — JPG/PNG/BMP 이미지 입력 시 여백 없는 PDF가 동일 폴더에 생성된다.

- [ ] **`merge_files()` 구현**
  - **수행 지침**: `src/converter.py`에 `merge_files(file_paths: List[Path], output_path: Path, progress_cb=None, cancel_flag=None) -> List[tuple]` 구현. `fitz.open()` 결과 문서 생성 → 각 파일 `fitz.open()` → `result.insert_pdf()`. 파일별 예외는 `errors` 리스트에 누적(건너뜀). `cancel_flag.is_set()` 확인 시 `CancelledError` raise. `progress_cb(i+1, total, filename)` 호출. 반환: 오류 리스트(빈 리스트 = 전체 성공).
  - **완료 기준**: Done When — 이미지+PDF 혼합 파일 목록을 병합해 단일 PDF 생성, 취소 시 `CancelledError` 발생, 실패 파일은 건너뛰고 계속 진행한다.

- [ ] **커밋**: `feat: 프로젝트 기반 구조 및 converter.py 구현`

---

## Phase 2 — install.py (레지스트리 등록/해제)
> REF: PRD.md#우클릭-메뉴-등록, PRD.md#installpy-동작

- [ ] **`install()` 구현**
  - **수행 지침**: `src/install.py`에 `install()` 함수 구현. PyInstaller frozen 환경(`sys.frozen` 속성)이면 `sys.executable`, 아니면 `sys.argv[0]` 절대경로를 exe 경로로 사용. `winreg.CreateKey(winreg.HKEY_CURRENT_USER, ...)` + `winreg.SetValueEx()`로 다음 키 등록(이미 있으면 덮어쓰기):
    - `Software\Classes\SystemFileAssociations\.jpg\shell\pdf_maker_convert\` MUIVerb + command
    - `.jpeg`, `.png`, `.bmp` 동일 반복 (4개 확장자)
    - `Software\Classes\*\shell\pdf_maker_merge\` MUIVerb + command
    - 각 command 서브키에 `MultiSelectModel = Player`
  - **완료 기준**: Done When — `python src/main.py install` 실행 후 레지스트리 편집기에서 해당 키가 존재한다.

- [ ] **`uninstall()` 구현**
  - **수행 지침**: `install()`에서 등록한 키를 `winreg.DeleteKey()` 재귀 삭제. 키 미존재 시 무시.
  - **완료 기준**: Done When — `python src/main.py uninstall` 실행 후 레지스트리에서 해당 키가 사라진다.

- [ ] **커밋**: `feat: install.py 레지스트리 등록/해제 구현`

---

## Phase 3 — gui.py (GUI 3종)
> REF: PRD.md#GUI-명세

- [x] **툴팁 헬퍼 구현**
  - **수행 지침**: `src/gui.py`에 `Tooltip` 클래스 구현. Listbox 항목 마우스 오버 시 해당 항목의 전체 경로를 작은 toplevel 창으로 표시. `<Motion>` 이벤트로 항목 인덱스 계산.
  - **완료 기준**: Done When — 파일 목록에서 마우스를 올리면 전체 경로가 툴팁으로 표시된다.

- [x] **`ProgressPopup` 구현**
  - **수행 지침**: `Toplevel` + `topmost=True`, 모달 아님(`grab_set()` 미사용). 내부에 `ttk.Progressbar`, 파일 카운트 레이블, 현재 파일명 레이블, [취소] 버튼 배치. 작업은 `threading.Thread`로 실행, `queue.Queue`로 진행 상황 전달, `after(50, _poll)` 폴링으로 UI 갱신. 취소/X 클릭 시 `cancel_flag.set()` → `CancelledError` catch → 부분 생성 파일 `unlink()`. ESC 바인딩 = 취소. 완료 시 팝업 닫힘.
  - **완료 기준**: Done When — 변환/병합 중 진행바 갱신, 취소 시 파일 삭제, 완료 시 팝업 닫힘이 동작한다.

- [x] **`MergeWindow` 구현**
  - **수행 지침**: `Toplevel` 또는 `Tk` 창. 파일 목록 `Listbox` + 스크롤바, [▲][▼] 순서 변경, [+추가](`askopenfilenames` 다중 선택), [−제거], 파일명 입력란(포커스 아웃 시 빈값이면 `merged.pdf` 복원), [취소][병합 시작] 버튼(파일 0개면 비활성화). 초기 파일 순서: 파일명 오름차순. ESC=닫기, Enter=병합 시작. 파일명만 표시, 툴팁으로 전체 경로. [병합 시작] 클릭 시 `ProgressPopup` 실행 → 완료 후 성공/오류 `messagebox`.
  - **완료 기준**: Done When — 병합 GUI에서 파일 추가/순서 변경/병합이 동작하고 완료 메시지가 표시된다.

- [x] **`HelperWindow` 구현**
  - **수행 지침**: `Tk` 메인 창. 파일 목록 Listbox(MergeWindow와 동일 구성), 라디오버튼 "각 파일을 별도 PDF로 변환" / "하나의 PDF로 병합"(기본값), 파일명 입력란("개별 변환" 선택 시 비활성화), [메뉴 등록][메뉴 제거] 버튼, [취소][실행] 버튼. [실행] 클릭 시 창 유지하며 `ProgressPopup` 별도 실행. [메뉴 등록] 클릭 시 `install()` 호출 → "등록 완료 (※ exe 이동 시 재등록 필요)" messagebox. ESC=닫기, Enter=실행.
  - **완료 기준**: Done When — 도우미 GUI에서 개별 변환·병합 모드 전환, 실행 후 창 유지, 메뉴 등록이 동작한다.

- [x] **커밋**: `feat: gui.py 진행바·병합·도우미 GUI 구현`

---

## Phase 4 — main.py (CLI 진입점 + 세션 수집기)
> REF: PRD.md#exe-실행-모드, PRD.md#핵심-패턴-세션-수집기, PRD.md#단일-파일-예외-처리

- [x] **`collect_session()` 구현**
  - **수행 지침**: `src/main.py`에 `collect_session(mode: str, file_path: str) -> Optional[List[Path]]` 구현. `TEMP/pdf_maker_{mode}_session.txt`에 파일경로 원자적 append(파일 열기 → fcntl 대신 Windows에서는 `msvcrt.locking` 또는 짧은 retry 루프). `TEMP/pdf_maker_{mode}_lock.txt` 존재 확인 → 없으면 lock 생성(마스터) → 400ms `time.sleep(0.4)` → session.txt 읽기 → lock/session 삭제 → 파일 목록 반환. lock 있으면 `None` 반환. lock 파일 mtime이 5초 초과면 stale로 삭제 후 마스터 재선출.
  - **완료 기준**: Done When — 동일 mode로 동시에 여러 프로세스 실행 시 마스터 1개만 파일 목록을 받고 나머지는 종료된다.

- [x] **`cmd_convert()` 구현**
  - **수행 지침**: `collect_session("convert", file_path)` 호출 → `None`이면 조용히 종료. 마스터: 수집된 경로 중 지원 형식(`.jpg/.jpeg/.png/.bmp`) 필터링 → 0개면 오류 messagebox → `ProgressPopup`으로 `image_to_pdf()` 일괄 실행 → 완료 후 "N개 파일이 PDF로 변환되었습니다." messagebox.
  - **완료 기준**: Done When — 이미지 3개 선택 후 우클릭 변환 시 PDF 3개 생성, 완료 팝업 1개만 표시된다.

- [x] **`cmd_merge()` 구현**
  - **수행 지침**: `collect_session("merge", file_path)` 호출 → `None`이면 조용히 종료. 마스터: 수집 파일이 1개이면 단일 파일 예외처리(이미지→변환, PDF→`merged.pdf` 복사, GUI 없음). 2개 이상이면 `MergeWindow` 실행.
  - **완료 기준**: Done When — 파일 1개 merge: GUI 없이 즉시 처리. 파일 2개 이상 merge: MergeWindow 표시.

- [x] **argparse 진입점 구현**
  - **수행 지침**: `if __name__ == "__main__"`: argparse로 `{convert,merge,install,uninstall}` 서브커맨드 분기. 인수 없으면 `HelperWindow` 실행. Tkinter `mainloop()` 필요한 경우에만 호출.
  - **완료 기준**: Done When — `python src/main.py` 실행 시 도우미 GUI, `python src/main.py install` 실행 시 레지스트리 등록이 동작한다.

- [x] **커밋**: `feat: main.py CLI 진입점 및 세션 수집기 구현`

---

## Phase 5 — 통합 검증
> REF: PRD.md#엣지-케이스-정리

- [ ] **기본 동작 검증**
  - **수행 지침**: `python src/main.py`로 도우미 GUI 실행 → 파일 추가 → 개별 변환/병합 각각 테스트. `python src/main.py convert "경로"`, `python src/main.py merge "경로"` 직접 실행.
  - **완료 기준**: Done When — convert, merge, 도우미 GUI 세 경로 모두 오류 없이 PDF 생성.

- [ ] **세션 수집기 검증**
  - **수행 지침**: PowerShell에서 `Start-Process python -ArgumentList "src/main.py convert 파일1"` 등 동시 다중 실행. 완료 팝업이 1개만 떠야 함.
  - **완료 기준**: Done When — n개 동시 실행 시 팝업 1개, 결과 파일 n개 생성.

- [ ] **엣지 케이스 검증**
  - **수행 지침**: ① 한글 경로 파일 변환 ② 출력 파일명 충돌(`merged.pdf` 이미 있는 경우) ③ 빈 파일명 입력란 포커스 이탈 ④ 취소 후 부분 파일 삭제 확인 ⑤ 단일 파일 merge.
  - **완료 기준**: Done When — 모든 케이스가 PRD 엣지 케이스 표와 동일하게 처리된다.

- [ ] **레지스트리 등록 후 실제 우클릭 검증**
  - **수행 지침**: `python src/main.py install` → 탐색기에서 이미지 선택 → 우클릭 → "추가 옵션 표시" → "이미지 → PDF 변환" 클릭. 동일하게 merge도 확인.
  - **완료 기준**: Done When — 탐색기 우클릭에서 메뉴 항목이 보이고 기능이 동작한다.

- [ ] **커밋**: `test: 통합 검증 완료`
