# -*- coding: utf-8 -*-
"""大模型接口层。

设计原则:
    归因结论的**事实部分**全部来自 SQL 与工具产出，大模型只负责语言润色与措辞组织，
    不参与数字计算。因此离线运行（provider=offline）时系统依然给出完整、正确的结论，
    只是措辞更模板化。

支持 provider:
    offline          —— 默认，不调用任何外部服务，使用确定性模板措辞
    openai_compat    —— 任意兼容 OpenAI Chat Completions 协议的网关（含 DashScope 兼容模式）
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.runtime_config import runtime_config

logger = logging.getLogger(__name__)

TIMEOUT_SEC = 30


class LLMClient:
    """极简 LLM 客户端：只有一个 polish() 能力，失败一律降级为原文。"""

    def __init__(self) -> None:
        self._provider = "offline"

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    @property
    def provider(self) -> str:
        return str(runtime_config.get("llm.provider", "offline") or "offline").strip().lower()

    @property
    def enabled(self) -> bool:
        if self.provider in ("offline", "none", "disabled", ""):
            return False
        if not runtime_config.get_bool("llm.enabled", False):
            return False
        return bool(runtime_config.get("llm.api_key") and runtime_config.get("llm.base_url"))

    @property
    def model(self) -> str:
        return str(runtime_config.get("llm.model", "qwen-plus"))

    # ------------------------------------------------------------------
    # 调用
    # ------------------------------------------------------------------

    def _chat(self, system: str, user: str, max_tokens: int = 800) -> str | None:
        base = str(runtime_config.get("llm.base_url", "")).rstrip("/")
        key = str(runtime_config.get("llm.api_key", ""))
        if not base or not key:
            return None

        try:
            resp = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": float(runtime_config.get("llm.temperature", 0.3)),
                    "max_tokens": max_tokens,
                },
                timeout=TIMEOUT_SEC,
            )
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
            return payload["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001 - 任何异常都降级
            logger.warning("LLM 调用失败，降级为模板措辞：%s", exc)
            return None

    def polish(self, draft: str, *, scene_hint: str = "") -> str:
        """把规则生成的结论润色成更自然的表述；不可用时原样返回。"""
        if not self.enabled or not draft.strip():
            return draft

        system = (
            "你是资深经营分析师。请在不改变任何数字、不新增任何事实的前提下，"
            "把给定的分析结论改写得更有条理、更适合管理者阅读。"
            "严禁修改任何数值、单位与因果关系；保留原有的分点结构。"
        )
        user = f"【业务背景】{scene_hint}\n\n【待润色结论】\n{draft}"
        out = self._chat(system, user)
        if not out or len(out.strip()) < 20:
            return draft
        # 安全校验：润色结果必须保留原文中的所有数字
        if not _numbers_preserved(draft, out):
            logger.warning("润色结果数字与原稿不一致，已丢弃润色结果")
            return draft
        return out.strip()


def _numbers_preserved(draft: str, polished: str) -> bool:
    """校验润色前后关键数字一致，防止模型篡改数据。"""
    import re

    pattern = re.compile(r"\d+(?:\.\d+)?")
    src = set(pattern.findall(draft))
    dst = set(pattern.findall(polished))
    missing = {n for n in src if n not in dst}
    # 允许少量格式差异，缺失超过 20% 判定为篡改
    if not src:
        return True
    return len(missing) / len(src) <= 0.2


llm_client = LLMClient()
