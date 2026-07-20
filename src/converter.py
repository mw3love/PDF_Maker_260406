from pathlib import Path
from typing import List, Optional, Callable, Tuple, Dict
import os
import shutil
import tempfile
import threading

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
                # 보안 승인창 억제 (보안모듈 사전 등록 시 유효, 아니면 창이 뜰 수 있음)
                hwp.RegisterModule("FilePathCheckerModule", "FilePathCheckerModuleExample")
            except Exception:
                pass
        except Exception:
            e = RuntimeError("한컴오피스(한글) 미설치 또는 COM 사용 불가")
            return done, [(src, e) for src, _ in jobs]

        for i, (src, dst) in enumerate(jobs):
            try:
                dst.unlink(missing_ok=True)
                hwp.Open(str(src), "", "")             # 인자 3개 필수
                hwp.SaveAs(str(dst), "PDF", "")
                if not dst.exists():
                    raise RuntimeError("PDF 저장 실패 (SaveAs)")
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
    page = doc.new_page(width=rect.width, height=rect.height)
    page.insert_image(page.rect, stream=img_doc.tobytes())
    img_doc.close()
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
