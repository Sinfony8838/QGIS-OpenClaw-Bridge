---
name: qgis_geoai_bridge
description: Session-aware QGIS socket skill for direct current-project edits, thematic mapping, layout export, and guarded PyQGIS fallback.
---

# QGIS GeoAI Bridge

This skill talks to `GeoaiSocketServer` over the local socket on port `5555`.

The preferred workflow is:

1. Inspect the current project with `get_layers()`.
2. For direct current-project edits, prefer low-level tools first:
   - `set_style()` or `set_layer_style()` for color, fill, outline, opacity, and width changes
   - `set_layer_labels()` for labels
   - `set_layer_visibility()` for show/hide
   - `set_active_layer()` plus `zoom_to_layer()` for selecting and focusing a layer
   - `move_layer()` for ordering
   - `query_attributes()` only when you need record inspection
   - For requests like "change the current layer to yellow", do not use `apply_graduated_renderer()` or any thematic template. Use `set_layer_style()` directly and verify with `get_layer_style()`.
3. Prepare data with dedicated tools such as `prepare_layer()`, `filter_layer()`, `join_attributes()`, or `create_connection_lines()`.
4. Use templates only when the user clearly requests a thematic map product:
   - `create_population_distribution_map()`
   - `create_population_density_map()`
   - `create_population_migration_map()`
   - `create_hu_line_comparison_map()`
5. Use terrain tools when the task is about DEMs, contours, profiles, or simplified terrain visualization:
   - `create_terrain_profile()`
   - `create_terrain_model()`
6. Use lower-level cartography tools for targeted overrides and composition:
   - `apply_graduated_renderer()`
   - `create_heatmap()`
   - `create_flow_arrows()`
   - `customize_layout_legend()`
   - `embed_chart()`
7. Export with `auto_layout()` and `export_map()` only when you need a final artifact.

## Session Rules

- `map_session` is the unit of one map product.
- Template tools create a new `map_session` by default.
- Reuse the same `map_session` only when you intentionally want multiple operations to build the same map.
- `reference_layers` is explicit opt-in. Existing visible project layers are not automatically included in session-driven outputs.
- Responses may include `map_session`, `layer_group`, `layout_name`, and `export_path` inside `artifacts`.

## Tool Preference

- In QGIS-only mode, prefer direct current-project edits before thematic templates.
- Use dedicated cartography and teaching tools first when the user explicitly wants a composed map output.
- Use `run_algorithm()` only when no dedicated tool covers the workflow.
- Use `run_python_code()` only as an expert fallback for missing APIs, quick validation, or debugging.

## Error Handling

Always inspect:

- `status`
- `message`
- `data`
- `warnings`
- `artifacts`

If `status != "success"`, stop and resolve the failure before chaining more map operations.
