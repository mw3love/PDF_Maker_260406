import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from converter import CancelledError, image_to_pdf, merge_files, resolve_output_path
from install import install, uninstall

SUPPORTED_IMG = {".jpg", ".jpeg", ".png", ".bmp"}
SUPPORTED_ALL = SUPPORTED_IMG | {".pdf"}


# ---------------------------------------------------------------------------
# Tooltip
# ---------------------------------------------------------------------------

class Tooltip:
    """Listbox 항목 마우스 오버 시 전체 경로 툴팁."""

    def __init__(self, listbox: tk.Listbox, paths_getter):
        self._lb = listbox
        self._paths_getter = paths_getter  # () -> List[Path]
        self._win: Optional[tk.Toplevel] = None
        listbox.bind("<Motion>", self._on_motion)
        listbox.bind("<Leave>", self._hide)

    def _on_motion(self, event):
        idx = self._lb.nearest(event.y)
        paths = self._paths_getter()
        if idx < 0 or idx >= len(paths):
            self._hide()
            return
        text = str(paths[idx])
        if self._win is None:
            self._win = tk.Toplevel(self._lb)
            self._win.wm_overrideredirect(True)
            self._win.attributes("-topmost", True)
            self._label = tk.Label(
                self._win, text=text, background="#ffffe0",
                relief="solid", borderwidth=1, font=("", 9),
            )
            self._label.pack()
        else:
            self._label.config(text=text)
        x = self._lb.winfo_rootx() + event.x + 16
        y = self._lb.winfo_rooty() + event.y + 8
        self._win.wm_geometry(f"+{x}+{y}")

    def _hide(self, _event=None):
        if self._win:
            self._win.destroy()
            self._win = None


# ---------------------------------------------------------------------------
# ProgressPopup
# ---------------------------------------------------------------------------

class ProgressPopup:
    """
    작업 스레드 실행 + 진행바 팝업.

    사용법:
        popup = ProgressPopup(parent, title="변환 중...")
        popup.run(worker_func, on_done_callback)

    worker_func(progress_cb, cancel_flag) 시그니처.
    progress_cb(current, total, filename) 호출.
    """

    def __init__(self, parent: tk.Misc, title: str = "처리 중..."):
        self._parent = parent
        self._title = title
        self._cancel_flag = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._output_path: Optional[Path] = None  # 취소 시 삭제할 경로

        top = tk.Toplevel(parent)
        top.title(title)
        top.resizable(False, False)
        top.attributes("-topmost", True)
        top.protocol("WM_DELETE_WINDOW", self._cancel)
        top.bind("<Escape>", lambda _: self._cancel())
        self._top = top

        top.columnconfigure(0, weight=1)
        self._pb = ttk.Progressbar(top, length=300, mode="determinate")
        self._pb.grid(row=0, column=0, padx=20, pady=(20, 6), sticky="ew")

        self._lbl_count = tk.Label(top, text="0 / 0 파일")
        self._lbl_count.grid(row=1, column=0, padx=20)

        self._lbl_file = tk.Label(top, text="", width=35, anchor="w")
        self._lbl_file.grid(row=2, column=0, padx=20, pady=(0, 10))

        tk.Button(top, text="취소", width=10, command=self._cancel).grid(
            row=3, column=0, pady=(0, 16)
        )

        top.update_idletasks()
        _center(top, parent)

    def set_output_path(self, path: Path):
        self._output_path = path

    def run(self, worker_func, on_done):
        """worker_func(progress_cb, cancel_flag) 를 별도 스레드에서 실행."""
        def _thread():
            try:
                result = worker_func(self._progress_cb, self._cancel_flag)
                self._queue.put(("done", result))
            except CancelledError:
                self._queue.put(("cancelled", None))
            except Exception as exc:
                self._queue.put(("error", exc))

        self._on_done = on_done
        threading.Thread(target=_thread, daemon=True).start()
        self._top.after(50, self._poll)

    def _progress_cb(self, current: int, total: int, filename: str):
        self._queue.put(("progress", (current, total, filename)))

    def _cancel(self):
        self._cancel_flag.set()

    def _poll(self):
        try:
            while True:
                msg, data = self._queue.get_nowait()
                if msg == "progress":
                    current, total, filename = data
                    self._pb["maximum"] = total
                    self._pb["value"] = current
                    self._lbl_count.config(text=f"{current} / {total} 파일")
                    self._lbl_file.config(text=filename)
                elif msg == "done":
                    self._top.destroy()
                    self._on_done("done", data)
                    return
                elif msg == "cancelled":
                    self._top.destroy()
                    if self._output_path and self._output_path.exists():
                        self._output_path.unlink()
                    self._on_done("cancelled", None)
                    return
                elif msg == "error":
                    self._top.destroy()
                    self._on_done("error", data)
                    return
        except queue.Empty:
            pass
        self._top.after(50, self._poll)


# ---------------------------------------------------------------------------
# _FileListFrame  (공통 파일 목록 UI)
# ---------------------------------------------------------------------------

class _FileListFrame(tk.Frame):
    """파일 목록 Listbox + 순서 변경 + 추가/제거. 재사용 컴포넌트."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._paths: List[Path] = []
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        lb_frame = tk.Frame(self)
        lb_frame.grid(row=0, column=0, rowspan=4, sticky="nsew")
        lb_frame.rowconfigure(0, weight=1)
        lb_frame.columnconfigure(0, weight=1)

        self._lb = tk.Listbox(lb_frame, selectmode=tk.EXTENDED, width=36, height=10)
        self._lb.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lb_frame, orient="vertical", command=self._lb.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._lb.config(yscrollcommand=sb.set)

        btn_frame = tk.Frame(self)
        btn_frame.grid(row=0, column=1, sticky="n", padx=(4, 0))
        tk.Button(btn_frame, text="▲", width=4, command=self._move_up).pack(pady=(0, 2))
        tk.Button(btn_frame, text="▼", width=4, command=self._move_down).pack(pady=(0, 8))
        tk.Button(btn_frame, text="+추가", width=6, command=self._add_files).pack(pady=(0, 2))
        tk.Button(btn_frame, text="−제거", width=6, command=self._remove_selected).pack()

        Tooltip(self._lb, lambda: self._paths)

    def _refresh_display(self, keep_selection: list = None):
        """번호 포함 Listbox 전체 갱신."""
        self._lb.delete(0, tk.END)
        for i, p in enumerate(self._paths):
            self._lb.insert(tk.END, f"{i + 1}. {p.name}")
        if keep_selection:
            for idx in keep_selection:
                if 0 <= idx < len(self._paths):
                    self._lb.selection_set(idx)

    def _add_files(self):
        files = filedialog.askopenfilenames(
            title="파일 선택",
            filetypes=[
                ("지원 파일", "*.jpg *.jpeg *.png *.bmp *.pdf"),
                ("모든 파일", "*.*"),
            ],
        )
        for f in files:
            self._paths.append(Path(f))
        self._refresh_display()
        self._on_list_changed()

    def _remove_selected(self):
        for idx in reversed(self._lb.curselection()):
            del self._paths[idx]
        self._refresh_display()
        self._on_list_changed()

    def _move_up(self):
        sel = list(self._lb.curselection())
        if not sel or sel[0] == 0:
            return
        for idx in sel:
            self._paths[idx - 1], self._paths[idx] = self._paths[idx], self._paths[idx - 1]
        self._refresh_display([idx - 1 for idx in sel])

    def _move_down(self):
        sel = list(self._lb.curselection())
        if not sel or sel[-1] == self._lb.size() - 1:
            return
        for idx in reversed(sel):
            self._paths[idx], self._paths[idx + 1] = self._paths[idx + 1], self._paths[idx]
        self._refresh_display([idx + 1 for idx in sel])

    def _on_list_changed(self):
        pass  # 서브클래스에서 override

    def set_paths(self, paths: List[Path]):
        self._paths = list(paths)
        self._refresh_display()
        self._on_list_changed()

    @property
    def paths(self) -> List[Path]:
        return list(self._paths)


# ---------------------------------------------------------------------------
# MergeWindow
# ---------------------------------------------------------------------------

class MergeWindow:
    """우클릭 merge 모드 (파일 2개 이상) 또는 도우미에서 병합 모드 실행 시."""

    def __init__(self, parent: Optional[tk.Misc], initial_paths: List[Path]):
        self._parent = parent
        if parent is None:
            self._root = tk.Tk()
            self._top = self._root
        else:
            self._root = None
            self._top = tk.Toplevel(parent)

        self._top.title("PDF 병합")
        self._top.resizable(True, True)
        self._top.protocol("WM_DELETE_WINDOW", self._cancel)
        self._top.bind("<Escape>", lambda _: self._cancel())
        self._top.bind("<Return>", lambda _: self._start_merge())

        self._build()
        sorted_paths = sorted(initial_paths, key=lambda p: p.name)
        self._file_frame.set_paths(sorted_paths)
        self._update_merge_btn()

        _center(self._top, parent)
        self._top.attributes("-topmost", True)
        self._top.focus_force()
        self._top.after(200, lambda: self._top.attributes("-topmost", False))

    def _build(self):
        self._top.columnconfigure(0, weight=1)

        self._file_frame = _FileListFrame(self._top)
        self._file_frame._on_list_changed = self._update_merge_btn  # hook
        self._file_frame.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="nsew")
        self._top.rowconfigure(0, weight=1)

        name_frame = tk.Frame(self._top)
        name_frame.grid(row=1, column=0, padx=12, pady=2, sticky="ew")
        name_frame.columnconfigure(1, weight=1)
        tk.Label(name_frame, text="저장 파일명:").grid(row=0, column=0, sticky="w")
        self._name_var = tk.StringVar(value="merged.pdf")
        name_entry = tk.Entry(name_frame, textvariable=self._name_var)
        name_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        name_entry.bind("<FocusOut>", self._restore_name)

        tk.Label(self._top, text="저장 위치: 첫 번째 파일의 폴더", fg="gray").grid(
            row=2, column=0, padx=12, sticky="w"
        )

        btn_frame = tk.Frame(self._top)
        btn_frame.grid(row=3, column=0, pady=12, padx=12, sticky="e")
        tk.Button(btn_frame, text="취소", width=10, command=self._cancel).pack(side="left", padx=(0, 6))
        self._merge_btn = tk.Button(btn_frame, text="병합 시작", width=12, command=self._start_merge)
        self._merge_btn.pack(side="left")

    def _restore_name(self, _event=None):
        if not self._name_var.get().strip():
            self._name_var.set("merged.pdf")

    def _update_merge_btn(self):
        state = "normal" if self._file_frame.paths else "disabled"
        self._merge_btn.config(state=state)

    def _cancel(self):
        self._top.destroy()
        if self._root:
            self._root.destroy()
        elif self._parent:
            self._parent.destroy()

    def _start_merge(self):
        paths = self._file_frame.paths
        if not paths:
            return
        filename = self._name_var.get().strip() or "merged.pdf"
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        output_dir = paths[0].parent
        output_path = resolve_output_path(output_dir / filename)

        popup = ProgressPopup(self._top, title="병합 중...")
        popup.set_output_path(output_path)

        def worker(progress_cb, cancel_flag):
            return merge_files(paths, output_path, progress_cb, cancel_flag)

        def on_done(status, data):
            if status == "done":
                errors = data
                if errors:
                    failed = "\n".join(str(p) for p, _ in errors)
                    messagebox.showwarning(
                        "병합 완료 (일부 실패)",
                        f"{output_path.name} 생성 완료\n{output_path}\n\n실패 파일:\n{failed}",
                    )
                else:
                    messagebox.showinfo(
                        "병합 완료",
                        f"{output_path.name} 생성 완료\n{output_path}",
                    )
                self._cancel()
            elif status == "error":
                messagebox.showerror("오류", str(data))

        popup.run(worker, on_done)

    def mainloop(self):
        target = self._root or self._parent
        if target:
            target.mainloop()


# ---------------------------------------------------------------------------
# HelperWindow
# ---------------------------------------------------------------------------

class HelperWindow:
    """도우미 GUI — 더블클릭 또는 인수 없이 실행 시."""

    def __init__(self):
        self._root = tk.Tk()
        self._root.title("PDF 변환 도구")
        self._root.resizable(True, True)
        self._root.protocol("WM_DELETE_WINDOW", self._root.destroy)
        self._root.bind("<Escape>", lambda _: self._root.destroy())
        self._root.bind("<Return>", lambda _: self._run())
        self._build()
        _center(self._root, None)

    def _build(self):
        root = self._root
        root.columnconfigure(0, weight=1)

        self._file_frame = _FileListFrame(root)
        self._file_frame.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="nsew")
        root.rowconfigure(0, weight=1)

        # 라디오버튼
        self._mode_var = tk.StringVar(value="merge")
        radio_frame = tk.Frame(root)
        radio_frame.grid(row=1, column=0, padx=12, sticky="w")
        tk.Radiobutton(
            radio_frame, text="각 파일을 별도 PDF로 변환",
            variable=self._mode_var, value="convert",
            command=self._on_mode_change,
        ).pack(anchor="w")
        tk.Radiobutton(
            radio_frame, text="하나의 PDF로 병합",
            variable=self._mode_var, value="merge",
            command=self._on_mode_change,
        ).pack(anchor="w")

        # 파일명 입력란
        name_frame = tk.Frame(root)
        name_frame.grid(row=2, column=0, padx=12, pady=2, sticky="ew")
        name_frame.columnconfigure(1, weight=1)
        tk.Label(name_frame, text="저장 파일명:").grid(row=0, column=0, sticky="w")
        self._name_var = tk.StringVar(value="merged.pdf")
        self._name_entry = tk.Entry(name_frame, textvariable=self._name_var)
        self._name_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self._name_entry.bind("<FocusOut>", self._restore_name)

        tk.Label(root, text="저장 위치: 첫 번째 파일의 폴더", fg="gray").grid(
            row=3, column=0, padx=12, sticky="w"
        )

        sep = ttk.Separator(root, orient="horizontal")
        sep.grid(row=4, column=0, sticky="ew", padx=12, pady=6)

        # 메뉴 등록/제거 + 취소/실행
        bottom = tk.Frame(root)
        bottom.grid(row=5, column=0, padx=12, pady=(0, 12), sticky="ew")
        bottom.columnconfigure(1, weight=1)

        left_btn = tk.Frame(bottom)
        left_btn.grid(row=0, column=0, sticky="w")
        tk.Button(left_btn, text="메뉴 등록", command=self._do_install).pack(side="left", padx=(0, 4))
        tk.Button(left_btn, text="메뉴 제거", command=self._do_uninstall).pack(side="left")

        right_btn = tk.Frame(bottom)
        right_btn.grid(row=0, column=1, sticky="e")
        tk.Button(right_btn, text="취소", width=8, command=self._root.destroy).pack(side="left", padx=(0, 6))
        tk.Button(right_btn, text="실행", width=10, command=self._run).pack(side="left")

    def _on_mode_change(self):
        if self._mode_var.get() == "convert":
            self._name_entry.config(state="disabled")
        else:
            self._name_entry.config(state="normal")

    def _restore_name(self, _event=None):
        if not self._name_var.get().strip():
            self._name_var.set("merged.pdf")

    def _do_install(self):
        try:
            install()
            messagebox.showinfo("메뉴 등록", "등록 완료 (※ exe 이동 시 재등록 필요)")
        except Exception as exc:
            messagebox.showerror("오류", str(exc))

    def _do_uninstall(self):
        try:
            uninstall()
            messagebox.showinfo("메뉴 제거", "메뉴가 제거되었습니다.")
        except Exception as exc:
            messagebox.showerror("오류", str(exc))

    def _run(self):
        paths = self._file_frame.paths
        if not paths:
            messagebox.showwarning("파일 없음", "파일을 추가해 주세요.")
            return

        mode = self._mode_var.get()

        if mode == "convert":
            img_paths = [p for p in paths if p.suffix.lower() in SUPPORTED_IMG]
            if not img_paths:
                messagebox.showerror("오류", "지원되는 이미지 파일이 없습니다.")
                return
            self._run_convert(img_paths)
        else:
            self._run_merge(paths)

    def _run_convert(self, img_paths: List[Path]):
        popup = ProgressPopup(self._root, title="변환 중...")
        total = len(img_paths)
        results: List[Path] = []

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

        popup.run(worker, on_done)

    def _run_merge(self, paths: List[Path]):
        filename = self._name_var.get().strip() or "merged.pdf"
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        output_dir = paths[0].parent
        output_path = resolve_output_path(output_dir / filename)

        popup = ProgressPopup(self._root, title="병합 중...")
        popup.set_output_path(output_path)

        def worker(progress_cb, cancel_flag):
            return merge_files(paths, output_path, progress_cb, cancel_flag)

        def on_done(status, data):
            if status == "done":
                errors = data
                if errors:
                    failed = "\n".join(str(p) for p, _ in errors)
                    messagebox.showwarning(
                        "병합 완료 (일부 실패)",
                        f"{output_path.name} 생성 완료\n{output_path}\n\n실패 파일:\n{failed}",
                    )
                else:
                    messagebox.showinfo(
                        "병합 완료",
                        f"{output_path.name} 생성 완료\n{output_path}",
                    )
            elif status == "error":
                messagebox.showerror("오류", str(data))

        popup.run(worker, on_done)

    def mainloop(self):
        self._root.mainloop()


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------

def _center(win: tk.Misc, parent: Optional[tk.Misc]):
    win.withdraw()
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    if parent and parent.winfo_viewable():
        px = parent.winfo_rootx() + parent.winfo_width() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2
    else:
        px = win.winfo_screenwidth() // 2
        py = win.winfo_screenheight() // 2
    win.geometry(f"{w}x{h}+{px - w // 2}+{py - h // 2}")
    win.deiconify()
