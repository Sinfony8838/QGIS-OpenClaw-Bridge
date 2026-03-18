---
name: qgis_geoai_bridge
description: Expert-level QGIS automation skill. Remotely drives QGIS desktop via Socket protocol, supporting Processing algorithms, automated style configuration (including categorized rendering), precise coordinate system transformation, and standard map export.
---

# QGIS Expert Automation Skill

This skill connects to QGIS `GeoaiSocketServer` through Socket protocol (default port 5555). It enables AI to operate professional desktop GIS software like an API, achieving end-to-end workflow from raw data to final deliverables.

## Core Production Logic (Standard Operating Procedure)

1. **Environment Awareness**: Call `get_layers()` to retrieve current project layer list.
2. **Spatial Analysis**: Call `run_algorithm()` to execute analysis.
   * **Real-time Display**: Default parameter `load_result=True` renders analysis result as "memory layer" directly on map, no file saving required.
   * **Parameter Lookup**: When unsure about parameters, call `get_algorithm_help()` first to query algorithm documentation.
3. **Precise Positioning**: Call `zoom_to_layer()`.
   * **Features**: Plugin automatically handles coordinate system (CRS) transformation and adds 10% visual margin to prevent features from sticking to borders.
4. **Style Configuration**: Call `set_style()`.
   * **Single**: Quick styling with color, width, size.
   * **Categorized**: Specify `column` field and `categories` dictionary mapping for attribute-driven coloring.
5. **Automated Layout**:
   * Call `auto_layout()` to initialize `GeoAI_Output` layout.
   * Call `export_map()` to export PDF or images.

## Tool Definitions

### 1. `run_algorithm(algorithm_id, params, load_result=True)`
* **Purpose**: Execute full QGIS algorithm toolbox (buffer, clip, resample, etc.).
* **Input Conversion**: Supports passing layer name string directly; plugin automatically resolves to QGIS object.
* **Default Output**: If path not specified, automatically set to `memory:` (memory layer).

### 2. `set_style(layer_name, style_type, **properties)`
* **Single Symbol**: Suitable for quick styling. Parameters: `color` (#RRGGBB), `width`, `size`.
* **Categorized**: For thematic maps. Requires `column` (field name) and `categories` (value-color mapping).

### 3. `zoom_to_layer(layer_name)`
* **Robustness**: Built-in `QgsCoordinateTransform` handles positioning offset when layer CRS doesn't match canvas CRS.

### 4. `set_background_color(color)`
* **Visual Adjustment**: Supports setting QGIS main canvas background color for night mode or high-contrast base maps.

## Typical Usage Examples

**Task: Create 100-meter buffer on "rivers" layer, categorize and color by flow, then export image.**

1. `run_algorithm("native:buffer", {"INPUT": "rivers", "DISTANCE": 100})` -> Creates "Result_buffer".
2. `set_style(layer_name="Result_buffer", style_type="categorized", column="flow", categories={"high": "#0000FF", "low": "#ADD8E6"})`.
3. `zoom_to_layer(layer_name="Result_buffer")`.
4. `auto_layout(title="River Buffer Analysis")`.
5. `export_map(file_path="C:/Output/river_map.png")`.

## Development Notes
* **Server Isolation**: Server-side `GeoaiSocketServer` must NOT call `send_command`; it only executes methods mapped in `handlers`.
* **Memory Priority**: For temporary testing, don't specify `OUTPUT` path to use memory layer, reducing disk fragmentation.
* **Error Handling**: All tools return standard `{"status": "success/error", "message": "..."}` structure; AI should check this status.
