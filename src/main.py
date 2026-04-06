import argparse
import shutil
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import List, Optional

SUPPORTED_IMG = {".jpg", ".jpeg", ".png", ".bmp"}


# ---------------------------------------------------------------------------
# 세션 수집기
# ---------------------------------------------------------------------------

def collect_session(mode: str, file_path: str) -> Optional[List[Path]]:
    """
    파일 경로를 session.txt에 원자적으로 기록하고,
    lock 파일 선점에 성공한 마스터 프로세스만 수집된 경로 목록을 반환.
    슬레이브(비마스터)는 None 반환.
    """
    tmp = Path(tempfile.gettempdir())
    session_file = tmp / f"pdf_maker_{mode}_session.txt"
    lock_file = tmp / f"pdf_maker_{mode}_lock.txt"

    # session.txt에 현재 파일 경로 기록
    try:
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(file_path + "\n")
    except Exception:
        pass

    # 스테일 lock 처리 (5초 초과 = 이전 크래시)
    if lock_file.exists():
        try:
            age = time.time() - lock_file.stat().st_mtime
            if age > 5:
                lock_file.unlink(missing_ok=True)
        except Exception:
            pass

    # 이미 lock이 존재하면 슬레이브 → 조용히 종료
    if lock_file.exists():
        return None

    # lock 생성(마스터 선출)
    try:
        lock_file.touch()
    except Exception:
        return None

    # 다른 프로세스들이 session.txt에 기록할 시간 대기
    time.sleep(0.4)

    # session.txt 읽기
    try:
        paths_text = session_file.read_text(encoding="utf-8")
        paths = [Path(line.strip()) for line in paths_text.splitlines() if line.strip()]
    except Exception:
        paths = []

    # lock/session 정리
    try:
        lock_file.unlink(missing_ok=True)
        session_file.unlink(missing_ok=True)
    except Exception:
        pass

    return paths


# ---------------------------------------------------------------------------
# convert 모드
# ---------------------------------------------------------------------------

def cmd_convert(file_path: str):
    paths = collect_session("convert", file_path)
    if paths is None:
        return

    from converter import CancelledError, image_to_pdf
    import gui

    img_paths = [p for p in paths if p.suffix.lower() in SUPPORTED_IMG]

    root = tk.Tk()
    root.withdraw()

    if not img_paths:
        messagebox.showerror("오류", "지원되는 이미지 파일이 없습니다.")
        root.destroy()
        return

    total = len(img_paths)
    results: List[Path] = []

    popup = gui.ProgressPopup(root, title="변환 중...")

    def worker(progress_cb, cancel_flag):
        for i, p in enumerate(img_paths):
            if cancel_flag.is_set():
                raise CancelledError()
            out = image_to_pdf(p)
            results.append(out)
            progress_cb(i + 1, total, p.name)
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
    paths = collect_session("merge", file_path)
    if paths is None:
        return

    from converter import CancelledError, image_to_pdf, resolve_output_path
    import gui

    if len(paths) == 1:
        # 단일 파일 예외처리: GUI 없이 즉시 처리
        p = paths[0]
        ext = p.suffix.lower()

        root = tk.Tk()
        root.withdraw()

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

    # 2개 이상 → MergeWindow (parent=None 이므로 자체 Tk root 생성)
    sorted_paths = sorted(paths, key=lambda p: p.name)
    win = gui.MergeWindow(None, sorted_paths)
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
        from install import install
        install()
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("메뉴 등록", "등록 완료 (※ exe 이동 시 재등록 필요)")
        root.destroy()

    elif args.command == "uninstall":
        from install import uninstall
        uninstall()
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("메뉴 제거", "메뉴가 제거되었습니다.")
        root.destroy()

    else:
        # 인수 없음 → 도우미 GUI
        from gui import HelperWindow
        win = HelperWindow()
        win.mainloop()


if __name__ == "__main__":
    main()
