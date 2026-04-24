import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import shutil
from pathlib import Path
import logging
import webbrowser

# 智能缩放记录：鼠标/键盘全局监听（用于生成 events.json）
try:
    from pynput import mouse as _pynput_mouse  # type: ignore
    from pynput import keyboard as _pynput_keyboard  # type: ignore

    _PYNPUT_OK = True
except Exception:
    _pynput_mouse = None  # type: ignore
    _pynput_keyboard = None  # type: ignore
    _PYNPUT_OK = False

# 构建期：强制 PyInstaller 收集剪映导入依赖（运行时失败会被吞掉，不影响录屏）
try:
    import _jy_embed_imports  # noqa: F401
except Exception:
    pass


# --- Windows DPI Awareness Fix ---
if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        pass


class VideoRecorderApp:
    """
    仅录制视频（可选麦克风）GUI。

    - 桌面录屏：ffmpeg gdigrab
    - 麦克风：优先 ffmpeg dshow；若本机 DirectShow 枚举失败则回退 WASAPI / OpenAL（取决于 ffmpeg 编译能力）
    - 保存目录：可选择并持久化
    - 停止：圆形悬浮按钮（轻点停止，拖拽不停止）
    """

    def __init__(self):
        self.is_recording = False
        self.process = None

        self.mini_size = 34
        self._transparent_key = "#ff00ff"

        self.root = tk.Tk()
        self._init_ttk_style()
        self.root.title("录屏助手（仅录制）")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#2c3e50")

        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recorder_config.json")
        self.output_dir = os.path.abspath(os.getcwd())
        self.ffmpeg_path = ""
        # 清晰度：影响编码参数（preset/crf），默认取“高”（更清晰）
        self.quality_level = "高"
        self._last_audio_enum_log = ""
        # 下拉框展示名 -> {"fmt": "dshow|wasapi|openal", "iarg": "传给 ffmpeg -i 的完整参数字符串"}
        self.audio_route: dict[str, dict[str, str]] = {}
        # 智能缩放记录开关（鼠标/键盘）。说明：
        # - smart_zoomer.py 会读取 events.json 中的 click/move 事件
        # - 键盘事件目前用于“用户确实有操作”的信号，未来可扩展更复杂的镜头逻辑
        self.enable_zoom_record = tk.BooleanVar(value=True)
        self.start_time = 0.0
        self.events: list[dict] = []
        self.m_listener = None
        self.k_listener = None
        self._events_lock = threading.Lock()
        self._last_move_time = 0.0
        self._last_move_pos = (0, 0)
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()

        self.events_path = ""
        # “保存到剪映草稿”依赖：外部 python + 仓库脚本（打包 exe 默认不包含仓库代码）
        self.python_path = ""
        self.jy_wrapper_path = ""
        self.load_config()

        # 日志目录：exe 同级 logs（源码运行时为脚本同级）
        self.app_dir = self._get_app_dir()
        self.logs_dir = os.path.join(self.app_dir, "logs")
        os.makedirs(self.logs_dir, exist_ok=True)
        self._setup_logging()

        self.output_dir_var = tk.StringVar(value=self.output_dir)
        self.ffmpeg_var = tk.StringVar(value=self.ffmpeg_path or "")
        self.quality_var = tk.StringVar(value=self.quality_level)

        # ---- 主界面 ----
        self.main_frame = tk.Frame(self.root, bg="#2c3e50")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.status_label = tk.Label(
            self.main_frame,
            text="准备就绪",
            fg="#ecf0f1",
            bg="#2c3e50",
            font=("Microsoft YaHei", 12, "bold"),
        )
        self.status_label.pack(pady=(10, 8))

        # ffmpeg 可用性检查（双击 bat 时常见 PATH 不一致）
        if not self._resolve_ffmpeg_exe():
            self._notify_ffmpeg_missing()

        if sys.platform == "win32":
            self._enumerate_audio_inputs()
        else:
            self.audio_devices, self.audio_route = [], {}
        initial_audio = self.audio_devices[0] if self.audio_devices else ""
        self.audio_var = tk.StringVar(value=initial_audio)

        self.info_label = tk.Label(
            self.main_frame,
            text=f"麦克风录音：{'已开启' if initial_audio else '已禁用'}  ·  保存至：{self._short_path(self.output_dir)}/",
            fg="#bdc3c7",
            bg="#2c3e50",
            font=("Microsoft YaHei", 8),
        )
        self.info_label.pack(pady=(0, 6))

        # --- 设置卡片 ---
        settings_card = tk.Frame(
            self.main_frame,
            bg="#2f4153",
            highlightbackground="#3a5166",
            highlightthickness=1,
        )
        settings_card.pack(pady=(8, 6), padx=18, fill=tk.X)

        settings_inner = tk.Frame(settings_card, bg="#2f4153")
        settings_inner.pack(padx=12, pady=10, fill=tk.X)

        # FFmpeg（可选择路径，避免 bat/资源管理器启动时 PATH 不一致）
        ff_frame = tk.Frame(settings_inner, bg="#2f4153")
        ff_frame.pack(pady=(0, 8), fill=tk.X)
        ff_frame.grid_columnconfigure(0, weight=1)

        tk.Label(
            ff_frame,
            text="FFmpeg",
            fg="#aeb9c5",
            bg="#2f4153",
            font=("Microsoft YaHei", 9),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        ff_row = tk.Frame(ff_frame, bg="#2f4153")
        ff_row.grid(row=1, column=0, sticky="ew")
        ff_row.grid_columnconfigure(0, weight=1)

        self.ffmpeg_entry = tk.Entry(
            ff_row,
            textvariable=self.ffmpeg_var,
            state="readonly",
            readonlybackground="#34495e",
            fg="#ecf0f1",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#3a5166",
            highlightcolor="#3a5166",
        )
        self.ffmpeg_entry.grid(row=0, column=0, sticky="ew", ipady=5)

        self.ffmpeg_btn = tk.Button(
            ff_row,
            text="选择…",
            command=self.choose_ffmpeg_exe,
            bg="#3d566e",
            fg="white",
            font=("Microsoft YaHei", 9),
            relief="flat",
            padx=10,
        )
        self.ffmpeg_btn.grid(row=0, column=1, padx=(10, 0), ipady=1)

        # FFmpeg 下载按钮（打开浏览器）
        self.download_ffmpeg_btn = tk.Button(
            ff_row,
            text="下载FFmpeg",
            command=self.open_ffmpeg_download,
            bg="#34495e",
            fg="white",
            font=("Microsoft YaHei", 9),
            relief="flat",
            padx=10,
        )
        self.download_ffmpeg_btn.grid(row=0, column=3, padx=(10, 0), ipady=1)

        # 麦克风 + 清晰度：同一行展示
        mic_quality_row = tk.Frame(settings_inner, bg="#2f4153")
        mic_quality_row.pack(pady=(0, 8), fill=tk.X)
        mic_quality_row.grid_columnconfigure(0, weight=1)
        mic_quality_row.grid_columnconfigure(1, weight=1)

        mic_frame = tk.Frame(mic_quality_row, bg="#2f4153")
        mic_frame.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        mic_frame.grid_columnconfigure(0, weight=1)

        # 用“刷新麦克风”按钮替换标题“麦克风”，更紧凑也更一致
        self.refresh_audio_btn = tk.Button(
            mic_frame,
            text="刷新麦克风",
            command=self.reload_audio_devices,
            bg="#34495e",
            fg="white",
            font=("Microsoft YaHei", 9),
            relief="flat",
            padx=10,
        )
        self.refresh_audio_btn.grid(row=0, column=0, sticky="w", pady=(0, 6))

        # 始终使用 combobox（即使为空也可后续刷新）
        self.audio_combo = ttk.Combobox(
            mic_frame,
            textvariable=self.audio_var,
            values=self.audio_devices,
            state="readonly",
            style="JY.TCombobox",
        )
        self.audio_combo.grid(row=1, column=0, sticky="ew", ipady=3)

        quality_frame = tk.Frame(mic_quality_row, bg="#2f4153")
        quality_frame.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        quality_frame.grid_columnconfigure(0, weight=1)

        # 标题也做成“按钮外观”，提升一致性（仅作展示，不可点击）
        tk.Label(
            quality_frame,
            text="清晰度",
            bg="#34495e",
            fg="white",
            font=("Microsoft YaHei", 9),
            anchor="w",
            padx=10,
            pady=2,
            relief="flat",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        # 单选框（圆点形式）
        quality_row = tk.Frame(quality_frame, bg="#2f4153")
        quality_row.grid(row=1, column=0, sticky="ew")

        rb_style = {
            "bg": "#2f4153",
            "fg": "#ecf0f1",
            "activebackground": "#2f4153",
            "activeforeground": "#ecf0f1",
            "selectcolor": "#34495e",
            "font": ("Microsoft YaHei", 9),
            "padx": 6,
        }
        tk.Radiobutton(quality_row, text="高", variable=self.quality_var, value="高", **rb_style).pack(
            side=tk.LEFT
        )
        tk.Radiobutton(quality_row, text="中", variable=self.quality_var, value="中", **rb_style).pack(
            side=tk.LEFT
        )
        tk.Radiobutton(quality_row, text="低", variable=self.quality_var, value="低", **rb_style).pack(
            side=tk.LEFT
        )

        # 保存目录
        path_frame = tk.Frame(settings_inner, bg="#2f4153")
        path_frame.pack(pady=(6, 0), fill=tk.X)
        path_frame.grid_columnconfigure(0, weight=1)

        tk.Label(
            path_frame,
            text="保存到（会再自动创建一个以当前时间为名的文件夹）",
            fg="#aeb9c5",
            bg="#2f4153",
            font=("Microsoft YaHei", 9),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        path_row = tk.Frame(path_frame, bg="#2f4153")
        path_row.grid(row=1, column=0, sticky="ew")
        path_row.grid_columnconfigure(0, weight=1)

        self.output_entry = tk.Entry(
            path_row,
            textvariable=self.output_dir_var,
            state="readonly",
            readonlybackground="#34495e",
            fg="#ecf0f1",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#3a5166",
            highlightcolor="#3a5166",
        )
        self.output_entry.grid(row=0, column=0, sticky="ew", ipady=5)

        self.browse_btn = tk.Button(
            path_row,
            text="浏览…",
            command=self.choose_output_dir,
            bg="#3d566e",
            fg="white",
            font=("Microsoft YaHei", 9),
            relief="flat",
            padx=10,
        )
        self.browse_btn.grid(row=0, column=1, padx=(10, 0), ipady=1)

        # 智能缩放记录开关（鼠标 / 键盘）
        self.zoom_cb = tk.Checkbutton(
            settings_inner,
            text="开启智能缩放记录（鼠标 / 键盘）",
            variable=self.enable_zoom_record,
            bg="#2f4153",
            fg="#c7d2df",
            selectcolor="#2f4153",
            activebackground="#2f4153",
            activeforeground="white",
            font=("Microsoft YaHei", 8),
            anchor="w",
        )
        self.zoom_cb.pack(fill=tk.X, pady=(8, 0))


        # 按钮（同宽）
        btn_frame = tk.Frame(self.main_frame, bg="#2c3e50")
        btn_frame.pack(padx=18, fill=tk.X)

        self.start_btn = tk.Button(
            btn_frame,
            text="🎬 开始录制",
            command=self.start_countdown,
            bg="#2ecc71",
            fg="white",
            font=("Microsoft YaHei", 10, "bold"),
            height=2,
            relief="flat",
        )
        self.start_btn.pack(fill=tk.X, pady=(2, 8))

        # ---- 录制中悬浮圆形按钮 ----
        self.mini_frame = tk.Frame(self.root, bg=self._transparent_key, cursor="hand2")
        self.mini_canvas = tk.Canvas(
            self.mini_frame,
            width=self.mini_size,
            height=self.mini_size,
            bg=self._transparent_key,
            highlightthickness=0,
            bd=0,
        )
        self.mini_canvas.pack(fill=tk.BOTH, expand=True)

        pad = 2
        self.mini_canvas.create_oval(
            pad,
            pad,
            self.mini_size - pad,
            self.mini_size - pad,
            fill="#e74c3c",
            outline="",
        )
        dot_r = 2
        cx = self.mini_size // 2
        cy = self.mini_size // 2
        self.mini_canvas.create_oval(
            cx - dot_r,
            cy - dot_r,
            cx + dot_r,
            cy + dot_r,
            fill="white",
            outline="",
        )

        self._mini_dragging = False
        self._mini_press_xy = (0, 0)
        self._mini_drag_threshold = 4

        def _on_press(event):
            self._mini_dragging = False
            self._mini_press_xy = (event.x, event.y)

        def _on_motion(event):
            dx = abs(event.x - self._mini_press_xy[0])
            dy = abs(event.y - self._mini_press_xy[1])
            if dx >= self._mini_drag_threshold or dy >= self._mini_drag_threshold:
                self._mini_dragging = True
            self.drag_window(event)

        def _on_release(_event):
            if not self._mini_dragging:
                self.stop_recording()

        for w in (self.mini_frame, self.mini_canvas):
            w.bind("<ButtonPress-1>", _on_press)
            w.bind("<B1-Motion>", _on_motion)
            w.bind("<ButtonRelease-1>", _on_release)

        self.mini_frame.pack_forget()
        # 首次启动枚举若失败：等主界面控件创建完成后再弹诊断（否则用户只会看到空下拉框）
        try:
            self.root.after(0, self._notify_audio_enum_failure_if_needed)
        except Exception:
            pass
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- UI helpers ----------
    def _init_ttk_style(self):
        try:
            style = ttk.Style(self.root)
            try:
                style.theme_use("clam")
            except Exception:
                pass

            style.configure(
                "JY.TCombobox",
                fieldbackground="#34495e",
                background="#34495e",
                foreground="#ecf0f1",
                arrowcolor="#ecf0f1",
                bordercolor="#3a5166",
                lightcolor="#3a5166",
                darkcolor="#3a5166",
                padding=(10, 6, 10, 6),
            )
            style.map(
                "JY.TCombobox",
                fieldbackground=[("readonly", "#34495e"), ("disabled", "#2c3e50")],
                foreground=[("readonly", "#ecf0f1"), ("disabled", "#bdc3c7")],
                background=[("readonly", "#34495e"), ("active", "#3d566e")],
            )
        except Exception:
            pass

    def _short_path(self, path: str, max_len: int = 34) -> str:
        p = os.path.abspath(path)
        if len(p) <= max_len:
            return p
        return f"{p[:18]}...{p[-12:]}"

    def _get_app_dir(self) -> str:
        """
        返回应用目录：
        - 打包 exe：sys.executable 所在目录
        - 源码运行：当前脚本所在目录
        """
        try:
            if getattr(sys, "frozen", False):
                return os.path.dirname(os.path.abspath(sys.executable))
        except Exception:
            pass
        return os.path.dirname(os.path.abspath(__file__))

    def _setup_logging(self) -> None:
        """
        将运行日志写入 exe 同级 logs/ 目录，便于用户排障。
        """
        try:
            log_path = os.path.join(self.logs_dir, "app.log")
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(levelname)s] %(message)s",
                handlers=[
                    logging.FileHandler(log_path, encoding="utf-8"),
                ],
            )
            logging.info("app started")
        except Exception:
            pass

    def open_ffmpeg_download(self):
        """
        打开 FFmpeg 官方下载索引页（汇总 Windows 常用预编译来源，避免单一镜像失效）。
        """
        # 官方页面同时列出 BtbN、gyan.dev 等 Windows 构建入口，比直连单个第三方站点更稳
        url = "https://ffmpeg.org/download.html"
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def _notify_ffmpeg_missing(self):
        """
        未检测到 FFmpeg 时的提示：给出可点击下载入口。
        """
        url = "https://ffmpeg.org/download.html"
        msg = (
            "当前启动环境未检测到 ffmpeg。\n\n"
            "你可以：\n"
            "1) 点击“选择…”指定 ffmpeg.exe\n"
            "2) 或点击“下载FFmpeg”打开 FFmpeg 官方下载页（含 Windows 预编译链接）后再试\n\n"
            f"下载页：{url}"
        )
        try:
            messagebox.showwarning("未找到 FFmpeg", msg)
        except Exception:
            pass
        logging.warning("ffmpeg not found; user should download or select ffmpeg.exe")

    def _refresh_info_label(self):
        audio_enabled = bool((self.audio_var.get() or "").strip())
        self.info_label.config(
            text=f"麦克风录音：{'已开启' if audio_enabled else '已禁用'}  ·  保存至：{self._short_path(self.output_dir)}/"
        )

    def _format_audio_enum_detail(self, max_len: int = 1600) -> str:
        detail = (self._last_audio_enum_log or "").strip()
        if not detail:
            return ""
        if len(detail) > max_len:
            return detail[-max_len:]
        return detail

    def _notify_audio_enum_failure_if_needed(self):
        """
        当麦克风列表为空但 ffmpeg 已输出诊断信息时，向用户展示 stderr（节选）。

        说明：这不是“猜测修复”，而是把组件边界（ffmpeg 设备枚举）证据直接暴露出来，
        便于区分：路径错误 / dshow 不可用 / WASAPI 回退是否成功 / 系统隐私或策略拦截等。
        """
        if sys.platform != "win32":
            return
        if self.audio_devices:
            return
        detail = self._format_audio_enum_detail()
        if not detail:
            return
        extra = ""
        low = detail.lower()
        if "could not enumerate" in low:
            extra = (
                "\n\n【判读提示】日志中的 “Could not enumerate …” 通常表示 DirectShow（dshow）在该会话无法枚举硬件。"
                "本程序已自动尝试 WASAPI / OpenAL（若你的 ffmpeg 编译包含这些输入）。若仍为空，请检查："
                "Windows「设置 → 隐私 → 麦克风」、音频服务、声卡驱动；并尽量使用 FFmpeg 官方下载页推荐的完整构建（full / essentials）。"
            )
        messagebox.showerror(
            "麦克风枚举失败",
            "未能枚举到任何音频输入设备。\n\n"
            "这通常不是“没有麦克风”，而是 FFmpeg 在设备枚举阶段失败，或系统策略阻止访问。\n\n"
            "【FFmpeg 输出（节选）】\n"
            f"{detail}"
            f"{extra}",
        )

    # ---------- Config ----------
    def load_config(self):
        # 说明：高 DPI / 字体放大时，340px 高度会把底部按钮挤出可视区
        default_geo = "560x460"
        min_w, min_h = 520, 440
        try:
            self.root.minsize(min_w, min_h)
        except Exception:
            pass

        loaded_geo = None
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f) or {}
                loaded_geo = (config.get("window_pos") or "").strip() or None
                saved_dir = (config.get("output_dir") or "").strip()
                if saved_dir:
                    self.output_dir = os.path.abspath(saved_dir)
                    os.makedirs(self.output_dir, exist_ok=True)
                saved_ffmpeg = (config.get("ffmpeg_path") or "").strip()
                if saved_ffmpeg:
                    # 远程/换机场景：配置里可能残留另一台机器的路径
                    if os.path.exists(saved_ffmpeg):
                        self.ffmpeg_path = saved_ffmpeg
                    else:
                        self.ffmpeg_path = ""
                saved_py = (config.get("python_path") or "").strip()
                if saved_py and os.path.exists(saved_py):
                    self.python_path = saved_py
                saved_wrapper = (config.get("jy_wrapper_path") or "").strip()
                if saved_wrapper and os.path.exists(saved_wrapper):
                    self.jy_wrapper_path = saved_wrapper
                saved_quality = (config.get("quality") or "").strip()
                if saved_quality in ("高", "中", "低"):
                    self.quality_level = saved_quality
            except Exception:
                pass

        geo = loaded_geo or default_geo
        try:
            m = re.match(r"^(?P<w>\d+)x(?P<h>\d+)(?P<xy>\+\d+\+\d+)?$", str(geo).strip())
            if m:
                w = max(int(m.group("w")), min_w)
                h = max(int(m.group("h")), min_h)
                xy = m.group("xy") or ""
                geo = f"{w}x{h}{xy}"
        except Exception:
            geo = default_geo

        self.root.geometry(geo)

    def on_close(self):
        try:
            geo = self.root.geometry()
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "window_pos": geo,
                        "output_dir": self.output_dir,
                        "ffmpeg_path": self.ffmpeg_path,
                        "python_path": self.python_path,
                        "jy_wrapper_path": self.jy_wrapper_path,
                        "quality": (self.quality_var.get() if hasattr(self, "quality_var") else self.quality_level),
                    },
                    f,
                    ensure_ascii=False,
                )
        except Exception:
            pass
        self.root.destroy()

    # ---------- Actions ----------
    def choose_output_dir(self):
        if self.is_recording:
            messagebox.showwarning("录制中", "录制进行中无法修改保存目录，请停止后再修改。")
            return
        selected = filedialog.askdirectory(title="选择保存目录", initialdir=self.output_dir, mustexist=True)
        if not selected:
            return
        self.output_dir = os.path.abspath(selected)
        os.makedirs(self.output_dir, exist_ok=True)
        self.output_dir_var.set(self.output_dir)
        self._refresh_info_label()

    def _resolve_ffmpeg_exe(self) -> str:
        """
        解析可用的 ffmpeg 可执行文件路径。
        优先级：配置里的 ffmpeg_path -> PATH 中的 ffmpeg -> 空
        """
        if self.ffmpeg_path and os.path.exists(self.ffmpeg_path):
            return self.ffmpeg_path
        # 配置路径失效：清理，避免后续一直走错误路径
        if self.ffmpeg_path and not os.path.exists(self.ffmpeg_path):
            self.ffmpeg_path = ""
            try:
                self.ffmpeg_var.set("")
            except Exception:
                pass
        found = shutil.which("ffmpeg")
        if found:
            self.ffmpeg_path = found
            self.ffmpeg_var.set(found)
            return found
        return ""

    def choose_ffmpeg_exe(self):
        if self.is_recording:
            messagebox.showwarning("录制中", "录制进行中无法修改 FFmpeg 路径，请停止后再修改。")
            return
        initial_dir = os.path.dirname(self.ffmpeg_path) if self.ffmpeg_path else os.getcwd()
        selected = filedialog.askopenfilename(
            title="选择 ffmpeg.exe",
            initialdir=initial_dir,
            filetypes=[("ffmpeg.exe", "ffmpeg.exe"), ("可执行文件", "*.exe"), ("所有文件", "*.*")],
        )
        if not selected:
            return
        self.ffmpeg_path = os.path.abspath(selected)
        self.ffmpeg_var.set(self.ffmpeg_path)
        # 选择后立即刷新设备
        self.reload_audio_devices()

    def reload_audio_devices(self):
        """重新枚举麦克风设备（用于修复 PATH/ffmpeg 变化）。"""
        if sys.platform != "win32":
            return
        if not self._resolve_ffmpeg_exe():
            messagebox.showwarning(
                "未找到 FFmpeg",
                "仍然无法找到 ffmpeg。\n请在“FFmpeg”处选择 ffmpeg.exe，或把 ffmpeg 加入系统 PATH。",
            )
            self.audio_devices, self.audio_route = [], {}
        else:
            self._enumerate_audio_inputs()

        self.audio_combo["values"] = self.audio_devices
        if self.audio_devices:
            self.audio_var.set(self.audio_devices[0])
        else:
            self.audio_var.set("")
        self._refresh_info_label()

        # 仍然没有设备：把 ffmpeg 枚举日志展示出来（远程排障关键）
        self._notify_audio_enum_failure_if_needed()

    def start_countdown(self):
        self.start_btn.config(state=tk.DISABLED)
        for i in range(3, 0, -1):
            self.status_label.config(text=f"即将开始（{i}）...", fg="#f1c40f")
            self.root.update()
            time.sleep(1)
        self.start_recording()

    def start_recording(self):
        # 每次录制：在用户选择的目录下创建一个时间文件夹
        folder_ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        self.active_output_dir = os.path.join(self.output_dir, folder_ts)
        os.makedirs(self.active_output_dir, exist_ok=True)

        ts = time.strftime("%Y%m%d_%H%M%S")
        self.output_path = os.path.join(self.active_output_dir, f"recording_{ts}.mp4")
        self.log_file = os.path.join(self.active_output_dir, "ffmpeg_log.txt")
        self.events_path = os.path.join(self.active_output_dir, f"recording_{ts}_events.json")

        self.is_recording = True
        self.status_label.config(text="录制中…（轻点红点停止）", fg="#e67e22")
        logging.info("start recording: %s", self.output_path)

        self.main_frame.pack_forget()
        self.mini_frame.pack(fill=tk.BOTH, expand=True)
        self.root.overrideredirect(True)

        if sys.platform == "win32":
            try:
                self.root.configure(bg=self._transparent_key)
                self.root.wm_attributes("-transparentcolor", self._transparent_key)
            except Exception:
                pass

        old_geo = self.root.geometry()
        parts = old_geo.split("+")
        if len(parts) >= 3:
            self.root.geometry(f"{self.mini_size}x{self.mini_size}+{parts[1]}+{parts[2]}")
        else:
            self.root.geometry(f"{self.mini_size}x{self.mini_size}")

        # 启动鼠标/键盘监听（用于智能缩放记录）
        if self.enable_zoom_record.get():
            self.start_time = time.time()
            with self._events_lock:
                self.events = []
            self._last_move_time = 0.0
            self._last_move_pos = (0, 0)
            self._start_event_listeners()

        threading.Thread(target=self.run_ffmpeg, daemon=True).start()

    # ---------- 智能缩放事件采集（鼠标/键盘） ----------
    def _events_enabled(self) -> bool:
        return bool(self.is_recording and self.enable_zoom_record.get() and _PYNPUT_OK)

    def _event_time(self) -> float:
        return round(max(0.0, time.time() - float(self.start_time or 0.0)), 3)

    def _norm_xy(self, x: int, y: int) -> tuple[float, float]:
        w = int(self.screen_width or 1)
        h = int(self.screen_height or 1)
        nx = x / w
        ny = y / h
        # 防御：在 DPI 缩放/多显示器场景，pynput 坐标可能与 Tk 屏幕尺寸口径不同，导致归一化越界
        nx = 0.0 if nx < 0.0 else (1.0 if nx > 1.0 else nx)
        ny = 0.0 if ny < 0.0 else (1.0 if ny > 1.0 else ny)
        return round(nx, 4), round(ny, 4)

    def on_click(self, x, y, _button, pressed):
        # 仅记录按下（与原版一致：一次点击只记一条）
        if not pressed or not self._events_enabled():
            return
        try:
            nx, ny = self._norm_xy(int(x), int(y))
            payload = {"type": "click", "time": self._event_time(), "x": nx, "y": ny}
            with self._events_lock:
                self.events.append(payload)
        except Exception:
            pass

    def on_move(self, x, y):
        # 采样节流：10FPS + 位移阈值 5px，避免文件过大
        if not self._events_enabled():
            return
        try:
            now = time.time()
            if (now - float(self._last_move_time or 0.0)) <= 0.1:
                return
            lx, ly = self._last_move_pos if isinstance(self._last_move_pos, tuple) else (0, 0)
            dx = int(x) - int(lx)
            dy = int(y) - int(ly)
            if dx * dx + dy * dy <= 25:
                return
            nx, ny = self._norm_xy(int(x), int(y))
            payload = {"type": "move", "time": self._event_time(), "x": nx, "y": ny}
            with self._events_lock:
                self.events.append(payload)
            self._last_move_time = now
            self._last_move_pos = (int(x), int(y))
        except Exception:
            pass

    def on_press(self, _key):
        if not self._events_enabled():
            return
        try:
            # 记录按键类型，供 smart_zoomer 做“文本输入”判定
            key_str = ""
            try:
                key_str = getattr(_key, "char", None) or ""
            except Exception:
                key_str = ""
            if not key_str:
                try:
                    key_str = str(_key)
                except Exception:
                    key_str = ""

            payload = {"type": "keypress", "time": self._event_time(), "key": key_str}
            with self._events_lock:
                self.events.append(payload)
        except Exception:
            pass

    def _start_event_listeners(self):
        if not _PYNPUT_OK:
            return
        try:
            self.m_listener = _pynput_mouse.Listener(on_click=self.on_click, on_move=self.on_move)
            self.k_listener = _pynput_keyboard.Listener(on_press=self.on_press)
            self.m_listener.start()
            self.k_listener.start()
        except Exception:
            self.m_listener = None
            self.k_listener = None

    def _stop_event_listeners(self):
        try:
            if self.m_listener:
                self.m_listener.stop()
        except Exception:
            pass
        try:
            if self.k_listener:
                self.k_listener.stop()
        except Exception:
            pass
        self.m_listener = None
        self.k_listener = None

    def stop_recording(self):
        if not self.is_recording:
            return
        self.is_recording = False

        # 先停监听，避免收尾阶段继续写 events
        self._stop_event_listeners()

        def _wait_file_stable(path: str, timeout_s: float = 12.0, stable_rounds: int = 3, interval_s: float = 0.2) -> bool:
            """
            等待输出文件写入稳定，避免 MP4 尾部索引尚未落盘导致“最后几秒像没录上/无法拖动”。
            """
            deadline = time.time() + timeout_s
            last_size = -1
            stable = 0
            while time.time() < deadline:
                try:
                    if not path or not os.path.exists(path):
                        time.sleep(interval_s)
                        continue
                    size = os.path.getsize(path)
                    if size > 0 and size == last_size:
                        stable += 1
                        if stable >= stable_rounds:
                            return True
                    else:
                        stable = 0
                        last_size = size
                except Exception:
                    pass
                time.sleep(interval_s)
            return bool(path and os.path.exists(path) and os.path.getsize(path) > 0)

        try:
            if self.process and self.process.poll() is None:
                # 给 ffmpeg 一点时间把缓冲刷出，再发退出信号
                time.sleep(0.35)
                try:
                    if self.process.stdin:
                        self.process.stdin.write(b"q")
                        self.process.stdin.flush()
                except Exception:
                    # stdin 可能不可写，退回 terminate
                    try:
                        self.process.terminate()
                    except Exception:
                        pass

                # 关键：不要 5 秒就 kill。MP4 收尾写入可能需要更久，否则会“掐掉尾巴”
                try:
                    self.process.wait(timeout=20)
                except Exception:
                    try:
                        self.process.terminate()
                    except Exception:
                        pass
                    try:
                        self.process.wait(timeout=5)
                    except Exception:
                        pass
        except Exception:
            try:
                if self.process:
                    self.process.kill()
            except Exception:
                pass

        # 恢复 UI
        self.root.overrideredirect(False)
        if sys.platform == "win32":
            try:
                self.root.wm_attributes("-transparentcolor", "")
                self.root.configure(bg="#2c3e50")
            except Exception:
                pass

        self.mini_frame.pack_forget()
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.start_btn.config(state=tk.NORMAL)

        # 等待文件稳定再判定成功，避免“最后几秒未写完就去导入/播放”
        _wait_file_stable(self.output_path, timeout_s=12.0)
        ok = os.path.exists(self.output_path) and os.path.getsize(self.output_path) > 100
        if ok:
            # 写入 events.json（供 smart_zoomer 使用；顶层必须是列表）
            try:
                if self.events_path:
                    with open(self.events_path, "w", encoding="utf-8") as f:
                        with self._events_lock:
                            data = list(self.events or [])
                        json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            self.status_label.config(text="已保存", fg="#2ecc71")
            self._post_dialog()
            logging.info("recording saved: %s", self.output_path)
        else:
            self.status_label.config(text="录制失败", fg="#e74c3c")
            messagebox.showerror("录制失败", "FFmpeg 未能生成有效的视频文件。请检查麦克风或 FFmpeg 设置。")
            logging.error("recording failed: %s", self.output_path)

    def _post_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("录制完成")
        dialog.geometry("380x280")
        dialog.configure(bg="#2c3e50")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.transient(self.root)

        self.root.update_idletasks()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        dialog.geometry(f"380x280+{x}+{y}")
        dialog.focus_force()
        dialog.grab_set()

        tk.Label(
            dialog,
            text="✅ 视频已保存",
            fg="#ecf0f1",
            bg="#2c3e50",
            font=("Microsoft YaHei", 12, "bold"),
        ).pack(pady=(18, 10))

        tk.Label(
            dialog,
            text=os.path.basename(self.output_path),
            fg="#bdc3c7",
            bg="#2c3e50",
            font=("Microsoft YaHei", 9),
        ).pack(pady=(0, 10))

        def _locate_jy_wrapper() -> tuple[str, str]:
            """
            尝试定位主仓库的 jy_wrapper.py。

            返回：(python_exe, jy_wrapper_path)，找不到则返回空字符串。
            """
            # 0) 打包版：优先使用内置 jy_skill（零操作）
            try:
                meipass = getattr(sys, "_MEIPASS", "")
            except Exception:
                meipass = ""

            if meipass:
                embedded_root = os.path.join(str(meipass), "jy_skill")
                embedded_wrapper = os.path.join(embedded_root, "scripts", "jy_wrapper.py")
                if os.path.exists(embedded_wrapper):
                    # 让 scripts/utils/skill_path.py 能正确解析到 “<root>/scripts/jy_wrapper.py”
                    os.environ["JY_SKILL_ROOT"] = embedded_root
                    # 内置脚本使用 vendored 依赖：jy_skill/scripts + jy_skill/scripts/vendor
                    scripts_dir = os.path.join(embedded_root, "scripts")
                    vendor_dir = os.path.join(scripts_dir, "vendor")
                    if scripts_dir not in sys.path:
                        sys.path.insert(0, scripts_dir)
                    if vendor_dir not in sys.path:
                        sys.path.insert(0, vendor_dir)

                    # 内置导入不需要外部 python.exe
                    return "", embedded_wrapper

            # 1) 优先使用配置（用户手选）
            py = (self.python_path or "").strip() or (shutil.which("python") or "")
            wrapper = (self.jy_wrapper_path or "").strip()
            if py and wrapper and os.path.exists(py) and os.path.exists(wrapper):
                return py, wrapper

            # 2) 尝试环境变量
            env_py = (os.environ.get("JY_PYTHON") or "").strip()
            env_wrapper = (os.environ.get("JY_WRAPPER_PATH") or "").strip()
            if env_py and env_wrapper and os.path.exists(env_py) and os.path.exists(env_wrapper):
                self.python_path = env_py
                self.jy_wrapper_path = env_wrapper
                return env_py, env_wrapper

            # 3) 尝试相对路径（开发态/仓库态）
            base = Path(__file__).resolve().parent
            candidates = [
                (base.parent / "scripts" / "jy_wrapper.py"),
                (base / "scripts" / "jy_wrapper.py"),  # 若用户把 scripts 目录拷到 exe 同级
                (base.parent.parent / "scripts" / "jy_wrapper.py"),
            ]
            for c in candidates:
                try:
                    if c.exists() and py:
                        self.jy_wrapper_path = str(c.resolve())
                        return py, self.jy_wrapper_path
                except Exception:
                    continue

            return "", ""

        def import_to_jianying():
            py, wrapper = _locate_jy_wrapper()
            if not wrapper:
                # 交互式补全：让用户选择 python.exe 与 jy_wrapper.py
                messagebox.showwarning(
                    "需要补全依赖",
                    "“保存到剪映草稿”需要：\n"
                    "1) 目标机器有 Python（python.exe）\n"
                    "2) 有剪映脚本 `scripts/jy_wrapper.py`（来自仓库）\n\n"
                    "接下来会依次让你选择 python.exe 和 jy_wrapper.py。",
                )

                if not py:
                    picked_py = filedialog.askopenfilename(
                        title="选择 python.exe（用于调用 jy_wrapper）",
                        filetypes=[("python.exe", "python.exe"), ("可执行文件", "*.exe"), ("所有文件", "*.*")],
                    )
                    if picked_py:
                        self.python_path = os.path.abspath(picked_py)
                        py = self.python_path

                if not wrapper:
                    picked_wrapper = filedialog.askopenfilename(
                        title="选择 jy_wrapper.py（通常在仓库 scripts/jy_wrapper.py）",
                        filetypes=[("jy_wrapper.py", "jy_wrapper.py"), ("Python 文件", "*.py"), ("所有文件", "*.*")],
                    )
                    if picked_wrapper:
                        self.jy_wrapper_path = os.path.abspath(picked_wrapper)
                        wrapper = self.jy_wrapper_path

                if not wrapper or not py:
                    return

            def _ensure_skill_paths(wrapper_path: str) -> None:
                """
                确保剪映技能脚本在源码运行时可被 import：
                - scripts/ 下的 jy_wrapper.py、smart_zoomer.py
                - scripts/vendor/ 下 vendored 的 pyJianYingDraft 等
                """
                try:
                    wp = Path(wrapper_path).resolve()
                    # wrapper 通常位于 <root>/scripts/jy_wrapper.py
                    root = wp.parent.parent if wp.name.lower() == "jy_wrapper.py" else Path(__file__).resolve().parent
                    scripts_dir = root / "scripts"
                    vendor_dir = scripts_dir / "vendor"

                    if scripts_dir.exists():
                        os.environ.setdefault("JY_SKILL_ROOT", str(root))
                        s = str(scripts_dir)
                        if s not in sys.path:
                            sys.path.insert(0, s)
                    if vendor_dir.exists():
                        v = str(vendor_dir)
                        if v not in sys.path:
                            sys.path.insert(0, v)
                except Exception:
                    # 兜底：不阻断导入流程，后续自检会给出缺失项
                    pass

            def _dependency_self_check() -> list[str]:
                """
                依赖自检（一次性列出缺失项，避免“点一次缺一个库”的循环）。

                说明：
                - 标准库也可能因 PyInstaller 依赖分析不足而漏打包（例如 asyncio/difflib）。
                - 第三方依赖来自 pyJianYingDraft（如 pymediainfo、uiautomation、comtypes、win32ctypes）。
                """
                import importlib

                missing: list[str] = []
                # 源码运行时：先把 ./scripts 与 ./scripts/vendor 加入 sys.path
                _ensure_skill_paths(wrapper)
                modules = [
                    # 标准库（理论上应存在，但为防打包漏掉）
                    "asyncio",
                    "difflib",
                    "uuid",
                    "json",
                    "argparse",
                    # 剪映导入链路
                    "pyJianYingDraft",
                    "pymediainfo",
                    "uiautomation",
                    "comtypes",
                    "win32ctypes",
                    # 我们的脚本入口（内置模式需要）
                    "jy_wrapper",
                    "smart_zoomer",
                ]

                for m in modules:
                    try:
                        importlib.import_module(m)
                    except Exception:
                        missing.append(m)

                # 额外检查：pyJianYingDraft 模板资源是否存在（打包时常见漏项）
                try:
                    import pyJianYingDraft.assets as _assets  # type: ignore

                    meta = _assets.get_asset_path("DRAFT_META_TEMPLATE")
                    content = _assets.get_asset_path("DRAFT_CONTENT_TEMPLATE")
                    if not meta.exists():
                        missing.append("pyJianYingDraft.assets:draft_meta_info.json")
                    if not content.exists():
                        missing.append("pyJianYingDraft.assets:draft_content_template.json")
                except Exception:
                    missing.append("pyJianYingDraft.assets:(templates)")

                return missing

            # 生成草稿名：不要中文，避免路径/编码/兼容性问题
            name = f"rec_{time.strftime('%Y%m%d_%H%M%S')}"
            video = os.path.abspath(self.output_path)
            events = os.path.abspath(self.events_path) if self.events_path else ""
            if not events or not os.path.exists(events):
                # 最后兜底：写一个空 json
                events = os.path.join(os.path.dirname(video), "recording_events.json")
                try:
                    with open(events, "w", encoding="utf-8") as f:
                        json.dump([], f, ensure_ascii=False)
                except Exception:
                    pass

            def _run():
                try:
                    missing = _dependency_self_check()
                    if missing:
                        messagebox.showerror(
                            "依赖自检失败",
                            "检测到以下依赖缺失或不可用：\n\n- "
                            + "\n- ".join(missing)
                            + "\n\n请使用最新打包版本（我已在构建中强制打包这些依赖）；"
                            "若你是手动运行源码，请先安装相应依赖后再试。",
                        )
                        return
                    # 打包版：优先“内置导入”（不依赖外部 python.exe）
                    if not py:
                        import importlib
                        import importlib.util

                        # 强制覆盖 smart_zoomer：避免打包时 scripts 内同名文件未被覆盖
                        try:
                            meipass = getattr(sys, "_MEIPASS", "")
                        except Exception:
                            meipass = ""
                        if meipass:
                            override_path = os.path.join(str(meipass), "jy_skill", "overrides", "smart_zoomer.py")
                            if os.path.exists(override_path):
                                spec = importlib.util.spec_from_file_location("smart_zoomer", override_path)
                                if spec and spec.loader:
                                    mod = importlib.util.module_from_spec(spec)
                                    spec.loader.exec_module(mod)
                                    sys.modules["smart_zoomer"] = mod

                        jy = importlib.import_module("jy_wrapper")
                        cmd_apply_zoom = getattr(jy, "cmd_apply_zoom", None)
                        if not callable(cmd_apply_zoom):
                            raise RuntimeError("jy_wrapper.cmd_apply_zoom 不可用")

                        class _NS:
                            pass

                        ns = _NS()
                        ns.name = name
                        ns.video = video
                        ns.json = events
                        # 默认 150：100 等于不放大
                        ns.scale = 150
                        ns.projects_root = ""
                        ns.no_overwrite = False

                        # 捕获 RESULT_JSON（脚本用 print 输出）
                        import io
                        import contextlib

                        buf = io.StringIO()
                        with contextlib.redirect_stdout(buf):
                            rc = cmd_apply_zoom(ns)
                        out = buf.getvalue() + f"\n[exit_code]{rc}\n"
                    else:
                        # 外部 python 路径模式：调用脚本
                        cmd = [
                            py,
                            wrapper,
                            "apply-zoom",
                            "--name",
                            name,
                            "--video",
                            video,
                            "--json",
                            events,
                            "--scale",
                            "150",
                        ]
                        # Windows 终端默认可能是 GBK；强制子进程用 UTF-8，避免脚本输出包含特殊字符时报错
                        env = os.environ.copy()
                        env["PYTHONIOENCODING"] = "utf-8"
                        env["PYTHONUTF8"] = "1"
                        proc = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="ignore",
                            timeout=120,
                            env=env,
                        )
                        out = (proc.stdout or "") + "\n" + (proc.stderr or "")

                    # 尝试解析 RESULT_JSON
                    m = re.search(r"RESULT_JSON:\s*(\{.*\})", out)
                    if m:
                        try:
                            payload = json.loads(m.group(1))
                            if payload.get("status") == "SUCCESS":
                                draft_path = payload.get("draft_path") or ""
                                messagebox.showinfo("导入成功", f"已生成剪映草稿：\n{draft_path}")
                                return
                            messagebox.showerror("导入失败", payload.get("message") or out[-800:])
                            return
                        except Exception:
                            pass

                    messagebox.showerror("导入失败", out[-1200:] if out else "未知错误：未获得脚本输出。")
                except Exception as e:
                    messagebox.showerror("导入失败", f"{e}")

            threading.Thread(target=_run, daemon=True).start()

        def open_folder():
            os.startfile(self.output_dir)
            try:
                dialog.lift()
                dialog.focus_force()
            except Exception:
                pass

        # 导入剪映：按钮永远展示（打包版也展示），缺依赖时点击会引导选择路径
        tk.Button(
            dialog,
            text="🎞️ 保存到剪映草稿",
            command=import_to_jianying,
            bg="#3498db",
            fg="white",
            font=("Microsoft YaHei", 10, "bold"),
            width=18,
            relief="flat",
        ).pack(pady=(2, 6))

        tk.Button(
            dialog,
            text="📂 打开文件位置",
            command=open_folder,
            bg="#95a5a6",
            fg="white",
            font=("Microsoft YaHei", 10),
            width=18,
            relief="flat",
        ).pack(pady=6)

        tk.Button(
            dialog,
            text="关闭",
            command=dialog.destroy,
            bg="#34495e",
            fg="white",
            font=("Microsoft YaHei", 10),
            width=18,
            relief="flat",
        ).pack(pady=6)

    # ---------- FFmpeg ----------
    def run_ffmpeg(self):
        ffmpeg_exe = self._resolve_ffmpeg_exe() or "ffmpeg"
        cmd = [ffmpeg_exe, "-y", "-f", "gdigrab", "-framerate", "30", "-i", "desktop"]

        # 清晰度映射：高更清晰但更吃 CPU/更大文件；低更省资源但更糊
        q = (self.quality_var.get() or "中").strip()
        if q == "高":
            preset, crf = "slow", "18"
        elif q == "低":
            preset, crf = "veryfast", "23"
        else:
            preset, crf = "medium", "20"

        selected_audio = (self.audio_var.get() or "").strip()
        if selected_audio:
            route = self.audio_route.get(selected_audio) or {}
            fmt = (route.get("fmt") or "dshow").strip()
            iarg = (route.get("iarg") or "").strip()
            if not iarg:
                # 极端情况：路由表缺失时退回 dshow（与旧逻辑一致）
                iarg = f"audio={selected_audio}"
                fmt = "dshow"
            cmd.extend(["-thread_queue_size", "1024", "-f", fmt, "-i", iarg])
            cmd.extend(["-map", "0:v:0", "-map", "1:a:0"])
            # 关键：不要使用 -shortest。
            # 原因：在某些机器/驱动/ffmpeg 构建下，音频流会比视频更早结束（或先进入 EOF），
            # -shortest 会直接按“更短的那路”裁切输出，从而表现为“每次最后几秒没录上”。
            cmd.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    preset,
                    "-pix_fmt",
                    "yuv420p",
                    "-crf",
                    crf,
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                ]
            )
        else:
            cmd.extend(["-c:v", "libx264", "-preset", preset, "-pix_fmt", "yuv420p", "-crf", crf])

        # 让 MP4 索引更快可用（不影响时长，但提升兼容性）
        cmd.extend(["-movflags", "+faststart"])

        cmd.append(self.output_path)

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        with open(self.log_file, "w", encoding="utf-8") as f:
            popen_kwargs = {}
            if sys.platform == "win32":
                # Windows：隐藏 ffmpeg 的控制台窗口，避免弹出 cmd 黑窗
                try:
                    popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    si.wShowWindow = 0
                    popen_kwargs["startupinfo"] = si
                except Exception:
                    pass
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=f,
                stderr=subprocess.STDOUT,
                env=env,
                **popen_kwargs,
            )
            self.process.wait()

    def _list_devices_text(self, ffmpeg_exe: str, fmt: str) -> str:
        """调用 ffmpeg 列出指定输入格式下的设备，返回合并后的文本（stderr+stdout）。"""
        try:
            proc = subprocess.run(
                [ffmpeg_exe, "-hide_banner", "-nostdin", "-list_devices", "true", "-f", fmt, "-i", "dummy"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=8,
            )
            return (proc.stderr or "") + "\n" + (proc.stdout or "")
        except Exception as e:
            return f"[list_devices 异常] fmt={fmt!r}: {e}\n"

    def _ffmpeg_supports_input_format(self, ffmpeg_exe: str, fmt: str) -> bool:
        """检测当前 ffmpeg 是否编译了该输入设备（避免在旧构建上反复报错）。"""
        txt = self._list_devices_text(ffmpeg_exe, fmt)
        if re.search(r"Unknown input format", txt, re.I) and fmt.lower() in txt.lower():
            return False
        if re.search(r"Unknown format", txt, re.I) and fmt.lower() in txt.lower():
            return False
        return True

    def _parse_generic_capture_devices(self, text_out: str) -> tuple[list[str], dict[str, str]]:
        """
        解析 ffmpeg list_devices 的通用“引号设备名 + (类型)”行，用于 wasapi/openal 等输出。

        接受类型名中包含 audio / capture 的条目；显式排除纯 video。
        """
        devices: list[str] = []
        alt_map: dict[str, str] = {}
        last_device: str | None = None

        for line in text_out.splitlines():
            m = re.search(r'"([^"]+)"\s*\(([^)]+)\)', line)
            if m:
                name, typ_raw = m.group(1).strip(), m.group(2).strip().lower()
                if not name:
                    last_device = None
                    continue
                if "video" in typ_raw and "audio" not in typ_raw:
                    last_device = None
                    continue
                if "audio" in typ_raw or "capture" in typ_raw:
                    if name not in devices:
                        devices.append(name)
                    last_device = name
                else:
                    last_device = None
                continue

            if last_device:
                m3 = re.search(r'Alternative name\s+"(.+?)"', line, re.I)
                if m3:
                    alt_map[last_device] = m3.group(1).strip()
                    last_device = None

        return devices, alt_map

    def _enumerate_audio_inputs(self) -> None:
        """
        枚举可用麦克风输入：优先 dshow；若 DirectShow 无法列出设备则尝试 wasapi / openal。
        """
        self.audio_devices = []
        self.audio_route = {}
        ffmpeg_exe = self._resolve_ffmpeg_exe()
        if not ffmpeg_exe or sys.platform != "win32":
            self._last_audio_enum_log = ""
            return

        sections: list[str] = []

        td = self._list_devices_text(ffmpeg_exe, "dshow")
        sections.append("===== dshow (-f dshow -list_devices true -i dummy) =====\n" + td)
        dd, ad = self._parse_dshow_audio_devices(td)
        if dd:
            self.audio_devices = dd[:]
            for name in dd:
                spec = (ad.get(name, name) or name).strip()
                self.audio_route[name] = {"fmt": "dshow", "iarg": f"audio={spec}"}
            self._last_audio_enum_log = "\n\n".join(sections)
            return

        # 多数静态包里 WASAPI 输入仍不可用；gyan 等构建常带 OpenAL 采集，故先尝试 openal。
        for fmt, ui_prefix in (("openal", "[OpenAL] "), ("wasapi", "[WASAPI] ")):
            if not self._ffmpeg_supports_input_format(ffmpeg_exe, fmt):
                continue
            tx = self._list_devices_text(ffmpeg_exe, fmt)
            sections.append(f"===== {fmt} (-f {fmt} -list_devices true -i dummy) =====\n" + tx)
            devs, alts = self._parse_generic_capture_devices(tx)
            if not devs:
                continue
            for name in devs:
                label = f"{ui_prefix}{name}"
                self.audio_devices.append(label)
                spec = (alts.get(name, name) or name).strip()
                if fmt == "openal":
                    # OpenAL 输入：设备名直接作为 -i 参数（见 ffmpeg-devices 文档示例）
                    self.audio_route[label] = {"fmt": "openal", "iarg": spec}
                else:
                    # WASAPI：与 dshow 类似，使用 audio= 选择端点（具体以当前 ffmpeg 为准）
                    self.audio_route[label] = {"fmt": "wasapi", "iarg": f"audio={spec}"}

            if self.audio_devices:
                self._last_audio_enum_log = "\n\n".join(sections)
                return

        self._last_audio_enum_log = "\n\n".join(sections)

    def _parse_dshow_audio_devices(self, text_out: str) -> tuple[list[str], dict[str, str]]:
        """
        从 ffmpeg list_devices 输出解析音频设备。

        兼容多种输出形态：
        - `"Mic" (audio)`
        - ` "Mic" (audio)`
        - `Alternative name "@device_..."`
        - 旧版分段 `DirectShow audio devices`
        """
        devices: list[str] = []
        alt_map: dict[str, str] = {}
        last_device: str | None = None

        for line in text_out.splitlines():
            # 方案 A：标准行
            m = re.search(r"\"(.+?)\"\s*\(audio\)", line)
            if m:
                name = m.group(1).strip()
                if name and name not in devices:
                    devices.append(name)
                last_device = name
                continue

            # 方案 B：有些版本前面带前缀，但仍包含 (audio)
            if "(audio)" in line:
                m2 = re.search(r"\"(.+?)\"", line)
                if m2:
                    name = m2.group(1).strip()
                    if name and name not in devices:
                        devices.append(name)
                    last_device = name
                    continue

            if last_device:
                m3 = re.search(r'Alternative name\s+\"(.+?)\"', line)
                if m3:
                    alt_map[last_device] = m3.group(1).strip()
                    last_device = None

        if devices:
            return devices, alt_map

        # 方案 C：旧格式分段
        in_audio = False
        for line in text_out.splitlines():
            if "DirectShow audio devices" in line:
                in_audio = True
                continue
            if "DirectShow video devices" in line:
                in_audio = False
                continue
            if not in_audio:
                continue
            m = re.search(r"\"(.+?)\"", line)
            if m:
                name = m.group(1).strip()
                if name and name not in devices:
                    devices.append(name)
        return devices, alt_map

    # ---------- Mini window drag ----------
    def drag_window(self, event):
        half = int(self.mini_size / 2)
        x = self.root.winfo_x() + event.x - half
        y = self.root.winfo_y() + event.y - half
        self.root.geometry(f"+{x}+{y}")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    VideoRecorderApp().run()

