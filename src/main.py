import argparse
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional

from converter import SUPPORTED_IMG


# ---------------------------------------------------------------------------
# 세션 수집기 (2단계)
# ---------------------------------------------------------------------------

def _try_master(mode: str, file_path: str) -> bool:
    """session.txt에 경로 기록 후 lock 선점 시 True, 슬레이브면 False."""
    tmp = Path(tempfile.gettempdir())
    session_file = tmp / f"pdf_maker_{mode}_session.txt"
    lock_file = tmp / f"pdf_maker_{mode}_lock.txt"

    try:
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(file_path + "\n")
    except Exception:
        pass

    if lock_file.exists():
        try:
            if time.time() - lock_file.stat().st_mtime > 15:
                lock_file.unlink(missing_ok=True)
        except Exception:
            pass

    if lock_file.exists():
        return False

    try:
        lock_file.touch()
        return True
    except Exception:
        return False


def _collect_master(mode: str) -> List[Path]:
    """마스터로서 adaptive wait 후 수집된 경로 목록 반환, lock/session 정리."""
    tmp = Path(tempfile.gettempdir())
    session_file = tmp / f"pdf_maker_{mode}_session.txt"
    lock_file = tmp / f"pdf_maker_{mode}_lock.txt"

    # 새 파일 도착마다 deadline 600ms 연장 (Explorer 순차 실행 대응)
    text = ""
    deadline = time.time() + 0.6
    prev_count = 0
    while time.time() < deadline:
        time.sleep(0.05)
        try:
            text = session_file.read_text(encoding="utf-8")
            count = sum(1 for l in text.splitlines() if l.strip())
            if count > prev_count:
                prev_count = count
                deadline = time.time() + 0.6
        except Exception:
            pass

    paths = [Path(l.strip()) for l in text.splitlines() if l.strip()]

    try:
        lock_file.unlink(missing_ok=True)
        session_file.unlink(missing_ok=True)
    except Exception:
        pass

    return paths


# ---------------------------------------------------------------------------
# 수집 인디케이터 (마스터 선출 직후 표시)
# ---------------------------------------------------------------------------

def _run_with_indicator(mode: str, root, label: str) -> List[Path]:
    """백그라운드 스레드에서 _collect_master 실행하며 인디케이터 표시. 수집 완료 후 경로 반환."""
    import tkinter as tk
    from tkinter import ttk

    ind = tk.Toplevel(root)
    ind.title("PDF 변환 도구")
    ind.resizable(False, False)
    ind.attributes("-topmost", True)
    ind.protocol("WM_DELETE_WINDOW", lambda: None)
    ind.overrideredirect(False)

    tk.Label(ind, text=label, padx=24, pady=12).pack()
    pb = ttk.Progressbar(ind, mode="indeterminate", length=200)
    pb.pack(padx=24, pady=(0, 16))
    pb.start(50)

    ind.update_idletasks()
    w, h = ind.winfo_reqwidth(), ind.winfo_reqheight()
    x = (ind.winfo_screenwidth() - w) // 2
    y = (ind.winfo_screenheight() - h) // 2
    ind.geometry(f"+{x}+{y}")
    ind.update()

    collected: List[Path] = []

    def collect():
        nonlocal collected
        collected = _collect_master(mode)

    t = threading.Thread(target=collect, daemon=True)
    t.start()
    while t.is_alive():
        root.update()
        time.sleep(0.02)

    ind.destroy()
    return collected


# ---------------------------------------------------------------------------
# convert 모드
# ---------------------------------------------------------------------------

def cmd_convert(file_path: str):
    if not _try_master("convert", file_path):
        return

    import tkinter as tk
    from tkinter import messagebox
    from converter import CancelledError, image_to_pdf
    import gui

    root = tk.Tk()
    root.withdraw()

    paths = _run_with_indicator("convert", root, "파일 수집 중...")
    img_paths = [p for p in paths if p.suffix.lower() in SUPPORTED_IMG]

    if not img_paths:
        messagebox.showerror("오류", "지원되는 이미지 파일이 없습니다.")
        root.destroy()
        return

    results: List[Path] = []

    popup = gui.ProgressPopup(root, title="변환 중...")

    def worker(progress_cb, cancel_flag):
        for i, p in enumerate(img_paths):
            if cancel_flag.is_set():
                raise CancelledError()
            out = image_to_pdf(p)
            results.append(out)
            progress_cb(i + 1, len(img_paths), p.name)
        return results

    def on_done(status, data):
        if status == "done":
            messagebox.showinfo("변환 완료", f"{len(results)}개 파일이 PDF로 변환되었습니다.")
        elif status == "error":
            messagebox.showerror("오류", str(data))
        root.destroy()

    popup.run(worker, on_done)
    root.mainloop()


# ---------------------------------------------------------------------------
# merge 모드
# ---------------------------------------------------------------------------

def cmd_merge(file_path: str):
    if not _try_master("merge", file_path):
        return

    import tkinter as tk
    from tkinter import messagebox
    from converter import CancelledError, image_to_pdf, resolve_output_path
    import gui

    root = tk.Tk()
    root.withdraw()

    paths = _run_with_indicator("merge", root, "파일 수집 중...")

    if len(paths) == 1:
        p = paths[0]
        ext = p.suffix.lower()
        try:
            if ext in SUPPORTED_IMG:
                out = image_to_pdf(p)
                messagebox.showinfo("변환 완료", f"{out.name} 생성 완료\n{out}")
            elif ext == ".pdf":
                output_path = resolve_output_path(p.parent / "merged.pdf")
                shutil.copy2(str(p), str(output_path))
                messagebox.showinfo("완료", f"{output_path.name} 생성 완료\n{output_path}")
            else:
                messagebox.showerror("오류", f"지원하지 않는 파일 형식: {p.suffix}")
        except Exception as exc:
            messagebox.showerror("오류", str(exc))
        root.destroy()
        return

    win = gui.MergeWindow(root, paths)
    win.mainloop()


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(prog="pdf_maker")
    sub = parser.add_subparsers(dest="command")

    sp_convert = sub.add_parser("convert")
    sp_convert.add_argument("file")

    sp_merge = sub.add_parser("merge")
    sp_merge.add_argument("file")

    sub.add_parser("install")
    sub.add_parser("uninstall")

    args = parser.parse_args()

    if args.command == "convert":
        cmd_convert(args.file)

    elif args.command == "merge":
        cmd_merge(args.file)

    elif args.command == "install":
        import tkinter as tk
        from tkinter import messagebox
        from install import install
        install()
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("메뉴 등록", "등록 완료 (※ exe 이동 시 재등록 필요)")
        root.destroy()

    elif args.command == "uninstall":
        import tkinter as tk
        from tkinter import messagebox
        from install import uninstall
        uninstall()
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("메뉴 제거", "메뉴가 제거되었습니다.")
        root.destroy()

    else:
        from gui import HelperWindow
        win = HelperWindow()
        win.mainloop()


if __name__ == "__main__":
    main()
