PAPER_SIZES_MM = {
    "A5": (148.0, 210.0),
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "LETTER": (215.9, 279.4),
}

LAYER_PARAMETER_CLASS_TOKENS = (
    "FeatureSource",
    "MapLayer",
    "VectorLayer",
    "RasterLayer",
    "MeshLayer",
    "PointCloudLayer",
    "MultipleLayers",
)

TERRAIN_SOURCE_KINDS = {"raster", "line"}
TERRAIN_TYPES = {"auto", "dem", "contours"}


def is_layer_parameter_definition(definition):
    if definition is None:
        return False

    class_name = type(definition).__name__
    if "Sink" in class_name:
        return False
    return any(token in class_name for token in LAYER_PARAMETER_CLASS_TOKENS)


def _track_resolved_layer(layer, resolved_layers, seen_layer_keys):
    if not layer:
        return

    layer_key = getattr(layer, "id", None)
    if callable(layer_key):
        layer_key = layer_key()
    if not layer_key:
        layer_key = id(layer)

    if layer_key in seen_layer_keys:
        return

    seen_layer_keys.add(layer_key)
    resolved_layers.append(layer)


def _resolve_layer_candidate(candidate, layer_resolver, resolved_layers, seen_layer_keys):
    if not isinstance(candidate, str):
        return candidate

    layer = layer_resolver(layer_id=candidate, layer_name=candidate)
    if layer:
        _track_resolved_layer(layer, resolved_layers, seen_layer_keys)
        return layer
    return candidate


def resolve_processing_inputs(params, definitions, layer_resolver):
    definitions_by_name = {
        definition.name(): definition
        for definition in (definitions or [])
        if hasattr(definition, "name") and callable(definition.name)
    }

    fixed_params = {}
    resolved_layers = []
    seen_layer_keys = set()

    for key, value in (params or {}).items():
        definition = definitions_by_name.get(key)
        if is_layer_parameter_definition(definition):
            if isinstance(value, (list, tuple)):
                fixed_params[key] = [
                    _resolve_layer_candidate(item, layer_resolver, resolved_layers, seen_layer_keys)
                    for item in value
                ]
            else:
                fixed_params[key] = _resolve_layer_candidate(value, layer_resolver, resolved_layers, seen_layer_keys)
        else:
            fixed_params[key] = value

    return fixed_params, resolved_layers


def sort_and_limit_rows(rows, order_by=None, limit=None):
    result = list(rows or [])
    if order_by:
        result.sort(key=lambda row: (row.get(order_by) is None, row.get(order_by)))

    if limit is None:
        return result

    return result[: max(int(limit), 0)]


def normalize_paper_size(paper_size):
    if isinstance(paper_size, dict):
        width = float(paper_size.get("width"))
        height = float(paper_size.get("height"))
        label = str(paper_size.get("label") or f"{width:g}x{height:g} mm")
        return {
            "label": label,
            "width": width,
            "height": height,
        }

    raw_value = str(paper_size or "A4").strip()
    tokens = raw_value.replace("-", " ").split()
    orientation = "landscape"
    if tokens and tokens[-1].lower() in ("portrait", "landscape"):
        orientation = tokens[-1].lower()
        base_name = " ".join(tokens[:-1]) or "A4"
    else:
        base_name = raw_value or "A4"

    key = base_name.upper()
    if key not in PAPER_SIZES_MM:
        raise ValueError(f"Unsupported paper size: {paper_size}")

    width, height = PAPER_SIZES_MM[key]
    if orientation == "landscape" and height > width:
        width, height = height, width
    elif orientation == "portrait" and width > height:
        width, height = height, width

    return {
        "label": f"{key} {orientation}",
        "width": width,
        "height": height,
    }


def layout_frame_for_paper(paper_size):
    paper = normalize_paper_size(paper_size)
    width = paper["width"]
    height = paper["height"]

    side_margin = 10.0
    top_margin = 20.0
    bottom_margin = 10.0
    gutter = 10.0
    legend_width = min(90.0, max(60.0, (width - side_margin * 2.0) * 0.28))
    map_width = max(80.0, width - side_margin * 2.0 - legend_width - gutter)
    content_height = max(80.0, height - top_margin - bottom_margin)

    return {
        "paper": paper,
        "map": {
            "x": side_margin,
            "y": top_margin,
            "width": map_width,
            "height": content_height,
        },
        "legend": {
            "x": side_margin + map_width + gutter,
            "y": top_margin,
            "width": legend_width,
            "height": min(100.0, content_height),
        },
        "title": {
            "x": side_margin,
            "y": 8.0,
        },
    }


def normalize_terrain_type(terrain_type):
    value = str(terrain_type or "auto").strip().lower()
    if value not in TERRAIN_TYPES:
        raise ValueError(f"Unsupported terrain_type: {terrain_type}")
    return value


def infer_terrain_source_kind(terrain_type, layer_kind):
    normalized_type = normalize_terrain_type(terrain_type)
    normalized_kind = str(layer_kind or "").strip().lower()
    if normalized_kind not in TERRAIN_SOURCE_KINDS:
        raise ValueError(f"Unsupported terrain layer kind: {layer_kind}")

    if normalized_type == "auto":
        return "dem" if normalized_kind == "raster" else "contours"

    if normalized_type == "dem" and normalized_kind != "raster":
        raise ValueError("terrain_type='dem' requires a raster terrain layer")
    if normalized_type == "contours" and normalized_kind != "line":
        raise ValueError("terrain_type='contours' requires a line terrain layer")
    return normalized_type


def default_profile_sample_distance(total_length, target_samples=80, minimum=1e-6):
    length = float(total_length or 0.0)
    if length <= 0:
        raise ValueError("Profile length must be positive")

    count = max(int(target_samples), 2)
    return max(length / float(count - 1), float(minimum))


def default_grid_spacing(extent_width, extent_height, target_cells=250, minimum=1e-6):
    width = abs(float(extent_width or 0.0))
    height = abs(float(extent_height or 0.0))
    span = max(width, height)
    if span <= 0:
        raise ValueError("Terrain extent must be positive")

    cells = max(int(target_cells), 1)
    return max(span / float(cells), float(minimum))


def summarize_profile_samples(samples):
    rows = list(samples or [])
    if not rows:
        raise ValueError("Profile samples are required")

    distances = [float(item["distance"]) for item in rows]
    elevations = [float(item["elevation"]) for item in rows]
    min_elevation = min(elevations)
    max_elevation = max(elevations)
    return {
        "point_count": len(rows),
        "total_distance": max(distances),
        "min_elevation": min_elevation,
        "max_elevation": max_elevation,
        "relief": max_elevation - min_elevation,
    }
