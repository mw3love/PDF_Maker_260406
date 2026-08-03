import argparse
import errno
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional

# 주의: converter는 fitz(무거움, ~0.6s)를 import하므로 모듈 최상단에서 불러오지 않는다.
# 슬레이브 프로세스는 _try_master 후 즉시 종료하고, 마스터는 인디케이터 창을 먼저
# 띄운 뒤 converter를 로드한다 (체감 반응성 + 슬레이브 startup 단축).


# ---------------------------------------------------------------------------
# 세션 수집기 (2단계)
# ---------------------------------------------------------------------------

def _session_dir(mode: str) -> Path:
    return Path(tempfile.gettempdir()) / f"pdf_maker_{mode}_session"


def _try_master(mode: str, file_path: str) -> bool:
    """각 프로세스가 자기 엔트리 파일에 경로 기록 후 lock 선점 시 True, 슬레이브면 False.

    공유 session.txt에 동시 append하면 프로세스 간 경쟁으로 줄이 유실/뒤섞이므로
    (Windows append는 프로세스 간 원자적이지 않음), 프로세스마다 별도 파일에 1회 write한다.
    """
    session_dir = _session_dir(mode)
    lock_file = Path(tempfile.gettempdir()) / f"pdf_maker_{mode}_lock.txt"

    try:
        session_dir.mkdir(exist_ok=True)
        entry = session_dir / f"{os.getpid()}_{time.time_ns()}.txt"
        entry.write_text(file_path + "\n", encoding="utf-8")  # 단일 원자적 write
    except Exception:
        pass

    # 스테일 lock 처리 (이전 크래시 대비, 15초 초과)
    try:
        if lock_file.stat().st_mtime < time.time() - 15:
            lock_file.unlink(missing_ok=True)
    except (FileNotFoundError, OSError):
        pass

    # O_CREAT | O_EXCL 으로 원자적 lock 파일 생성 (TOCTOU 방지)
    try:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except OSError as e:
        if e.errno == errno.EEXIST:
            return False
        return False


def _collect_master(mode: str) -> List[Path]:
    """마스터로서 adaptive wait 후 엔트리 파일들을 수집해 경로 목록 반환, 정리."""
    session_dir = _session_dir(mode)
    lock_file = Path(tempfile.gettempdir()) / f"pdf_maker_{mode}_lock.txt"

    def read_entries():
        """(파일, 경로) 목록. 30초 넘은 엔트리는 이전 크래시 잔재로 무시."""
        out = []
        now = time.time()
        try:
            for f in session_dir.glob("*.txt"):
                try:
                    if now - f.stat().st_mtime > 30:
                        continue
                    for line in f.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            out.append((f, line.strip()))
                except Exception:
                    pass
        except Exception:
            pass
        return out

    # 새 엔트리 도착마다 deadline 600ms 연장 (Explorer 순차 실행 대응)
    deadline = time.time() + 0.6
    prev_count = 0
    entries = []
    while time.time() < deadline:
        time.sleep(0.05)
        entries = read_entries()
        if len(entries) > prev_count:
            prev_count = len(entries)
            deadline = time.time() + 0.6

    paths = [Path(p) for _, p in entries]

    # 수집한 엔트리 + lock 정리, 오래된 잔재도 청소
    try:
        for f, _ in entries:
            f.unlink(missing_ok=True)
        lock_file.unlink(missing_ok=True)
        now = time.time()
        for f in session_dir.glob("*.txt"):
            try:
                if now - f.stat().st_mtime > 30:
                    f.unlink(missing_ok=True)
            except Exception:
                pass
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

    # 무거운 fitz 로드 전에 인디케이터 창부터 띄운다 (클릭 즉시 "실행 중" 피드백)
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    paths = _run_with_indicator("convert", root, "파일 수집 중...")

    # 창이 뜬 뒤 무거운 모듈 로드
    from tkinter import messagebox
    from converter import SUPPORTED_IMG, SUPPORTED_HWP, CancelledError, image_to_pdf, hwp_batch_to_pdf
    import gui

    img_paths = [p for p in paths if p.suffix.lower() in SUPPORTED_IMG and p.exists()]
    hwp_paths = [p for p in paths if p.suffix.lower() in SUPPORTED_HWP and p.exists()]

    if not img_paths and not hwp_paths:
        messagebox.showerror("오류", "지원되는 파일이 없습니다.")
        root.destroy()
        return

    results: List[Path] = []
    conv_errors: List = []

    popup = gui.ProgressPopup(root, title="변환 중...")

    def worker(progress_cb, cancel_flag):
        total = len(img_paths) + len(hwp_paths)
        done = 0
        for p in img_paths:
            if cancel_flag.is_set():
                raise CancelledError()
            out = image_to_pdf(p)
            results.append(out)
            done += 1
            progress_cb(done, total, p.name)
        if hwp_paths:
            # 한컴 1세션 일괄 변환 (취소는 세션 단위 — 중간 취소 불가)
            base = len(img_paths)
            hres, herr = hwp_batch_to_pdf(
                hwp_paths,
                lambda i, n, name: progress_cb(base + i, total, name),
            )
            results.extend(hres)
            conv_errors.extend(herr)
        return results

    def on_done(status, data):
        if status == "done":
            msg = f"{len(results)}개 파일이 PDF로 변환되었습니다."
            if conv_errors:
                fails = "\n".join(f"- {p.name}: {e}" for p, e in conv_errors)
                msg += f"\n\n실패 {len(conv_errors)}건:\n{fails}"
            gui.show_result_popup(root, "변환 완료", msg, results, show_popup=bool(conv_errors))
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

    # 무거운 fitz 로드 전에 인디케이터 창부터 띄운다 (클릭 즉시 "실행 중" 피드백)
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    paths = [p for p in _run_with_indicator("merge", root, "파일 수집 중...") if p.exists()]

    # 창이 뜬 뒤 무거운 모듈 로드
    from tkinter import messagebox
    from converter import SUPPORTED_IMG, SUPPORTED_HWP, CancelledError, image_to_pdf, resolve_output_path
    import gui

    if not paths:
        messagebox.showerror("오류", "처리할 파일이 없습니다.")
        root.destroy()
        return

    if len(paths) == 1:
        p = paths[0]
        ext = p.suffix.lower()
        try:
            if ext in SUPPORTED_IMG:
                out = image_to_pdf(p)
                gui.show_result_popup(root, "변환 완료", f"{out.name} 생성 완료\n{out}", [out], show_popup=False)
            elif ext in SUPPORTED_HWP:
                from converter import hwp_to_pdf
                out = hwp_to_pdf(p)
                gui.show_result_popup(root, "변환 완료", f"{out.name} 생성 완료\n{out}", [out], show_popup=False)
            elif ext == ".pdf":
                output_path = resolve_output_path(p.parent / "merged.pdf")
                shutil.copy2(str(p), str(output_path))
                gui.show_result_popup(root, "완료", f"{output_path.name} 생성 완료\n{output_path}", [output_path], show_popup=False)
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
