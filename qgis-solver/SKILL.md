---
name: qgis_geoai_bridge
description: Session-aware QGIS socket skill for teaching cartography, thematic mapping, layout export, and guarded PyQGIS fallback.
---

# QGIS GeoAI Bridge

This skill talks to `GeoaiSocketServer` over the local socket on port `5555`.

The preferred workflow is:

1. Inspect the current project with `get_layers()`.
2. Prepare data with dedicated tools such as `prepare_layer()`, `filter_layer()`, `join_attributes()`, or `create_connection_lines()`.
3. Prefer the teaching templates for finished outputs:
   - `create_population_distribution_map()`
   - `create_population_density_map()`
   - `create_population_migration_map()`
   - `create_hu_line_comparison_map()`
4. Use lower-level cartography tools only for targeted overrides:
   - `apply_graduated_renderer()`
   - `create_heatmap()`
   - `create_flow_arrows()`
   - `set_layer_labels()`
   - `customize_layout_legend()`
   - `embed_chart()`
5. Export with `auto_layout()` and `export_map()` when you need a final artifact.

## Session Rules

- `map_session` is the unit of one map product.
- Template tools create a new `map_session` by default.
- Reuse the same `map_session` only when you intentionally want multiple operations to build the same map.
- `reference_layers` is explicit opt-in. Existing visible project layers are not automatically included in session-driven outputs.
- Responses may include `map_session`, `layer_group`, `layout_name`, and `export_path` inside `artifacts`.

## Tool Preference

- Use dedicated cartography and teaching tools first.
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
