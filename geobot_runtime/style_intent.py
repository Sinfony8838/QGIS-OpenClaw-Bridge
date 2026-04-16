from __future__ import annotations

import re
from typing import Iterable, Optional


HEX_COLOR_PATTERN = re.compile(r"(?<![#\w])(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6})(?!\w)")
NUMBER_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)")

COLOR_ALIASES = (
    ("yellow", "#FFFF00"),
    ("黄色", "#FFFF00"),
    ("黄颜色", "#FFFF00"),
    ("blue", "#0000FF"),
    ("蓝色", "#0000FF"),
    ("green", "#008000"),
    ("绿色", "#008000"),
    ("red", "#FF0000"),
    ("红色", "#FF0000"),
    ("orange", "#FFA500"),
    ("橙色", "#FFA500"),
    ("purple", "#800080"),
    ("紫色", "#800080"),
    ("pink", "#FFC0CB"),
    ("粉色", "#FFC0CB"),
    ("black", "#000000"),
    ("黑色", "#000000"),
    ("white", "#FFFFFF"),
    ("白色", "#FFFFFF"),
    ("gray", "#808080"),
    ("grey", "#808080"),
    ("灰色", "#808080"),
    ("cyan", "#00FFFF"),
    ("青色", "#00FFFF"),
)

DIRECT_STYLE_HINTS = (
    "当前图层",
    "图层",
    "样式",
    "颜色",
    "填充",
    "轮廓",
    "描边",
    "边界",
    "透明度",
    "线宽",
    "符号",
    "style",
    "color",
    "fill",
    "outline",
    "stroke",
    "opacity",
    "width",
    "symbol",
    "renderer",
    "layer",
)

CURRENT_LAYER_HINTS = (
    "当前图层",
    "当前层",
    "目前图层",
    "active layer",
    "current layer",
)

LABEL_HINTS = ("标注", "标签", "label", "labels")
LABEL_SHOW_HINTS = (
    "显示标注",
    "打开标注",
    "开启标注",
    "显示当前图层标注",
    "打开当前图层标注",
    "显示标签",
    "打开标签",
    "开启标签",
    "show labels",
    "enable labels",
)
LABEL_HIDE_HINTS = (
    "隐藏标注",
    "关闭标注",
    "取消标注",
    "隐藏当前图层标注",
    "关闭当前图层标注",
    "隐藏标签",
    "关闭标签",
    "hide labels",
    "disable labels",
)
LAYER_SHOW_HINTS = ("显示图层", "显示当前图层", "打开图层", "打开当前图层", "取消隐藏", "show layer", "unhide layer")
LAYER_HIDE_HINTS = ("隐藏图层", "隐藏当前图层", "关闭图层", "关闭当前图层", "hide layer")
ACTIVATE_HINTS = ("选中", "激活", "设为当前图层", "切换到图层", "select layer", "activate layer", "make active")
ZOOM_HINTS = ("缩放到图层", "缩放到当前图层", "定位到图层", "定位到当前图层", "聚焦到图层", "聚焦到当前图层", "zoom to layer", "focus layer")
MOVE_TOP_HINTS = ("置顶", "移到最上层", "移动到顶部", "move to top", "bring to front")
MOVE_BOTTOM_HINTS = ("置底", "移到最下层", "移动到底部", "move to bottom", "send to back")
OPACITY_HINTS = ("透明度", "opacity", "透明")
WIDTH_HINTS = ("线宽", "宽度", "outline width", "line width", "stroke width")
OUTLINE_HINTS = ("轮廓", "描边", "边界", "outline", "stroke", "border")


def normalize_hex_color(value: str) -> str:
    text = str(value or "").strip().upper()
    if len(text) == 4 and text.startswith("#"):
        return "#" + "".join(ch * 2 for ch in text[1:])
    return text


def contains_any(message: str, keywords: Iterable[str]) -> bool:
    lowered = str(message or "").lower()
    return any(str(keyword).lower() in lowered for keyword in keywords)


def extract_requested_color(message: str) -> Optional[str]:
    text = str(message or "")
    hex_match = HEX_COLOR_PATTERN.search(text)
    if hex_match:
        return normalize_hex_color(hex_match.group(1))

    lowered = text.lower()
    for alias, hex_value in COLOR_ALIASES:
        if alias.lower() in lowered:
            return hex_value
    return None


def extract_numeric_value(message: str, keywords: Iterable[str]) -> Optional[float]:
    if not contains_any(message, keywords):
        return None
    lowered = str(message or "").lower()
    keyword_index = min((lowered.find(str(keyword).lower()) for keyword in keywords if str(keyword).lower() in lowered), default=-1)
    search_segment = lowered[keyword_index:] if keyword_index >= 0 else lowered
    match = NUMBER_PATTERN.search(search_segment)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def extract_opacity_value(message: str) -> Optional[float]:
    value = extract_numeric_value(message, OPACITY_HINTS)
    if value is None:
        return None
    if "%" in str(message):
        value = value / 100.0
    elif value > 1.0:
        value = value / 100.0 if value <= 100.0 else 1.0
    return max(0.0, min(1.0, value))


def extract_width_value(message: str) -> Optional[float]:
    value = extract_numeric_value(message, WIDTH_HINTS)
    if value is None:
        return None
    return max(0.0, value)


def mentions_current_layer(message: str) -> bool:
    return contains_any(message, CURRENT_LAYER_HINTS)


def mentions_outline(message: str) -> bool:
    return contains_any(message, OUTLINE_HINTS)


def is_direct_style_request(message: str, suggested_template: str = "", requires_export: bool = False) -> bool:
    if requires_export:
        return False
    has_style_value = bool(
        extract_requested_color(message)
        or extract_opacity_value(message) is not None
        or extract_width_value(message) is not None
    )
    return has_style_value and contains_any(message, DIRECT_STYLE_HINTS)


def wants_show_labels(message: str) -> bool:
    return contains_any(message, LABEL_SHOW_HINTS)


def wants_hide_labels(message: str) -> bool:
    return contains_any(message, LABEL_HIDE_HINTS)


def wants_label_change(message: str) -> bool:
    return contains_any(message, LABEL_HINTS)


def wants_show_layer(message: str) -> bool:
    return contains_any(message, LAYER_SHOW_HINTS) and not wants_label_change(message)


def wants_hide_layer(message: str) -> bool:
    return contains_any(message, LAYER_HIDE_HINTS) and not wants_label_change(message)


def wants_activate_layer(message: str) -> bool:
    return contains_any(message, ACTIVATE_HINTS)


def wants_zoom_to_layer(message: str) -> bool:
    return contains_any(message, ZOOM_HINTS)


def wants_move_layer_top(message: str) -> bool:
    return contains_any(message, MOVE_TOP_HINTS)


def wants_move_layer_bottom(message: str) -> bool:
    return contains_any(message, MOVE_BOTTOM_HINTS)


def find_named_match(message: str, values: Iterable[str]) -> Optional[str]:
    lowered = str(message or "").lower()
    candidates = sorted({str(value) for value in values if value}, key=len, reverse=True)
    for candidate in candidates:
        if candidate.lower() in lowered:
            return candidate
    return None


def find_named_layer_match(message: str, layer_names: Iterable[str]) -> Optional[str]:
    return find_named_match(message, layer_names)
