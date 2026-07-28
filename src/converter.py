from pathlib import Path
from typing import List, Optional, Callable, Tuple, Dict
import os
import shutil
import tempfile
import threading
import time

import fitz  # PyMuPDF

SUPPORTED_IMG = {".jpg", ".jpeg", ".png", ".bmp"}
SUPPORTED_HWP = {".hwp", ".hwpx"}  # 한컴오피스 COM 필요 (merge 경로 한정)
SUPPORTED_ALL = SUPPORTED_IMG | {".pdf"} | SUPPORTED_HWP


class CancelledError(Exception):
    pass


def resolve_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def _wait_for_file(dst: Path, timeout: float = 30.0) -> bool:
    """비동기 프린터 스풀 대비: 파일이 생기고 크기가 안정될 때까지 대기."""
    deadline = time.time() + timeout
    last = -1
    stable = 0
    while time.time() < deadline:
        if dst.exists():
            size = dst.stat().st_size
            if size > 0 and size == last:
                stable += 1
                if stable >= 2:  # 연속 2회 동일 크기 → 쓰기 완료로 간주
                    return True
            else:
                stable = 0
            last = size
        time.sleep(0.3)
    return dst.exists() and dst.stat().st_size > 0


def _hwp_save_pdf(hwp, dst: Path) -> None:
    """열려 있는 현재 한글 문서를 dst(PDF)로 저장. 모아찍기(2-up) 방지.

    SaveAs(dst,"PDF","")는 한컴에 저장된 인쇄 '모아 찍기' 설정(PrintMethod=4=2쪽)을
    그대로 물려받아 A4 가로 2-up PDF로 나오는 문제가 있다(원본 6쪽 → 가로 3장).
    PrintToPDFEx 액션으로 PrintMethod=0(1쪽씩)을 명시해 원본 쪽 구성 그대로 저장한다.
    (한컴 개발자 포럼 forum.developer.hancom.com/t/saveas-pdf/1670 + 실조건검증 2026-07-22)
    Hancom PDF 프린터 경로가 실패하면 SaveAs로 폴백(2-up이라도 PDF는 생성).
    """
    dst.unlink(missing_ok=True)
    try:
        pset = hwp.HParameterSet.HPrint
        hwp.HAction.GetDefault("PrintToPDFEx", pset.HSet)
        pset.PrinterName = "Hancom PDF"
        pset.FileName = str(dst)
        pset.PrintMethod = 0   # 0=자동 인쇄(1쪽씩) / 4=2쪽 모아찍기
        pset.PrintToFile = 1
        # Execute가 True(액션 성공)이고 스풀 파일이 생기면 완료. 프린터 스풀은 비동기.
        if hwp.HAction.Execute("PrintToPDFEx", pset.HSet) and _wait_for_file(dst):
            return
    except Exception:
        pass
    # 폴백: PrintToPDFEx 실패(프린터 부재 등) → SaveAs (모아찍기 설정 물려받을 수 있음)
    dst.unlink(missing_ok=True)  # 스풀 잔여 파일 제거(이중쓰기 방지)
    hwp.SaveAs(str(dst), "PDF", "")
    if not dst.exists():
        raise RuntimeError("PDF 저장 실패 (PrintToPDFEx·SaveAs 모두 실패)")


def _hwp_session_convert(
    jobs: List[Tuple[Path, Path]],
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[List[Path], List[Tuple[Path, Exception]]]:
    """한컴오피스 COM 1세션으로 각 (src, dst) HWP를 dst(PDF)로 저장.

    한컴 미설치·pywin32 미설치·개별 변환 실패는 예외로 잡아 errors에 담고
    나머지는 계속 진행한다. dst가 이미 있으면 덮어씀(충돌 해소는 호출측 책임).

    반환: (성공한 dst 목록, [(src, 예외)] 실패 목록)
    """
    done: List[Path] = []
    errors: List[Tuple[Path, Exception]] = []
    if not jobs:
        return done, errors

    try:
        import pythoncom
        import win32com.client
    except ImportError:
        e = RuntimeError("pywin32 미설치 — HWP 변환 불가")
        return done, [(src, e) for src, _ in jobs]

    pythoncom.CoInitialize()
    hwp = None
    try:
        try:
            hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
            try:
                # 보안 승인창('모두 허용') 억제.
                # 1st="FilePathCheckDLL"(모듈 유형), 2nd="FilePathCheckerModule"(레지스트리
                # HKCU\Software\HNC\HwpAutomation\Modules 에 등록된 DLL 모듈 ID).
                # 그 레지스트리 값이 있어야만 효과 있음(pyhwpx setup_pc.py로 PC당 1회 등록).
                hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
            except Exception:
                pass
            try:
                # 확인만 있는 정보성 팝업 자동 확인(예: '상위 버전에서 작성한 문서').
                # 0x1 = OK-only 팝업에서 확인 자동클릭. (0xFFFFFF는 '자동설정 해제'이니 주의)
                hwp.SetMessageBoxMode(0x1)
            except Exception:
                pass
        except Exception:
            e = RuntimeError("한컴오피스(한글) 미설치 또는 COM 사용 불가")
            return done, [(src, e) for src, _ in jobs]

        for i, (src, dst) in enumerate(jobs):
            try:
                # 3번째 인자: versionwarning=상위버전 경고 끄기, suspendpassword=암호문서 프롬프트 억제
                hwp.Open(str(src), "", "versionwarning:False;suspendpassword:True")
                _hwp_save_pdf(hwp, dst)  # 모아찍기(2-up) 방지 — PrintToPDFEx PrintMethod=0
                done.append(dst)
                try:
                    hwp.Clear(1)  # 현재 문서 닫기(변경 무시)
                except Exception:
                    pass
            except Exception as e:
                errors.append((src, e))
            if progress_cb:
                progress_cb(i + 1, len(jobs), src.name)
    finally:
        if hwp is not None:
            try:
                hwp.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

    return done, errors


def hwp_to_pdf(hwp_path: Path, output_path: Optional[Path] = None) -> Path:
    """단일 HWP를 PDF로 변환. output_path 미지정 시 원본 옆 .pdf(충돌 시 _N)."""
    dst = output_path or resolve_output_path(hwp_path.with_suffix(".pdf"))
    done, errors = _hwp_session_convert([(hwp_path, dst)])
    if errors:
        raise errors[0][1]
    return dst


def hwp_batch_to_pdf(
    hwp_paths: List[Path],
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[List[Path], List[Tuple[Path, Exception]]]:
    """여러 HWP를 각각 원본 옆 PDF로 개별 변환(한컴 1세션). (성공 목록, 실패 목록) 반환."""
    jobs = [(p, resolve_output_path(p.with_suffix(".pdf"))) for p in hwp_paths]
    return _hwp_session_convert(jobs, progress_cb)


def image_to_pdf(img_path: Path) -> Path:
    doc = fitz.open()
    img_doc = fitz.open(str(img_path))
    rect = img_doc[0].rect
    img_doc.close()
    page = doc.new_page(width=rect.width, height=rect.height)
    # img_doc.tobytes()(Document.write, PDF 직렬화 전용)는 이미지 문서에 쓰면
    # PyMuPDF 1.27+에서 _as_pdf_document assert 실패로 매 변환마다 크래시한다.
    # insert_image(stream=...)는 원본 인코딩 바이트(JPEG/PNG 등) 그대로를 받으므로
    # 파일을 직접 읽어서 넘긴다.
    page.insert_image(page.rect, stream=img_path.read_bytes())
    output = resolve_output_path(img_path.with_suffix(".pdf"))
    doc.save(str(output))
    doc.close()
    return output


def merge_files(
    file_paths: List[Path],
    output_path: Path,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    cancel_flag: Optional[threading.Event] = None,
) -> List[Tuple[Path, Exception]]:
    # HWP는 한컴 COM 1세션으로 임시 PDF 일괄 변환 (승인창 1회, 성능)
    hwp_paths = [p for p in file_paths if p.suffix.lower() in SUPPORTED_HWP]
    hwp_pdf_map: Dict[Path, Path] = {}
    hwp_errors: Dict[Path, Exception] = {}
    temp_pdfs: List[Path] = []
    if hwp_paths:
        tmp_dir = Path(tempfile.gettempdir())
        jobs = [
            (p, tmp_dir / f"pdfmaker_hwp_{os.getpid()}_{idx}.pdf")
            for idx, p in enumerate(hwp_paths)
        ]
        for p, dst in jobs:
            hwp_pdf_map[p] = dst
        temp_pdfs = [dst for _, dst in jobs]
        _, errs = _hwp_session_convert(jobs)
        for src, e in errs:
            hwp_errors[src] = e

    result = fitz.open()
    errors: List[Tuple[Path, Exception]] = []
    total = len(file_paths)

    try:
        for i, path in enumerate(file_paths):
            if cancel_flag and cancel_flag.is_set():
                result.close()
                raise CancelledError()
            try:
                if path.suffix.lower() in SUPPORTED_HWP:
                    if path in hwp_errors:
                        raise hwp_errors[path]
                    src = fitz.open(str(hwp_pdf_map[path]))
                    try:
                        result.insert_pdf(src)
                    finally:
                        src.close()
                else:
                    src = fitz.open(str(path))
                    try:
                        if src.is_pdf:
                            result.insert_pdf(src)
                        else:
                            pdf_bytes = src.convert_to_pdf()
                            pdf_src = fitz.open("pdf", pdf_bytes)
                            result.insert_pdf(pdf_src)
                            pdf_src.close()
                    finally:
                        src.close()
            except Exception as e:
                errors.append((path, e))
            if progress_cb:
                progress_cb(i + 1, total, path.name)

        result.save(str(output_path))
        result.close()
    finally:
        for tp in temp_pdfs:
            try:
                tp.unlink(missing_ok=True)
            except Exception:
                pass
    return errors
