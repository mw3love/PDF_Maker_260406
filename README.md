# PDF Maker

Windows 탐색기 우클릭 메뉴에서 이미지→PDF 변환 및 PDF 병합을 수행하는 유틸리티.

**관리자 권한 불필요** | Python 없는 환경에서도 동작하는 단일 exe 배포

---

## 주요 기능

### 이미지 → PDF 변환
- 탐색기에서 이미지 파일 선택 → 우클릭 → **"이미지 → PDF 변환"**
- 다중 선택 시 각 파일을 개별 PDF로 일괄 변환
- 지원 형식: `.jpg`, `.jpeg`, `.png`, `.bmp`
- 출력: 원본 파일과 같은 폴더, 파일명 충돌 시 `_1`, `_2` 자동 suffix

### PDF 병합
- 파일 선택(이미지·PDF 혼합 가능) → 우클릭 → **"PDF로 병합"**
- 병합 GUI에서 순서 조정(▲▼), 파일 추가/제거 후 실행
- 파일 1개 선택 시 GUI 없이 즉시 처리
- 출력: `merged.pdf` (충돌 시 `merged_1.pdf`, `merged_2.pdf`...)

### 도우미 GUI (더블클릭)
- 개별 변환 / 병합 모드 선택
- 메뉴 등록·제거 버튼 내장 (별도 설치 과정 불필요)

### 기타
- 페이지 크기 = 이미지 원본 해상도 (여백·메타데이터 없음)
- 진행바 팝업 (항상 화면 위, 취소 가능, 부분 생성 파일 자동 삭제)
- 한글 경로 지원

---

## 설치 및 사용

1. [Releases](../../releases)에서 `pdf_maker.exe` 다운로드
2. 원하는 폴더에 저장 후 **더블클릭**
3. 도우미 GUI에서 **[메뉴 등록]** 클릭
4. 탐색기 우클릭 메뉴에서 즉시 사용

> exe를 다른 폴더로 이동하면 메뉴 등록을 다시 해야 합니다.

---

## 개발 환경 실행

```bat
pip install PyMuPDF pyinstaller

python src/main.py                     # 도우미 GUI
python src/main.py convert "파일경로"  # 이미지→PDF 변환
python src/main.py merge "파일경로"    # 병합 GUI
python src/main.py install             # 레지스트리 등록
python src/main.py uninstall          # 레지스트리 삭제
```

### exe 빌드

```bat
build.bat
```

---

## 기술 스택

| 항목 | 선택 |
|------|------|
| 언어 | Python |
| PDF 처리 | PyMuPDF (fitz) |
| GUI | Tkinter (내장) |
| 배포 | PyInstaller 단일 exe |
| 레지스트리 | HKCU (관리자 권한 불필요) |

---

## 업데이트 기록

| 날짜 | 내용 |
|------|------|
| 2026-04-06 | `.gitignore` 추가, GitHub 초기 배포 |
| 2026-04-06 | CLAUDE.md·PRD 현행화, 문서 업데이트 규칙 정립 |
| 2026-04-06 | 세션 수집기 개선 (adaptive wait), GUI 안정성 향상 (포커스·깜빡임 처리) |
| 2026-04-06 | 통합 테스트 완료 및 버그 수정 |
| 2026-04-06 | main.py CLI 진입점·세션 수집기(마스터 선출 로직) 구현 |
| 2026-04-06 | install.py 레지스트리 등록/해제 구현 |
| 2026-04-06 | 프로젝트 기반 구조 및 converter.py 구현 |
