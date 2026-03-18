# QGIS Automation Tools Reference (V3.0)

## Production Core

This is the core toolset for "one-click map generation", supporting the entire workflow from spatial analysis to layout export.

### Tool: set_style
**Parameters:** `layer_id`, `**properties`
**Description:** Universal styling engine. Supports all QGIS symbol properties. Common properties include: `color` (Hex/RGB), `width` (line width), `size` (point size), `opacity` (0.1-1.0), `outline_color`.

### Tool: run_algorithm
**Parameters:** `algorithm_id`, `params`
**Description:** Universal analysis engine. Executes all QGIS Processing algorithms. Requires algorithm ID (e.g., `native:buffer`) and parameter dictionary.

### Tool: auto_layout
**Parameters:** `title`, `paper_size`
**Description:** Automated layout. Generates standard A4 layout with north arrow, scale bar, legend, and main map item.

### Tool: export_map
**Parameters:** `file_path`
**Description:** Final output. Exports current layout to PDF or image file.

---

## Utilities

### Tool: get_layers
**Parameters:** None
**Description:** Retrieves all layer IDs and names in current project. Must call this tool to get layer IDs before any spatial operation.

### Tool: get_algorithm_help
**Parameters:** `algorithm_id`
**Description:** Intelligent error prevention. Queries specific QGIS algorithm parameter definitions to prevent parameter errors.

### Tool: fly_to
**Parameters:** `lat`, `lon`, `scale`
**Description:** Dynamic camera. Performs smooth fly-to animation on QGIS canvas for presentation or positioning.

### Tool: update_banner
**Parameters:** `text`
**Description:** UI subtitle. Displays status information or presentation subtitle at the top of QGIS interface.

---

## Common Algorithm IDs Quick Reference

| Algorithm | ID |
|-----------|-----|
| Buffer Analysis | `native:buffer` |
| Clip | `native:clip` |
| Centroids | `native:centroids` |
| Heatmap (Kernel Density) | `heatmapkerneldensity` |
| Reproject Layer | `native:reprojectlayer` |

---

## Standard Operating Procedure (SOP)

When receiving a "generate/make map" task, AI should combine tools according to this logic:

1. **Data Recognition**: Call `get_layers` to identify base map and business data.

2. **Spatial Computation**: Call `run_algorithm` based on requirements.

3. **Thematic Expression**: Call `set_style` to color and beautify results.

4. **Delivery**: Call `auto_layout` for layout, then `export_map` to complete file production.
