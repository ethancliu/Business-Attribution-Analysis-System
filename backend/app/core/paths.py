# -*- coding: utf-8 -*-
"""文件存储目录规范与路径安全校验。

目录规范（需求 §十，强制）:
    业务附件    uploads/{user_id}/{conversation_id}/
    分析结果    exports/{user_id}/{conversation_id}/
    分析临时    workspace/{user_id}/{conversation_id}/

级联删除:
    删除会话时，上述三个目录整体递归删除。
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

KIND_UPLOAD = "uploads"
KIND_EXPORT = "exports"
KIND_WORKSPACE = "workspace"

_ROOTS = {
    KIND_UPLOAD: settings.upload_root,
    KIND_EXPORT: settings.export_root,
    KIND_WORKSPACE: settings.workspace_root,
}

# 文件名中禁止出现的字符：路径分隔符、路径穿越、控制字符、Windows 保留字符
_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


# ---------------------------------------------------------------------------
# 文件名与相对路径安全
# ---------------------------------------------------------------------------

def sanitize_filename(name: str, fallback: str = "unnamed") -> str:
    """清洗上传文件名，杜绝路径穿越与非法字符。

    >>> sanitize_filename("../../etc/passwd")
    'passwd'
    >>> sanitize_filename("a/b\\c.csv")
    'a_b_c.csv'
    """
    raw = (name or "").strip().replace("\r", "").replace("\n", "")
    # 只取最后一段，剥离任何目录成分
    raw = raw.replace("\\", "/").split("/")[-1]
    raw = _ILLEGAL_CHARS.sub("_", raw)
    raw = raw.strip(" .")            # Windows 不允许结尾空格与点
    if not raw or raw in {".", ".."}:
        return fallback
    # 限制长度，保留扩展名
    if len(raw) > 180:
        stem, dot, ext = raw.rpartition(".")
        raw = (stem[:160] + dot + ext) if dot else raw[:180]
    return raw


def safe_join(root: Path, *parts: str) -> Path:
    """在 root 下安全拼接路径，确保结果不逃逸出 root。

    抛出 ValueError 表示检测到路径穿越。
    """
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*[str(p) for p in parts]).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"检测到非法路径穿越: {candidate} 不在 {root_resolved} 之内") from exc
    return candidate


def root_of(kind: str) -> Path:
    try:
        return _ROOTS[kind]
    except KeyError as exc:
        raise ValueError(f"未知的存储类型: {kind}（应为 uploads/exports/workspace）") from exc


def dir_of(kind: str, user_id: int, conversation_id: int) -> Path:
    """返回并创建 {kind}/{user_id}/{conversation_id}/ 目录。"""
    d = safe_join(root_of(kind), str(user_id), str(conversation_id))
    d.mkdir(parents=True, exist_ok=True)
    return d


def rel_path(kind: str, user_id: int, conversation_id: int, filename: str) -> str:
    """返回入库用的相对路径（统一正斜杠），形如 uploads/2/12/xxx.csv。"""
    return f"{kind}/{user_id}/{conversation_id}/{sanitize_filename(filename)}"


def abs_path(rel: str) -> Path:
    """把入库的相对路径还原为绝对路径，并校验不逃逸出 data 根目录。"""
    rel_norm = (rel or "").replace("\\", "/").lstrip("/")
    return safe_join(settings.data_path, *rel_norm.split("/"))


def unique_name(original: str) -> str:
    """生成带时间戳前缀的唯一文件名，避免同名覆盖。

    同时保证仍以清洗后的原始名结尾，方便用户识别。
    """
    clean = sanitize_filename(original)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return f"{stamp}_{clean}"


# ---------------------------------------------------------------------------
# 级联删除
# ---------------------------------------------------------------------------

@dataclass
class CleanupResult:
    removed_dirs: list[str]
    removed_files: int = 0
    freed_bytes: int = 0


def _dir_stats(path: Path) -> tuple[int, int]:
    """统计目录下的文件数与总字节数。"""
    files = 0
    size = 0
    if not path.exists():
        return 0, 0
    for p in path.rglob("*"):
        if p.is_file():
            files += 1
            try:
                size += p.stat().st_size
            except OSError:  # pragma: no cover - 文件被占用等情况
                pass
    return files, size


def cleanup_conversation_dirs(user_id: int, conversation_id: int) -> CleanupResult:
    """删除某会话在 uploads / exports / workspace 下的全部目录与文件。"""
    removed: list[str] = []
    files = 0
    size = 0

    for kind in (KIND_UPLOAD, KIND_EXPORT, KIND_WORKSPACE):
        try:
            target = safe_join(root_of(kind), str(user_id), str(conversation_id))
        except ValueError as exc:
            logger.error("跳过不安全的清理路径: %s", exc)
            continue

        if not target.exists():
            continue

        n, s = _dir_stats(target)
        try:
            shutil.rmtree(target, ignore_errors=False)
            removed.append(f"{kind}/{user_id}/{conversation_id}")
            files += n
            size += s
            logger.info("已删除目录 %s（%s 个文件，%s 字节）", target, n, s)
        except OSError as exc:
            logger.error("删除目录失败 %s: %s", target, exc)
            # 退化为逐个删除，尽量清干净
            try:
                shutil.rmtree(target, ignore_errors=True)
                removed.append(f"{kind}/{user_id}/{conversation_id}")
                files += n
                size += s
            except Exception:  # noqa: BLE001
                pass

    return CleanupResult(removed_dirs=removed, removed_files=files, freed_bytes=size)


def delete_file(rel: str) -> bool:
    """删除单个文件（相对路径）。返回是否真正删除了文件。"""
    try:
        p = abs_path(rel)
    except ValueError as exc:
        logger.error("拒绝删除非法路径 %s: %s", rel, exc)
        return False
    if p.is_file():
        try:
            p.unlink()
            return True
        except OSError as exc:
            logger.error("删除文件失败 %s: %s", p, exc)
            return False
    return False


def write_text_file(kind: str, user_id: int, conversation_id: int, filename: str, content: str) -> str:
    """写入文本文件，返回入库用相对路径。"""
    d = dir_of(kind, user_id, conversation_id)
    target = safe_join(d, sanitize_filename(filename))
    target.write_text(content, encoding="utf-8")
    return f"{kind}/{user_id}/{conversation_id}/{target.name}"


def human_size(num: int | float) -> str:
    """人类可读的文件大小。"""
    n = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def storage_stats() -> dict[str, float | int]:
    """统计三类目录的文件数与占用空间（管理控制台用）。"""
    out: dict[str, float | int] = {}
    for kind in (KIND_UPLOAD, KIND_EXPORT, KIND_WORKSPACE):
        files, size = _dir_stats(root_of(kind))
        out[f"{kind}_files"] = files
        out[f"{kind}_size_mb"] = round(size / 1024 / 1024, 2)
    return out


def ensure_dirs() -> None:
    """启动时确保三类存储根目录存在。"""
    for kind, root in _ROOTS.items():
        root.mkdir(parents=True, exist_ok=True)
        logger.debug("存储目录就绪 %s -> %s", kind, root)
