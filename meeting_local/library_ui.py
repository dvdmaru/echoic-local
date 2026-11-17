"""會議庫視窗：依分類篩選、關鍵字搜尋、設定分類、匯出、專案追蹤、AI 助理連線（MCP）設定。只用 tkinter。"""
from __future__ import annotations

import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import config, library, mcp_server, settings

ALL = "（全部）"
NONE = "（未分類）"
KEEP = "（不改）"


def _open(path: Path) -> None:
    subprocess.Popen(["open", str(path)])


def _center(win: tk.Toplevel, parent: tk.Misc) -> None:
    win.transient(parent)
    win.update_idletasks()
    x = parent.winfo_rootx() + 40
    y = parent.winfo_rooty() + 40
    win.geometry(f"+{x}+{y}")


class LibraryWindow:
    def __init__(self, parent: tk.Misc, out_root: Path):
        self.parent = parent
        self.out_root = out_root
        self.win = tk.Toplevel(parent)
        self.win.title("會議庫")
        self.win.geometry("980x680")
        self.win.minsize(760, 520)
        self.meetings: list[library.Meeting] = []
        self.shown: list[library.Meeting] = []
        self.hits: dict[str, list[dict]] = {}
        self.busy = False

        frm = ttk.Frame(self.win, padding=10)
        frm.pack(fill="both", expand=True)

        self.filter_row = ttk.Frame(frm)
        self.filter_row.pack(fill="x")
        self.filter_vars: dict[str, tk.StringVar] = {}
        self.filter_boxes: dict[str, ttk.Combobox] = {}

        q_row = ttk.Frame(frm)
        q_row.pack(fill="x", pady=(6, 6))
        ttk.Label(q_row, text="關鍵字：").pack(side="left")
        self.query_var = tk.StringVar()
        ent = ttk.Entry(q_row, textvariable=self.query_var, width=30)
        ent.pack(side="left")
        ent.bind("<Return>", lambda _e: self.refresh())
        ttk.Button(q_row, text="搜尋", command=self.refresh).pack(side="left", padx=(6, 0))
        ttk.Button(q_row, text="清除", command=self.clear_filters).pack(side="left", padx=(6, 0))
        self.tr_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(q_row, text="也搜逐字稿", variable=self.tr_var, command=self.refresh).pack(side="left", padx=(10, 0))
        ttk.Label(q_row, text="多個詞用空白分隔＝都要出現", foreground="#777").pack(side="left", padx=(10, 0))

        body = ttk.PanedWindow(frm, orient="vertical")
        body.pack(fill="both", expand=True)
        tree_frame = ttk.Frame(body)
        self.tree = ttk.Treeview(tree_frame, show="headings", selectmode="extended")
        ysb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_detail())
        self.tree.bind("<Double-1>", lambda _e: self.open_summary())
        body.add(tree_frame, weight=3)
        self.detail = tk.Text(body, height=9, wrap="word", font=("PingFang TC", 13), bg="#f6f6f6")
        self.detail.tag_configure("hit", foreground="#b3261e")
        self.detail.tag_configure("head", font=("PingFang TC", 13, "bold"))
        body.add(self.detail, weight=1)

        b1 = ttk.Frame(frm)
        b1.pack(fill="x", pady=(8, 0))
        ttk.Button(b1, text="設定分類…", command=self.edit_labels).pack(side="left")
        ttk.Button(b1, text="開啟摘要", command=self.open_summary).pack(side="left", padx=(6, 0))
        ttk.Button(b1, text="開啟資料夾", command=self.open_folder).pack(side="left", padx=(6, 0))
        ttk.Button(b1, text="匯出 Markdown…", command=lambda: self.export("md")).pack(side="left", padx=(16, 0))
        ttk.Button(b1, text="匯出 HTML…", command=lambda: self.export("html")).pack(side="left", padx=(6, 0))
        ttk.Button(b1, text="重新整理", command=self.reload).pack(side="right")

        b2 = ttk.Frame(frm)
        b2.pack(fill="x", pady=(6, 0))
        ttk.Button(b2, text="專案追蹤（這組分類）", command=self.thread).pack(side="left")
        self.btn_ai = ttk.Button(b2, text="請 Claude 整理進度…", command=self.thread_ai)
        self.btn_ai.pack(side="left", padx=(6, 0))
        if not config.claude_available():
            self.btn_ai.state(["disabled"])
        ttk.Button(b2, text="分類欄位…", command=self.edit_categories).pack(side="right")
        ttk.Button(b2, text="AI 助理連線…", command=self.mcp_settings).pack(side="right", padx=(0, 6))

        self.status = ttk.Label(frm, text="", foreground="#555", wraplength=940)
        self.status.pack(anchor="w", pady=(6, 0))

        self.reload()

    # ------------------------------------------------------------ 資料
    def categories(self) -> list[str]:
        return settings.load()["categories"]

    def reload(self) -> None:
        self.meetings = library.load_meetings(self.out_root)
        self._build_filters()
        self._build_columns()
        self.refresh()

    def _build_filters(self) -> None:
        old = {k: v.get() for k, v in self.filter_vars.items()}
        for w in self.filter_row.winfo_children():
            w.destroy()
        self.filter_vars.clear()
        self.filter_boxes.clear()
        values = library.label_values(self.meetings, self.categories())
        for cat in self.categories():
            ttk.Label(self.filter_row, text=f"{cat}：").pack(side="left")
            var = tk.StringVar(value=old.get(cat, ALL))
            box = ttk.Combobox(self.filter_row, textvariable=var, state="readonly", width=16,
                               values=[ALL, NONE, *values.get(cat, {}).keys()])
            box.pack(side="left", padx=(0, 12))
            box.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
            self.filter_vars[cat] = var
            self.filter_boxes[cat] = box
        ttk.Label(self.filter_row, text="日期從").pack(side="left")
        self.from_var = getattr(self, "from_var", tk.StringVar())
        self.to_var = getattr(self, "to_var", tk.StringVar())
        e1 = ttk.Entry(self.filter_row, textvariable=self.from_var, width=11)
        e1.pack(side="left", padx=(4, 4))
        ttk.Label(self.filter_row, text="到").pack(side="left")
        e2 = ttk.Entry(self.filter_row, textvariable=self.to_var, width=11)
        e2.pack(side="left", padx=(4, 0))
        for e in (e1, e2):
            e.bind("<Return>", lambda _e: self.refresh())
        ttk.Label(self.filter_row, text="（YYYY-MM-DD）", foreground="#777").pack(side="left")

    def _build_columns(self) -> None:
        cols = ["date", "time", "title", *[f"c:{c}" for c in self.categories()], "todos", "stage"]
        self.tree.configure(columns=cols)
        heads = {"date": ("日期", 92), "time": ("時間", 52), "title": ("標題", 300), "todos": ("待辦", 48), "stage": ("狀態", 84)}
        for c in cols:
            text, width = heads.get(c, (c[2:], 120))
            self.tree.heading(c, text=text)
            self.tree.column(c, width=width, stretch=(c == "title"), anchor="w")

    def current_labels(self) -> dict[str, str]:
        out = {}
        for cat, var in self.filter_vars.items():
            v = var.get()
            if v == NONE:
                out[cat] = library.UNLABELED
            elif v and v != ALL:
                out[cat] = v
        return out

    def clear_filters(self) -> None:
        for var in self.filter_vars.values():
            var.set(ALL)
        self.query_var.set("")
        self.from_var.set("")
        self.to_var.set("")
        self.refresh()

    def refresh(self) -> None:
        ms = library.filter_meetings(self.meetings, self.current_labels(),
                                     self.from_var.get().strip() or None, self.to_var.get().strip() or None)
        q = self.query_var.get().strip()
        self.hits = {}
        if q:
            res = library.search(ms, q, include_transcript=self.tr_var.get())
            ms = [r["meeting"] for r in res]
            self.hits = {r["meeting"].id: r["hits"] for r in res}
        self.shown = ms
        self.tree.delete(*self.tree.get_children())
        cats = self.categories()
        for m in ms:
            open_todos = sum(1 for t in m.todos if not t.done)
            self.tree.insert("", "end", iid=m.id, values=(
                m.date, m.clock, m.title, *[m.labels.get(c, "") for c in cats], open_todos or "", m.stage))
        msg = f"{len(ms)} 場" + (f"符合「{q}」" if q else "") + f"（全部 {len(self.meetings)} 場）"
        unl = sum(1 for m in self.meetings if not m.labels)
        if unl:
            msg += f"｜{unl} 場還沒分類：選起來（可多選）按「設定分類…」"
        self.status.configure(text=msg)
        self.show_detail()

    def selected(self) -> list[library.Meeting]:
        ids = set(self.tree.selection())
        return [m for m in self.shown if m.id in ids]

    def show_detail(self) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        sel = self.selected()
        if len(sel) == 1:
            m = sel[0]
            self.detail.insert("end", f"{m.date} {m.clock}｜{m.title}\n", "head")
            if m.labels:
                self.detail.insert("end", "分類：" + "、".join(f"{k}＝{v}" for k, v in m.labels.items()) + "\n")
            if m.private:
                self.detail.insert("end", "🔒 不給 AI 助理讀\n")
            for h in self.hits.get(m.id, []):
                ts = f" {h['timestamp']}" if h["timestamp"] else ""
                self._insert_hit(f"[{h['source']}{ts}] {h['text']}\n")
            if not self.hits.get(m.id):
                if m.one_liner:
                    self.detail.insert("end", m.one_liner + "\n")
                for d in m.decisions[:6]:
                    self.detail.insert("end", f"・{d}\n")
                for t in m.todos:
                    if not t.done:
                        self.detail.insert("end", f"☐ {t.text}（{t.owner or '未指定'}）\n")
        elif len(sel) > 1:
            self.detail.insert("end", f"選了 {len(sel)} 場：可一起設定分類或匯出成一份彙整。\n")
        self.detail.configure(state="disabled")

    def _insert_hit(self, text: str) -> None:
        parts = text.split("**")
        for i, p in enumerate(parts):
            self.detail.insert("end", p, "hit" if i % 2 else ())

    # ------------------------------------------------------------ 動作
    def open_folder(self) -> None:
        sel = self.selected()
        if sel:
            _open(sel[0].folder)
        else:
            _open(self.out_root)

    def open_summary(self) -> None:
        sel = self.selected()
        if not sel:
            return
        m = sel[0]
        _open(m.summary_path if m.summary_path.exists() else m.folder)

    def edit_labels(self) -> None:
        sel = self.selected()
        if not sel:
            messagebox.showinfo("設定分類", "先在清單裡選會議（可按住 ⌘ 或 Shift 多選）。", parent=self.win)
            return
        LabelDialog(self, sel)

    def export(self, fmt: str) -> None:
        ms = self.selected() or self.shown
        if not ms:
            messagebox.showinfo("匯出", "清單是空的，沒有可匯出的會議。", parent=self.win)
            return
        if len(ms) == 1:
            title, date = ms[0].title, ms[0].date
        else:
            key = library.thread_key({k: v for k, v in self.current_labels().items() if v})
            title, date = f"{key or '會議'} 會議彙整", time.strftime("%Y-%m-%d")
        ans = messagebox.askyesnocancel(
            "匯出", f"匯出 {len(ms)} 場（{'選取的' if self.selected() else '清單上全部'}）。\n\n要附上逐字稿嗎？"
            "（逐字稿很長；只要摘要按「否」）", parent=self.win)
        if ans is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self.win, initialdir=str(Path.home() / "Downloads"),
            initialfile=library.export_name(title, date, fmt),
            defaultextension=".html" if fmt == "html" else ".md",
            filetypes=[("HTML", "*.html")] if fmt == "html" else [("Markdown", "*.md")])
        if not path:
            return
        try:
            library.export(Path(path), title, ms, fmt=fmt, include_transcript=bool(ans))
        except (OSError, ValueError) as exc:
            messagebox.showerror("匯出失敗", str(exc), parent=self.win)
            return
        self.status.configure(text=f"✅ 已匯出 {len(ms)} 場 → {path}")
        subprocess.Popen(["open", "-R", path])

    def _thread_labels(self) -> dict[str, str] | None:
        labels = {k: v for k, v in self.current_labels().items() if v}
        if not labels:
            messagebox.showinfo("專案追蹤", "先在上面選一個分類（例如某個客戶，或客戶＋專案），再按這個鈕。", parent=self.win)
            return None
        return labels

    def thread(self) -> None:
        labels = self._thread_labels()
        if not labels:
            return
        ms = library.filter_meetings(self.meetings, labels)
        if not ms:
            messagebox.showinfo("專案追蹤", "這組分類目前沒有會議。", parent=self.win)
            return
        path = library.write_thread(self.out_root, labels, ms)
        self.status.configure(text=f"🧵 專案追蹤已更新（{len(ms)} 場）：{path}")
        _open(path)

    def thread_ai(self) -> None:
        labels = self._thread_labels()
        if not labels or self.busy:
            return
        ms = library.filter_meetings(self.meetings, labels)
        n = sum(1 for m in ms if m.summary_path.exists())
        if not n:
            messagebox.showinfo("請 Claude 整理", "這組會議都還沒有摘要，先產生摘要才能整理。", parent=self.win)
            return
        if not messagebox.askyesno(
            "請 Claude 整理進度",
            f"會把「{library.thread_key(labels)}」{n} 場會議的摘要（一句話、決議、待辦、數字表，不含逐字稿）"
            "送給這台電腦登入的 Claude，整理出目前進度、決議前後不一致、待辦追蹤、下次要追的事。\n\n"
            "會用到你自己 Claude 方案的用量。要繼續嗎？", parent=self.win):
            return
        self.busy = True
        self.btn_ai.state(["disabled"])
        self.status.configure(text=f"⏳ Claude 正在讀 {n} 場摘要整理進度…（通常一兩分鐘）")

        def worker() -> None:
            try:
                report = library.project_report(labels, ms, model=config.CLAUDE_MODEL)
                meta = f"Claude 整理：{time.strftime('%Y-%m-%d %H:%M')}，讀了 {n} 場摘要"
                path = library.write_thread(self.out_root, labels, ms, ai_report=report, ai_meta=meta)
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                self.win.after(0, self._ai_done, None, str(exc))
            else:
                self.win.after(0, self._ai_done, path, "")

        threading.Thread(target=worker, daemon=True).start()

    def _ai_done(self, path: Path | None, err: str) -> None:
        self.busy = False
        if config.claude_available():
            self.btn_ai.state(["!disabled"])
        if path is None:
            self.status.configure(text=f"❌ 整理失敗：{err}")
            return
        self.status.configure(text=f"✅ 進度整理完成：{path}")
        _open(path)

    def edit_categories(self) -> None:
        CategoriesDialog(self)

    def mcp_settings(self) -> None:
        McpDialog(self)


class LabelDialog:
    def __init__(self, lib: LibraryWindow, meetings: list[library.Meeting]):
        self.lib = lib
        self.meetings = meetings
        self.win = tk.Toplevel(lib.win)
        self.win.title("設定分類")
        _center(self.win, lib.win)
        frm = ttk.Frame(self.win, padding=14)
        frm.pack(fill="both", expand=True)
        head = meetings[0].title if len(meetings) == 1 else f"{len(meetings)} 場會議"
        ttk.Label(frm, text=f"替「{head}」設定分類", font=("PingFang TC", 14, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frm, text="可直接打新的值，或從下拉選既有的。清空＝移除這個分類。"
                  + ("「（不改）」＝這幾場維持各自原本的值。" if len(meetings) > 1 else ""),
                  foreground="#666", wraplength=420).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 8))
        values = library.label_values(lib.meetings, lib.categories())
        self.vars: dict[str, tk.StringVar] = {}
        for i, cat in enumerate(lib.categories(), start=2):
            cur = {m.labels.get(cat, "") for m in meetings}
            init = cur.pop() if len(cur) == 1 else KEEP
            var = tk.StringVar(value=init)
            ttk.Label(frm, text=f"{cat}：").grid(row=i, column=0, sticky="e", pady=3)
            opts = list(values.get(cat, {}).keys())
            if len(meetings) > 1:
                opts = [KEEP, *opts]
            ttk.Combobox(frm, textvariable=var, values=opts, width=28).grid(row=i, column=1, sticky="w", pady=3)
            self.vars[cat] = var
        priv = {m.private for m in meetings}
        self.private_var = tk.BooleanVar(value=priv == {True})
        self.private_touched = False
        r = len(lib.categories()) + 2
        ttk.Checkbutton(frm, text="不給 AI 助理讀（MCP 連線的助理看不到、搜不到這幾場；App 裡照常可看）", variable=self.private_var,
                        command=self._touch).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))
        if len(priv) > 1:
            ttk.Label(frm, text="（目前這幾場設定不一致；不勾不動就維持原狀）", foreground="#666").grid(
                row=r + 1, column=0, columnspan=2, sticky="w")
        btns = ttk.Frame(frm)
        btns.grid(row=r + 2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="取消", command=self.win.destroy).pack(side="right")
        ttk.Button(btns, text="儲存", command=self.save).pack(side="right", padx=(0, 6))
        self.win.bind("<Return>", lambda _e: self.save())

    def _touch(self) -> None:
        self.private_touched = True

    def save(self) -> None:
        labels = {cat: var.get().strip() for cat, var in self.vars.items() if var.get() != KEEP}
        private = self.private_var.get() if (self.private_touched or len({m.private for m in self.meetings}) == 1) else None
        try:
            for m in self.meetings:
                library.write_meta(m.folder, labels=labels, private=private)
            n = len(library.refresh_threads(self.lib.out_root)) if library.existing_threads(self.lib.out_root) else 0
            for m in self.meetings:
                if library.read_meta(m.folder)["labels"]:
                    n += len(library.refresh_threads(self.lib.out_root, m.folder))
            from .index import write_index
            write_index(self.lib.out_root)
        except OSError as exc:
            messagebox.showerror("儲存失敗", str(exc), parent=self.win)
            return
        self.win.destroy()
        keep = set(self.lib.tree.selection())
        self.lib.reload()
        for iid in keep:
            if self.lib.tree.exists(iid):
                self.lib.tree.selection_add(iid)
        self.lib.status.configure(text=f"✅ 已更新 {len(self.meetings)} 場的分類，會議索引與專案追蹤已同步。")


class CategoriesDialog:
    def __init__(self, lib: LibraryWindow):
        self.lib = lib
        self.win = tk.Toplevel(lib.win)
        self.win.title("分類欄位")
        _center(self.win, lib.win)
        frm = ttk.Frame(self.win, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="會議用哪些欄位分類（逗號分隔，最多 6 個）", font=("PingFang TC", 14, "bold")).pack(anchor="w")
        ttk.Label(frm, text="例：客戶, 專案　或　部門, 主題, 對象。會議時間不用設，直接用日期篩。\n"
                  "改名不會搬動已設好的值：舊欄位的值仍留在各場的 meta.json，改回原名就會再出現。",
                  foreground="#666", wraplength=440, justify="left").pack(anchor="w", pady=(2, 8))
        self.var = tk.StringVar(value=", ".join(lib.categories()))
        ttk.Entry(frm, textvariable=self.var, width=44).pack(anchor="w")
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="取消", command=self.win.destroy).pack(side="right")
        ttk.Button(btns, text="儲存", command=self.save).pack(side="right", padx=(0, 6))

    def save(self) -> None:
        import re

        cats = [c.strip() for c in re.split(r"[,，、]", self.var.get()) if c.strip()]
        if not settings._valid("categories", cats):
            messagebox.showerror("分類欄位", f"要 1～{settings.MAX_CATEGORIES} 個、不能重複。", parent=self.win)
            return
        settings.save({"categories": cats})
        self.win.destroy()
        self.lib.reload()


class McpDialog:
    def __init__(self, lib: LibraryWindow):
        self.lib = lib
        prefs = settings.load()
        self.win = tk.Toplevel(lib.win)
        self.win.title("AI 助理連線（MCP）")
        _center(self.win, lib.win)
        frm = ttk.Frame(self.win, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="讓你自己的 AI 助理讀會議記錄", font=("PingFang TC", 14, "bold")).pack(anchor="w")
        ttk.Label(frm, wraplength=560, justify="left", foreground="#444", text=(
            "打開後，你設定過的 AI 助理（Claude Desktop、Claude Code 等支援 MCP 的 App）可以列出、搜尋、讀取會議摘要與逐字稿，"
            "也能看同一客戶／專案的進度與待辦。只能讀，不能改或刪任何檔。\n"
            "⚠️ 助理讀到的內容會送到那個助理背後的 AI 服務（例如 Claude 就是 Anthropic）。"
            "公司或客戶的會議，請先確認那家服務可以用；不想給的會議，在會議庫「設定分類…」勾「不給 AI 助理讀」。")
        ).pack(anchor="w", pady=(4, 8))

        self.enabled = tk.BooleanVar(value=prefs["mcp_enabled"])
        self.transcripts = tk.BooleanVar(value=prefs["mcp_transcripts"])
        ttk.Checkbutton(frm, text="允許 AI 助理讀取會議記錄", variable=self.enabled).pack(anchor="w")
        ttk.Checkbutton(frm, text="也給逐字稿（不勾＝只給摘要、待辦與專案追蹤）", variable=self.transcripts).pack(anchor="w", padx=(22, 0))

        scope = ttk.LabelFrame(frm, text="只開放這些分類（留空＝全部；多個值用逗號分隔）", padding=8)
        scope.pack(fill="x", pady=(8, 0))
        values = library.label_values(lib.meetings, lib.categories())
        self.scope_vars: dict[str, tk.StringVar] = {}
        for i, cat in enumerate(lib.categories()):
            ttk.Label(scope, text=f"{cat}：").grid(row=i * 2, column=0, sticky="e")
            var = tk.StringVar(value=", ".join(prefs["mcp_scope"].get(cat, [])))
            ttk.Entry(scope, textvariable=var, width=44).grid(row=i * 2, column=1, sticky="w")
            have = "、".join(list(values.get(cat, {}).keys())[:12]) or "（還沒有）"
            ttk.Label(scope, text=f"現有：{have}", foreground="#777", wraplength=440).grid(row=i * 2 + 1, column=1, sticky="w")
            self.scope_vars[cat] = var

        ttk.Label(frm, text="接到 AI 助理（設定一次即可）：", font=("PingFang TC", 13, "bold")).pack(anchor="w", pady=(12, 2))
        ttk.Label(frm, text="Claude Desktop：設定 → 開發者 → 編輯設定，把下面這段的 echoic-local 加進 mcpServers，存檔後重開 Claude Desktop。",
                  wraplength=560, foreground="#444").pack(anchor="w")
        box = tk.Text(frm, height=8, width=70, font=("Menlo", 11), bg="#f6f6f6")
        box.insert("1.0", mcp_server.client_config_json())
        box.configure(state="disabled")
        box.pack(anchor="w", fill="x")
        row = ttk.Frame(frm)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="複製 Claude Desktop 設定", command=lambda: self.copy(mcp_server.client_config_json())).pack(side="left")
        ttk.Button(row, text="複製 Claude Code 指令", command=lambda: self.copy(mcp_server.claude_code_command())).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="讀取紀錄", command=self.open_log).pack(side="left", padx=(6, 0))
        self.note = ttk.Label(frm, text="", foreground="#555")
        self.note.pack(anchor="w", pady=(4, 0))

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="取消", command=self.win.destroy).pack(side="right")
        ttk.Button(btns, text="儲存", command=self.save).pack(side="right", padx=(0, 6))

    def copy(self, text: str) -> None:
        self.win.clipboard_clear()
        self.win.clipboard_append(text)
        self.note.configure(text="✅ 已複製到剪貼簿")

    def open_log(self) -> None:
        path = mcp_server.access_log_path()
        if path.exists():
            _open(path)
        else:
            self.note.configure(text="還沒有任何 AI 助理讀取過。")

    def save(self) -> None:
        import re

        scope = {}
        for cat, var in self.scope_vars.items():
            vals = [v.strip() for v in re.split(r"[,，、]", var.get()) if v.strip()]
            if vals:
                scope[cat] = vals
        settings.save({"mcp_enabled": self.enabled.get(), "mcp_transcripts": self.transcripts.get(), "mcp_scope": scope})
        self.win.destroy()
        state = "開" if self.enabled.get() else "關"
        self.lib.status.configure(text=f"AI 助理讀取：{state}（下一次助理呼叫就生效，不用重開助理）")
