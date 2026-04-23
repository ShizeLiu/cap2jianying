import json
import os


def apply_smart_zoom(project, video_segment, events_json_path: str, zoom_scale=150, zoom_duration_us=500000):
    """
    输入聚焦（Typing Focus）智能变焦：

    - 不再用鼠标点击驱动镜头，避免密集点击导致“晃来晃去”
    - 仅在检测到“文本输入相关按键”时进入聚焦
    - 最后一次文本输入后静默 T=2s 自动退出聚焦
    - 聚焦开始提前 Δ=0.25s

    事件文件约定（顶层为列表）：
    - click: {"type":"click","time":..,"x":..,"y":..}
    - move:  {"type":"move","time":..,"x":..,"y":..}
    - keypress: {"type":"keypress","time":..,"key":"a"} 或 {"key":"Key.space"} 等
    """

    if not os.path.exists(events_json_path):
        print(f"Events file not found: {events_json_path}")
        return

    with open(events_json_path, "r", encoding="utf-8") as f:
        events = json.load(f) or []

    # ---- 参数（与设计稿一致，后续可做成可配置）----
    scale_val = float(zoom_scale) / 100.0
    PRE_ROLL_S = 0.25
    END_SILENCE_S = 2.0
    ZOOM_OUT_US = 600000  # 0.6s
    MOVE_LOOKBACK_S = 2.0
    MIN_UPDATE_INTERVAL_S = 0.3
    MOVE_TRIGGER_RATIO = 0.20

    from pyJianYingDraft.keyframe import KeyframeProperty as KP

    def _clamp01(v: float) -> float:
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return v

    def _get_xy(e: dict):
        try:
            x = float(e.get("x"))
            y = float(e.get("y"))
            return _clamp01(x), _clamp01(y)
        except Exception:
            return None

    # 只保留合法坐标的 move/click，避免归一化越界导致镜头“慢漂”
    move_events = []
    click_events = []
    for e in events:
        typ = e.get("type")
        if typ not in ("move", "click"):
            continue
        if "time" not in e:
            continue
        xy = _get_xy(e)
        if xy is None:
            continue
        e2 = dict(e)
        e2["x"], e2["y"] = xy
        if typ == "move":
            move_events.append(e2)
        else:
            click_events.append(e2)

    def is_text_key(key_str: str) -> bool:
        """
        文本输入相关按键判定（工程近似）：
        - 单字符：字母/数字/常见符号 -> 视为文本键
        - 特殊键：space/enter/backspace/tab -> 视为文本键
        - 排除：ctrl/alt/shift/cmd/win/esc/方向键/F1~F12 等
        """
        if not key_str:
            return False
        ks = str(key_str)
        low = ks.lower()

        # 修饰键/导航键/功能键（排除）
        deny_prefixes = (
            "key.ctrl",
            "key.alt",
            "key.shift",
            "key.cmd",
            "key.win",
            "key.esc",
            "key.up",
            "key.down",
            "key.left",
            "key.right",
            "key.media",
        )
        if low.startswith(deny_prefixes):
            return False
        if low.startswith("key.f") and low[5:].isdigit():
            return False

        # 允许的特殊键
        allow_special = ("key.space", "key.enter", "key.backspace", "key.tab")
        if low in allow_special:
            return True

        # 单字符（含常见标点）视为文本输入
        if len(ks) == 1:
            return True

        return False

    # 说明：进入聚焦需要“文本键”，但聚焦维持用“任意 keypress”更稳。
    # 否则在输入法/组合键/慢速输入场景下，可能出现误判“输入结束”，导致镜头开始恢复，引发肉眼可见的漂移。
    text_key_events = [
        e
        for e in events
        if e.get("type") == "keypress"
        and isinstance(e.get("time"), (int, float))
        and is_text_key(e.get("key", ""))
    ]
    all_key_events = [
        e for e in events if e.get("type") == "keypress" and isinstance(e.get("time"), (int, float))
    ]

    if not text_key_events:
        print("No text keypress events found. Skipping smart zoom.")
        return
    if not all_key_events:
        print("No keypress events found. Skipping smart zoom.")
        return

    text_key_events.sort(key=lambda e: float(e["time"]))
    all_key_events.sort(key=lambda e: float(e["time"]))

    # --- 聚焦会话切分：以“文本键”作为进入点；以“任意 keypress 静默 2s”作为退出点 ---
    sessions: list[dict] = []
    key_i = 0
    for te in text_key_events:
        t0 = float(te["time"])
        # 找到 t0 前后对应的 key_i 起点
        while key_i < len(all_key_events) and float(all_key_events[key_i]["time"]) < t0:
            key_i += 1
        # 从 t0 开始，向后延伸直到静默 2s
        last = t0
        j = key_i
        while j < len(all_key_events):
            tt = float(all_key_events[j]["time"])
            if tt < t0:
                j += 1
                continue
            if tt - last > END_SILENCE_S:
                break
            last = tt
            j += 1
        sessions.append({"t0": t0, "t_last": last})

    # 合并重叠会话（避免多个文本键触发生成一堆重叠关键帧）
    sessions.sort(key=lambda x: x["t0"])
    merged: list[dict] = []
    for s in sessions:
        if not merged:
            merged.append(s)
            continue
        prev = merged[-1]
        if s["t0"] <= prev["t_last"] + END_SILENCE_S:
            prev["t_last"] = max(prev["t_last"], s["t_last"])
        else:
            merged.append(s)

    print(f"Typing focus sessions: {len(merged)} (start=text key, end=any key silence)")

    def get_clamped_pos(tx: float, ty: float, scale: float):
        px = -tx * scale
        py = -ty * scale
        limit = max(0.0, scale - 1.0)
        px = max(-limit, min(px, limit))
        py = max(-limit, min(py, limit))
        return px, py

    def viewport_half(scale: float):
        return 0.5 / scale, 0.5 / scale

    viewport_half_w, viewport_half_h = viewport_half(scale_val)

    def pick_anchor_xy(t0: float):
        """
        选择输入位置锚点：
        1) t0 前 MOVE_LOOKBACK_S 秒内最近 move
        2) 否则最近 click
        3) 否则 None
        """
        lo = t0 - MOVE_LOOKBACK_S
        mv = [m for m in move_events if lo <= float(m.get("time", -1)) <= t0 and "x" in m and "y" in m]
        if mv:
            m = max(mv, key=lambda x: float(x["time"]))
            return float(m["x"]), float(m["y"])
        ck = [c for c in click_events if float(c.get("time", -1)) <= t0 and "x" in c and "y" in c]
        if ck:
            c = max(ck, key=lambda x: float(x["time"]))
            return float(c["x"]), float(c["y"])
        return None

    def to_tx_ty(x: float, y: float):
        # smart_zoomer 原有坐标系：中心 0.5/0.5，转为 [-1,1] 偏移
        tx = (x - 0.5) * 2
        ty = (0.5 - y) * 2
        return tx, ty

    for s in merged:
        t0 = float(s["t0"])
        t_last = float(s["t_last"])
        t_start = max(0.0, t0 - PRE_ROLL_S)
        t_end = t_last + END_SILENCE_S

        t_start_us = int(t_start * 1_000_000)
        t0_us = int(t0 * 1_000_000)
        t_end_us = int(t_end * 1_000_000)

        # 进入前先写全景
        video_segment.add_keyframe(KP.uniform_scale, t_start_us, 1.0)
        video_segment.add_keyframe(KP.position_x, t_start_us, 0.0)
        video_segment.add_keyframe(KP.position_y, t_start_us, 0.0)

        anchor = pick_anchor_xy(t0)
        if anchor is None:
            # 无锚点：只缩放不平移
            pos_x, pos_y = 0.0, 0.0
            current_cam_x, current_cam_y = 0.5, 0.5
        else:
            ax, ay = anchor
            tx, ty = to_tx_ty(ax, ay)
            pos_x, pos_y = get_clamped_pos(tx, ty, scale_val)
            current_cam_x = -pos_x / (2 * scale_val) + 0.5
            current_cam_y = 0.5 - pos_y / (2 * scale_val)

        # 进入聚焦
        video_segment.add_keyframe(KP.uniform_scale, t0_us, scale_val)
        video_segment.add_keyframe(KP.position_x, t0_us, pos_x)
        video_segment.add_keyframe(KP.position_y, t0_us, pos_y)

        # 重要：聚焦期间不再跟随 move。
        #
        # 原因（对应用户反馈“镜头自己慢慢漂移”）：
        # - 录制过程中 move 事件可能因触控板抖动/DPI 口径差异产生微小但持续的变化
        # - 即使有阈值/节流，也可能在长时间输入时触发少量跟随，从而出现“慢慢漂”
        #
        # 这里采取更稳的策略：聚焦后冻结镜头中心，只用于展示输入区域，直到静默退出。

        # 退出：保持到 t_end，然后恢复全景
        video_segment.add_keyframe(KP.uniform_scale, t_end_us, scale_val)
        # 关键点：保持帧位置必须与进入聚焦的位置完全一致，避免因浮点重算产生极小差异，
        # 在剪映插值下表现为“镜头慢慢漂移”。
        video_segment.add_keyframe(KP.position_x, t_end_us, pos_x)
        video_segment.add_keyframe(KP.position_y, t_end_us, pos_y)

        t_restore = t_end_us + ZOOM_OUT_US
        video_segment.add_keyframe(KP.uniform_scale, t_restore, 1.0)
        video_segment.add_keyframe(KP.position_x, t_restore, 0.0)
        video_segment.add_keyframe(KP.position_y, t_restore, 0.0)

    print("Typing focus smart zoom applied successfully.")

