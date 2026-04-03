# QGIS Teaching Cartography Tools Reference

All tools return the same response envelope:

```json
{
  "status": "success|error",
  "message": "human readable summary",
  "data": {},
  "warnings": [],
  "artifacts": {}
}
```

Important session behavior:

- `map_session` is the logical unit of one map product.
- Template tools now create a new `map_session` by default unless you explicitly pass one.
- Reusing the same `map_session` means "compose into the same map".
- `artifacts` may include `map_session`, `layer_group`, `layout_name`, and `export_path`.
- `reference_layers` is opt-in. Existing visible project layers are not included in session-driven outputs unless you pass them.

## Core Tools

### `get_layers()`
Returns the current project layers with IDs, providers, and CRS.

### `add_layer_from_path(file_path, layer_name="New Layer", map_session=None, role=None)`
Loads a vector or raster layer from disk. When `map_session` is provided, the new layer is registered into that map session.

### `run_algorithm(algorithm_id, params, load_result=True, map_session=None, role=None)`
Runs a QGIS Processing algorithm. When a result layer is loaded and `map_session` is provided, the result is registered into that session.

### `auto_layout(title="GeoAI Output", paper_size="A4", layout_name="GeoAI_Output", map_session=None, reference_layers=None, extent_mode="session_union")`
Creates or refreshes a map layout.

- With `map_session`, the layout is isolated to that session's layers.
- Without `map_session`, the current visible canvas layers are snapshotted into a new implicit session.
- `extent_mode="session_union"` zooms to the union extent of session layers.

### `export_map(file_path, layout_name="GeoAI_Output", map_session=None)`
Exports a layout to image or PDF. Use `map_session` when you want the export to follow the resolved layout name of that session.

## Data Preparation Tools

### `prepare_layer(layer_name|layer_id, fix_geometry=True, reproject_to=None, force_points=False, map_session=None)`
Fixes invalid geometry, optionally reprojects, and optionally converts to points. Result layers can join a map session.

### `calculate_field(layer_name|layer_id, field_name, expression, field_type="double")`
Evaluates a QGIS expression into a field.

### `filter_layer(layer_name|layer_id, expression, output_name=None, map_session=None)`
Creates a filtered memory layer and optionally registers it into a session.

### `join_attributes(target_layer, join_layer, target_field, join_field, fields=None, map_session=None)`
Creates a joined output layer and optionally registers it into a session.

### `create_centroids(layer_name|layer_id, output_name=None, map_session=None)`
Creates centroids for a line or polygon layer and optionally registers them into a session.

### `create_connection_lines(origins_layer, destinations_layer, origin_id_field, destination_id_field, output_name=None, map_session=None)`
Builds connection lines between matched origin and destination features.

## Cartography Tools

### `set_style(layer_name|layer_id, style_type="single", map_session=None, **properties)`
Applies a simple single-symbol renderer and optionally registers the layer into a session.

### `apply_graduated_renderer(layer_name|layer_id, field, mode="jenks", classes=5, color_ramp="Viridis", precision=2, label_format="{lower} - {upper}", map_session=None)`
Applies graduated styling and optionally registers the layer into a session.

### `create_heatmap(layer_name|layer_id, radius=15, pixel_size=5, weight_field=None, output_mode="memory", map_session=None)`
Creates a heatmap output and registers it into the session as a surface layer when `map_session` is supplied.

### `create_flow_arrows(layer_name|layer_id, start_x=None, start_y=None, end_x=None, end_y=None, width_field=None, color="#d1495b", scale_mode="fixed", map_session=None)`
Creates or styles a line layer as a flow-arrow layer.

### `generate_hu_huanyong_line(line_name="Hu Huanyong Line", start_point=None, end_point=None, crs="EPSG:4326", add_label=True, map_session=None)`
Creates the classic Hu Huanyong line.

### `generate_dynamic_hu_huanyong_line(layer_name|layer_id, weight_field, output_name="Hu Huanyong Comparison", target_share=0.94, angle_range_degrees=20, angle_steps=41, shift_steps=81, add_labels=True, map_session=None)`
Fits a dynamic Hu Huanyong line and optionally registers it into a map session.

### `set_layer_labels(layer_name|layer_id, field=None, expression=None, font="Arial", size=10, color="#1f2933", buffer_color="#ffffff", buffer_size=1.0, placement=None, scale_visibility=None, map_session=None)`
Configures labels and optionally keeps the target layer inside a session-driven map.

### `customize_layout_legend(layout_name="GeoAI_Output", title="Legend", layer_order=None, hidden_layers=None, patch_size=None, fonts=None, auto_update=False, map_session=None)`
Customizes the legend of a layout. With `map_session`, the legend is derived only from that session's layers.

### `embed_chart(layer_name|layer_id, chart_type="bar", category_field=None, value_field=None, aggregation="sum", title="GeoAI Chart", dock_preview=True, layout_embed=True, layout_name="GeoAI_Output", position=None, map_session=None, reference_layers=None, extent_mode="session_union", chart_slot=None)`
Renders a chart and optionally embeds it into a layout.

- Default behavior is one chart per session/layout.
- Reuse the same `map_session` to place multiple charts into the same layout intentionally.
- Use `chart_slot` to control replacement vs multiple positions inside one shared session.

### `query_attributes(layer_name|layer_id, filters=None, fields=None, limit=50, order_by=None, select_on_map=True, zoom_to_selection=False)`
Queries attribute records and can highlight results on the map.

### `run_population_attraction_model(origins_layer, destinations_layer, origin_pop_field, destination_pop_field, distance_source="centroid", beta=2.0, output_type="lines", map_session=None)`
Runs a population attraction model and optionally registers the output into a session.

### `style_population_attraction_result(layer_name|layer_id, field="score", style_mode="graduated", classes=5, color_ramp="Magma", color="#e76f51", map_session=None)`
Styles the attraction-model result and optionally registers it into a session.

### `create_terrain_profile(terrain_layer_name|terrain_layer_id, terrain_type="auto", elevation_field=None, profile_layer_name|profile_layer_id=None, profile_points=None, sample_distance=None, title="Terrain Profile", map_session=None)`
Creates a terrain profile chart from a DEM raster or contour line layer.

- `terrain_type="auto"` treats raster input as DEM and line input as contours.
- Contour input requires `elevation_field` unless the plugin can auto-detect a suitable numeric field.
- `profile_points` should contain at least two points in current project coordinates.
- Returns a profile chart image in `artifacts.chart_image`, the line layer in `artifacts.profile_line_layer`, and a derived DEM in `artifacts.dem_layer` when contours are interpolated.

### `create_terrain_model(terrain_layer_name|terrain_layer_id, terrain_type="auto", elevation_field=None, grid_spacing=None, vertical_exaggeration=1.5, create_hillshade=True, color_ramp="Terrain", title="Simplified Terrain Model", map_session=None)`
Creates a simplified terrain visualization from a DEM raster or contour line layer.

- Raster DEM input is used directly as the surface layer.
- Contour input is interpolated to a DEM first and then styled.
- When `create_hillshade=True`, the response includes `artifacts.hillshade_layer` if a hillshade output is generated.
- `data.used_interpolation` indicates whether the tool had to derive a DEM from contour input.

## Teaching Templates

### `create_population_distribution_map(layer_name|layer_id, value_field, label_field=None, classes=5, mode="jenks", color_ramp="YlOrRd", title="Population Distribution Map", legend_title="Population Distribution", auto_layout=False, layout_name="GeoAI_Output", export_path=None, map_session=None, reference_layers=None, extent_mode="session_union")`
Creates a choropleth-style population distribution map.

### `create_population_density_map(layer_name|layer_id, weight_field=None, radius=15, pixel_size=5, title="Population Density Map", auto_layout=False, layout_name="GeoAI_Output", export_path=None, map_session=None, reference_layers=None, extent_mode="session_union")`
Creates a density or heatmap-style population map.

### `create_population_migration_map(origins_layer, destinations_layer, origin_id_field, destination_id_field, title="Population Migration Map", color="#d1495b", auto_layout=False, layout_name="GeoAI_Output", export_path=None, map_session=None, reference_layers=None, extent_mode="session_union")`
Creates a migration-flow map with isolated session output.

### `create_hu_line_comparison_map(layer_name|layer_id, weight_field, label_field=None, classes=5, color_ramp="YlOrRd", title="Hu Huanyong Line Comparison", auto_layout=False, layout_name="GeoAI_Output", export_path=None, map_session=None, reference_layers=None, extent_mode="session_union")`
Creates a Hu Huanyong comparison map with isolated layout and layer stack.
