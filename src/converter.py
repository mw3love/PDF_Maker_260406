from pathlib import Path
from typing import List, Optional, Callable, Tuple
import threading

import fitz  # PyMuPDF


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


def image_to_pdf(img_path: Path) -> Path:
    doc = fitz.open()
    img_doc = fitz.open(str(img_path))
    rect = img_doc[0].rect
    page = doc.new_page(width=rect.width, height=rect.height)
    page.show_pdf_page(page.rect, img_doc, 0)
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
    result = fitz.open()
    errors: List[Tuple[Path, Exception]] = []
    total = len(file_paths)

    for i, path in enumerate(file_paths):
        if cancel_flag and cancel_flag.is_set():
            result.close()
            raise CancelledError()
        try:
            src = fitz.open(str(path))
            result.insert_pdf(src)
            src.close()
        except Exception as e:
            errors.append((path, e))
        if progress_cb:
            progress_cb(i + 1, total, path.name)

    result.save(str(output_path))
    result.close()
    return errors
