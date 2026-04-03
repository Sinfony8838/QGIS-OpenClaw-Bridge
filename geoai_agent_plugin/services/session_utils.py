import re


DEFAULT_LAYOUT_NAME = "GeoAI_Output"
DEFAULT_GROUP_PREFIX = "GeoAI Session"
DEFAULT_CHART_SLOT = "primary"

ROLE_PRIORITIES = {
    "annotation": 100,
    "label": 95,
    "point": 90,
    "centroid": 88,
    "station": 87,
    "comparison_line": 82,
    "flow_line": 80,
    "overlay_line": 78,
    "line": 72,
    "boundary": 64,
    "reference_line": 60,
    "surface": 52,
    "polygon": 44,
    "fill": 40,
    "raster": 20,
    "basemap": 10,
    "default": 50,
}


def slugify_text(value, fallback="map"):
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "")).strip("_").lower()
    return text or fallback


def unique_name(base_name, existing_names, suffix_hint=None):
    base = str(base_name or DEFAULT_LAYOUT_NAME).strip() or DEFAULT_LAYOUT_NAME
    existing = {str(name) for name in existing_names if name}
    if base not in existing:
        return base

    suffix = slugify_text(suffix_hint, fallback="session")
    candidate = f"{base}_{suffix}"
    if candidate not in existing:
        return candidate

    index = 2
    while True:
        candidate = f"{base}_{suffix}_{index}"
        if candidate not in existing:
            return candidate
        index += 1


def normalize_role(role, fallback="default"):
    value = str(role or "").strip().lower()
    return value if value in ROLE_PRIORITIES else fallback


def role_priority(role):
    return ROLE_PRIORITIES.get(normalize_role(role), ROLE_PRIORITIES["default"])


def ordered_session_entries(entries):
    sortable = []
    for entry in entries or []:
        sortable.append(
            (
                -role_priority(entry.get("role")),
                int(entry.get("order", 0)),
                str(entry.get("layer_name") or entry.get("layer_id") or ""),
                entry,
            )
        )
    return [item[-1] for item in sorted(sortable)]


def build_layer_id_sequence(entries, include_reference=True):
    seen = set()
    ordered_ids = []
    for entry in ordered_session_entries(entries):
        if not entry.get("include_in_layout", True):
            continue
        if not include_reference and entry.get("is_reference"):
            continue
        layer_id = entry.get("layer_id")
        if not layer_id or layer_id in seen:
            continue
        seen.add(layer_id)
        ordered_ids.append(layer_id)
    return ordered_ids


def chart_slot_position(slot_index, base_position=None):
    position = {
        "x": 205.0,
        "y": 25.0,
        "width": 85.0,
        "height": 55.0,
    }
    if isinstance(base_position, dict):
        for key in position:
            if key in base_position:
                position[key] = float(base_position[key])

    index = max(int(slot_index), 0)
    column = index % 2
    row = index // 2
    return {
        "x": position["x"] + column * (position["width"] + 8.0),
        "y": position["y"] + row * (position["height"] + 8.0),
        "width": position["width"],
        "height": position["height"],
    }
