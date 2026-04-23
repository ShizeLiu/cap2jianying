"""
JianYing Editor Skill - High Level Wrapper (Mixin Based)
旨在解决路径依赖、API 复杂度及严格校验问题。
"""

import os
import sys
import uuid
import json
import argparse
from typing import Union, Optional

# 环境初始化
from utils.env_setup import setup_env
setup_env()

# 运行时配置
from utils.config import CONFIG

# 导入工具函数
from utils.constants import SYNONYMS
from utils.formatters import (
    resolve_enum_with_synonyms, format_srt_time, safe_tim, 
    get_duration_ffprobe_cached, get_default_drafts_root, get_all_drafts
)

# 导入基类与 Mixins
from core.project_base import JyProjectBase
from core.media_ops import MediaOpsMixin
from core.text_ops import TextOpsMixin
from core.vfx_ops import VfxOpsMixin
from core.mocking_ops import MockingOpsMixin

try:
    import pyJianYingDraft as draft
    from pyJianYingDraft import VideoSceneEffectType, TransitionType
except ImportError:
    draft = None

class JyProject(JyProjectBase, MediaOpsMixin, TextOpsMixin, VfxOpsMixin, MockingOpsMixin):
    """
    高层封装工程类。通过多重继承 Mixins 实现功能解耦。
    """
    def _resolve_enum(self, enum_cls, name: str):
        return resolve_enum_with_synonyms(enum_cls, name, SYNONYMS)

    def add_clip(self, media_path: str, source_start: Union[str, int], duration: Union[str, int], 
                 target_start: Union[str, int] = None, track_name: str = "VideoTrack", **kwargs):
        """高层剪辑接口：从媒体指定位置裁剪指定长度，并放入轨道。"""
        if target_start is None:
            target_start = self.get_track_duration(track_name)
        return self.add_media_safe(media_path, target_start, duration, track_name, source_start=source_start, **kwargs)

    def save(self):
        """保存并执行质检报告。"""
        self.script.save()
        self._patch_cloud_material_ids()
        self._force_activate_adjustments()
        
        draft_path = os.path.join(self.root, self.name)
        if os.path.exists(draft_path):
            os.utime(draft_path, None)
        # 注意：Windows 默认控制台编码可能为 GBK，避免输出 emoji 导致编码异常
        print(f"[OK] Project '{self.name}' saved and patched.")
        return {"status": "SUCCESS", "draft_path": draft_path}

# 导出工具函数以便向下兼容
__all__ = ["JyProject", "get_default_drafts_root", "get_all_drafts", "safe_tim", "format_srt_time"]

def _emit_result(payload: dict) -> None:
    """
    统一输出机器可解析结果，供 GUI/脚本调用方提取关键字段（如 draft_path）。

    约定：以 RESULT_JSON: 前缀输出一行 JSON。
    """
    print("RESULT_JSON: " + json.dumps(payload, ensure_ascii=False))


def cmd_apply_zoom(args: argparse.Namespace) -> int:
    """
    创建草稿 -> 导入录屏视频 -> 应用智能变焦关键帧 -> 保存。
    """
    if draft is None:
        _emit_result({"status": "ERROR", "code": "missing_pyJianYingDraft", "message": "未安装 pyJianYingDraft"})
        return 2

    video_path = os.path.abspath(args.video)
    events_path = os.path.abspath(args.json)
    if not os.path.exists(video_path):
        _emit_result({"status": "ERROR", "code": "video_missing", "message": f"视频不存在: {video_path}"})
        return 2
    if not os.path.exists(events_path):
        _emit_result({"status": "ERROR", "code": "events_missing", "message": f"事件文件不存在: {events_path}"})
        return 2

    # projects_root 优先级：CLI 参数 > 环境变量 JY_PROJECTS_ROOT > 自动探测
    drafts_root = (
        os.path.abspath(args.projects_root)
        if getattr(args, "projects_root", None)
        else (CONFIG.projects_root_override or None)
    )

    try:
        project = JyProject(
            args.name,
            drafts_root=drafts_root,
            overwrite=not args.no_overwrite,
        )
        seg = project.add_media_safe(video_path, "0s")
        if seg is None:
            _emit_result({"status": "ERROR", "code": "import_failed", "message": "导入视频失败"})
            return 3

        from smart_zoomer import apply_smart_zoom

        apply_smart_zoom(
            project,
            seg,
            events_json_path=events_path,
            zoom_scale=args.scale,
        )
        saved = project.save()
        _emit_result(
            {
                "status": "SUCCESS",
                "command": "apply-zoom",
                "name": project.name,
                "draft_path": saved.get("draft_path"),
                "projects_root": project.root,
            }
        )
        return 0
    except Exception as e:
        _emit_result({"status": "ERROR", "code": "exception", "message": str(e)})
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="剪映 Skill 命令行工具（jy_wrapper）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_zoom = sub.add_parser("apply-zoom", help="录屏视频导入剪映并应用智能变焦")
    p_zoom.add_argument("--name", required=True, help="剪映项目（草稿）名称")
    p_zoom.add_argument("--video", required=True, help="录屏视频路径（mp4/webm）")
    p_zoom.add_argument("--json", required=True, help="事件文件路径（_events.json）")
    p_zoom.add_argument("--scale", type=int, default=150, help="缩放比例（百分比），默认 150")
    p_zoom.add_argument("--projects-root", default="", help="剪映草稿根目录（可选，默认自动探测或读取 JY_PROJECTS_ROOT）")
    p_zoom.add_argument("--no-overwrite", action="store_true", help="若草稿同名已存在，则不覆盖重建")
    p_zoom.set_defaults(func=cmd_apply_zoom)

    return parser


if __name__ == "__main__":
    parser = _build_parser()
    ns = parser.parse_args()
    rc = ns.func(ns)
    raise SystemExit(rc)
