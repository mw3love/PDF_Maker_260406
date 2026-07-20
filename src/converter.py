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


def _batch_hwp_to_pdf(
    hwp_paths: List[Path],
) -> Tuple[Dict[Path, Path], Dict[Path, Exception], List[Path]]:
    """한컴오피스 COM 1세션으로 HWP들을 임시 PDF로 일괄 변환.

    한컴 미설치·pywin32 미설치·개별 변환 실패는 예외로 잡아 errors에 담고
    나머지는 계속 진행한다(merge_files가 실패 파일만 스킵하도록).

    반환: (path→임시PDF 맵, path→예외 맵, 정리해야 할 임시PDF 목록)
    """
    pdf_map: Dict[Path, Path] = {}
    errors: Dict[Path, Exception] = {}
    temp_pdfs: List[Path] = []

    try:
        import pythoncom
        import win32com.client
    except ImportError:
        err = RuntimeError("pywin32 미설치 — HWP 변환 불가")
        for p in hwp_paths:
            errors[p] = err
        return pdf_map, errors, temp_pdfs

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
            err = RuntimeError("한컴오피스(한글) 미설치 또는 COM 사용 불가")
            for p in hwp_paths:
                errors[p] = err
            return pdf_map, errors, temp_pdfs

        tmp_dir = Path(tempfile.gettempdir())
        for p in hwp_paths:
            try:
                out = tmp_dir / f"pdfmaker_hwp_{os.getpid()}_{len(temp_pdfs)}.pdf"
                out.unlink(missing_ok=True)
                hwp.Open(str(p), "", "")               # 인자 3개 필수
                hwp.SaveAs(str(out), "PDF", "")
                if not out.exists():
                    raise RuntimeError("PDF 저장 실패 (SaveAs)")
                pdf_map[p] = out
                temp_pdfs.append(out)
                try:
                    hwp.Clear(1)  # 현재 문서 닫기(변경 무시)
                except Exception:
                    pass
            except Exception as e:
                errors[p] = e
    finally:
        if hwp is not None:
            try:
                hwp.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

    return pdf_map, errors, temp_pdfs


def hwp_to_pdf(hwp_path: Path, output_path: Optional[Path] = None) -> Path:
    """단일 HWP를 PDF로 변환. output_path 미지정 시 원본 옆 .pdf(충돌 시 _N)."""
    pdf_map, errors, _ = _batch_hwp_to_pdf([hwp_path])
    if hwp_path in errors:
        raise errors[hwp_path]
    temp = pdf_map[hwp_path]
    final = output_path or resolve_output_path(hwp_path.with_suffix(".pdf"))
    try:
        shutil.move(str(temp), str(final))
    except Exception:
        shutil.copy2(str(temp), str(final))
        temp.unlink(missing_ok=True)
    return final


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
        hwp_pdf_map, hwp_errors, temp_pdfs = _batch_hwp_to_pdf(hwp_paths)

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
