import json
import socket


DEFAULT_LAYOUT_NAME = "GeoAI_Output"


class QGISClient:
    def __init__(self, host="127.0.0.1", port=5555, timeout=10):
        self.host = host
        self.port = port
        self.timeout = timeout

    def _recv_exact(self, sock, size):
        buffer = b""
        while len(buffer) < size:
            chunk = sock.recv(size - len(buffer))
            if not chunk:
                raise ConnectionError("Socket closed before full response was received")
            buffer += chunk
        return buffer

    def call(self, tool_name, **tool_params):
        payload = json.dumps({"tool_name": tool_name, "tool_params": tool_params}).encode("utf-8")
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.sendall(len(payload).to_bytes(4, "big") + payload)
            message_length = int.from_bytes(self._recv_exact(sock, 4), "big")
            response = json.loads(self._recv_exact(sock, message_length).decode("utf-8"))
        return response

    # Core
    def get_layers(self):
        return self.call("get_layers")

    def add_layer_from_path(self, file_path, layer_name="New Layer", map_session=None, role=None):
        return self.call("add_layer_from_path", file_path=file_path, layer_name=layer_name, map_session=map_session, role=role)

    def run_algorithm(self, algorithm_id, params, load_result=True, map_session=None, role=None):
        return self.call("run_algorithm", algorithm_id=algorithm_id, params=params, load_result=load_result, map_session=map_session, role=role)

    def get_algorithm_help(self, algorithm_id):
        return self.call("get_algorithm_help", algorithm_id=algorithm_id)

    def fly_to(self, lat, lon, scale):
        return self.call("fly_to", lat=lat, lon=lon, scale=scale)

    def zoom_to_layer(self, layer_id=None, layer_name=None):
        return self.call("zoom_to_layer", layer_id=layer_id, layer_name=layer_name)

    def set_layer_visibility(self, layer_id=None, layer_name=None, visible=True):
        return self.call("set_layer_visibility", layer_id=layer_id, layer_name=layer_name, visible=visible)

    def set_active_layer(self, layer_id=None, layer_name=None):
        return self.call("set_active_layer", layer_id=layer_id, layer_name=layer_name)

    def update_banner(self, text):
        return self.call("update_banner", text=text)

    def set_background_color(self, color="#ffffff"):
        return self.call("set_background_color", color=color)

    def auto_layout(
        self,
        title="GeoAI Output",
        paper_size="A4",
        layout_name=DEFAULT_LAYOUT_NAME,
        map_session=None,
        reference_layers=None,
        extent_mode="session_union",
    ):
        return self.call(
            "auto_layout",
            title=title,
            paper_size=paper_size,
            layout_name=layout_name,
            map_session=map_session,
            reference_layers=reference_layers,
            extent_mode=extent_mode,
        )

    def export_map(self, file_path, layout_name=DEFAULT_LAYOUT_NAME, map_session=None):
        return self.call("export_map", file_path=file_path, layout_name=layout_name, map_session=map_session)

    # Experimental
    def run_python_code(self, code, result_var="result"):
        return self.call("run_python_code", code=code, result_var=result_var)

    # Layer preparation
    def prepare_layer(self, layer_id=None, layer_name=None, fix_geometry=True, reproject_to=None, force_points=False, map_session=None):
        return self.call(
            "prepare_layer",
            layer_id=layer_id,
            layer_name=layer_name,
            fix_geometry=fix_geometry,
            reproject_to=reproject_to,
            force_points=force_points,
            map_session=map_session,
        )

    def calculate_field(self, layer_id=None, layer_name=None, field_name=None, expression=None, field_type="double"):
        return self.call(
            "calculate_field",
            layer_id=layer_id,
            layer_name=layer_name,
            field_name=field_name,
            expression=expression,
            field_type=field_type,
        )

    def filter_layer(self, layer_id=None, layer_name=None, expression=None, output_name=None, map_session=None):
        return self.call(
            "filter_layer",
            layer_id=layer_id,
            layer_name=layer_name,
            expression=expression,
            output_name=output_name,
            map_session=map_session,
        )

    def join_attributes(self, target_layer, join_layer, target_field, join_field, fields=None, map_session=None):
        return self.call(
            "join_attributes",
            target_layer=target_layer,
            join_layer=join_layer,
            target_field=target_field,
            join_field=join_field,
            fields=fields,
            map_session=map_session,
        )

    def create_centroids(self, layer_id=None, layer_name=None, output_name=None, map_session=None):
        return self.call("create_centroids", layer_id=layer_id, layer_name=layer_name, output_name=output_name, map_session=map_session)

    def create_connection_lines(self, origins_layer, destinations_layer, origin_id_field, destination_id_field, output_name=None, map_session=None):
        return self.call(
            "create_connection_lines",
            origins_layer=origins_layer,
            destinations_layer=destinations_layer,
            origin_id_field=origin_id_field,
            destination_id_field=destination_id_field,
            output_name=output_name,
            map_session=map_session,
        )

    def set_layer_z_order(self, layer_id=None, layer_name=None, position="top"):
        return self.call("set_layer_z_order", layer_id=layer_id, layer_name=layer_name, position=position)

    def move_layer(self, layer_id=None, layer_name=None, position="top"):
        return self.set_layer_z_order(layer_id=layer_id, layer_name=layer_name, position=position)

    # Cartography
    def set_style(self, layer_id=None, layer_name=None, style_type="single", map_session=None, **properties):
        return self.call("set_style", layer_id=layer_id, layer_name=layer_name, style_type=style_type, map_session=map_session, **properties)

    def set_layer_style(self, layer_id=None, layer_name=None, style_type="single", map_session=None, **properties):
        return self.set_style(layer_id=layer_id, layer_name=layer_name, style_type=style_type, map_session=map_session, **properties)

    def get_layer_style(self, layer_id=None, layer_name=None):
        return self.call("get_layer_style", layer_id=layer_id, layer_name=layer_name)

    def apply_graduated_renderer(
        self,
        layer_id=None,
        layer_name=None,
        field=None,
        mode="jenks",
        classes=5,
        color_ramp="Viridis",
        precision=2,
        label_format="{lower} - {upper}",
        map_session=None,
    ):
        return self.call(
            "apply_graduated_renderer",
            layer_id=layer_id,
            layer_name=layer_name,
            field=field,
            mode=mode,
            classes=classes,
            color_ramp=color_ramp,
            precision=precision,
            label_format=label_format,
            map_session=map_session,
        )

    def create_heatmap(
        self,
        layer_id=None,
        layer_name=None,
        radius=15,
        pixel_size=5,
        weight_field=None,
        output_mode="memory",
        map_session=None,
    ):
        return self.call(
            "create_heatmap",
            layer_id=layer_id,
            layer_name=layer_name,
            radius=radius,
            pixel_size=pixel_size,
            weight_field=weight_field,
            output_mode=output_mode,
            map_session=map_session,
        )

    def create_flow_arrows(
        self,
        layer_id=None,
        layer_name=None,
        start_x=None,
        start_y=None,
        end_x=None,
        end_y=None,
        width_field=None,
        color="#d1495b",
        scale_mode="fixed",
        map_session=None,
    ):
        return self.call(
            "create_flow_arrows",
            layer_id=layer_id,
            layer_name=layer_name,
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            width_field=width_field,
            color=color,
            scale_mode=scale_mode,
            map_session=map_session,
        )

    def generate_hu_huanyong_line(
        self,
        line_name="Hu Huanyong Line",
        start_point=None,
        end_point=None,
        crs="EPSG:4326",
        add_label=True,
        map_session=None,
    ):
        return self.call(
            "generate_hu_huanyong_line",
            line_name=line_name,
            start_point=start_point,
            end_point=end_point,
            crs=crs,
            add_label=add_label,
            map_session=map_session,
        )

    def generate_dynamic_hu_huanyong_line(
        self,
        layer_id=None,
        layer_name=None,
        weight_field=None,
        output_name="Hu Huanyong Comparison",
        target_share=0.94,
        angle_range_degrees=20,
        angle_steps=41,
        shift_steps=81,
        add_labels=True,
        map_session=None,
    ):
        return self.call(
            "generate_dynamic_hu_huanyong_line",
            layer_id=layer_id,
            layer_name=layer_name,
            weight_field=weight_field,
            output_name=output_name,
            target_share=target_share,
            angle_range_degrees=angle_range_degrees,
            angle_steps=angle_steps,
            shift_steps=shift_steps,
            add_labels=add_labels,
            map_session=map_session,
        )

    def customize_layout_legend(
        self,
        layout_name=DEFAULT_LAYOUT_NAME,
        title="Legend",
        layer_order=None,
        hidden_layers=None,
        patch_size=None,
        fonts=None,
        auto_update=False,
        map_session=None,
    ):
        return self.call(
            "customize_layout_legend",
            layout_name=layout_name,
            title=title,
            layer_order=layer_order,
            hidden_layers=hidden_layers,
            patch_size=patch_size,
            fonts=fonts,
            auto_update=auto_update,
            map_session=map_session,
        )

    def set_layer_labels(
        self,
        layer_id=None,
        layer_name=None,
        enabled=True,
        field=None,
        expression=None,
        font="Arial",
        size=10,
        color="#1f2933",
        buffer_color="#ffffff",
        buffer_size=1.0,
        placement=None,
        scale_visibility=None,
        map_session=None,
    ):
        return self.call(
            "set_layer_labels",
            layer_id=layer_id,
            layer_name=layer_name,
            enabled=enabled,
            field=field,
            expression=expression,
            font=font,
            size=size,
            color=color,
            buffer_color=buffer_color,
            buffer_size=buffer_size,
            placement=placement,
            scale_visibility=scale_visibility,
            map_session=map_session,
        )

    def query_attributes(
        self,
        layer_id=None,
        layer_name=None,
        filters=None,
        fields=None,
        limit=50,
        order_by=None,
        select_on_map=True,
        zoom_to_selection=False,
    ):
        return self.call(
            "query_attributes",
            layer_id=layer_id,
            layer_name=layer_name,
            filters=filters,
            fields=fields,
            limit=limit,
            order_by=order_by,
            select_on_map=select_on_map,
            zoom_to_selection=zoom_to_selection,
        )

    def embed_chart(
        self,
        layer_id=None,
        layer_name=None,
        chart_type="bar",
        category_field=None,
        value_field=None,
        aggregation="sum",
        title="GeoAI Chart",
        dock_preview=True,
        layout_embed=True,
        layout_name=DEFAULT_LAYOUT_NAME,
        position=None,
        map_session=None,
        reference_layers=None,
        extent_mode="session_union",
        chart_slot=None,
    ):
        return self.call(
            "embed_chart",
            layer_id=layer_id,
            layer_name=layer_name,
            chart_type=chart_type,
            category_field=category_field,
            value_field=value_field,
            aggregation=aggregation,
            title=title,
            dock_preview=dock_preview,
            layout_embed=layout_embed,
            layout_name=layout_name,
            position=position,
            map_session=map_session,
            reference_layers=reference_layers,
            extent_mode=extent_mode,
            chart_slot=chart_slot,
        )

    def run_population_attraction_model(
        self,
        origins_layer,
        destinations_layer,
        origin_pop_field,
        destination_pop_field,
        distance_source="centroid",
        beta=2.0,
        output_type="lines",
        map_session=None,
    ):
        return self.call(
            "run_population_attraction_model",
            origins_layer=origins_layer,
            destinations_layer=destinations_layer,
            origin_pop_field=origin_pop_field,
            destination_pop_field=destination_pop_field,
            distance_source=distance_source,
            beta=beta,
            output_type=output_type,
            map_session=map_session,
        )

    def style_population_attraction_result(
        self,
        layer_id=None,
        layer_name=None,
        field="score",
        style_mode="graduated",
        classes=5,
        color_ramp="Magma",
        color="#e76f51",
        map_session=None,
    ):
        return self.call(
            "style_population_attraction_result",
            layer_id=layer_id,
            layer_name=layer_name,
            field=field,
            style_mode=style_mode,
            classes=classes,
            color_ramp=color_ramp,
            color=color,
            map_session=map_session,
        )

    def create_terrain_profile(
        self,
        terrain_layer_id=None,
        terrain_layer_name=None,
        terrain_type="auto",
        elevation_field=None,
        profile_layer_id=None,
        profile_layer_name=None,
        profile_points=None,
        sample_distance=None,
        title="Terrain Profile",
        map_session=None,
    ):
        return self.call(
            "create_terrain_profile",
            terrain_layer_id=terrain_layer_id,
            terrain_layer_name=terrain_layer_name,
            terrain_type=terrain_type,
            elevation_field=elevation_field,
            profile_layer_id=profile_layer_id,
            profile_layer_name=profile_layer_name,
            profile_points=profile_points,
            sample_distance=sample_distance,
            title=title,
            map_session=map_session,
        )

    def create_terrain_model(
        self,
        terrain_layer_id=None,
        terrain_layer_name=None,
        terrain_type="auto",
        elevation_field=None,
        grid_spacing=None,
        vertical_exaggeration=1.5,
        create_hillshade=True,
        color_ramp="Terrain",
        title="Simplified Terrain Model",
        map_session=None,
    ):
        return self.call(
            "create_terrain_model",
            terrain_layer_id=terrain_layer_id,
            terrain_layer_name=terrain_layer_name,
            terrain_type=terrain_type,
            elevation_field=elevation_field,
            grid_spacing=grid_spacing,
            vertical_exaggeration=vertical_exaggeration,
            create_hillshade=create_hillshade,
            color_ramp=color_ramp,
            title=title,
            map_session=map_session,
        )

    # Teaching templates
    def create_population_distribution_map(
        self,
        layer_id=None,
        layer_name=None,
        value_field=None,
        label_field=None,
        classes=5,
        mode="jenks",
        color_ramp="YlOrRd",
        title="Population Distribution Map",
        legend_title="Population Distribution",
        auto_layout=False,
        layout_name=DEFAULT_LAYOUT_NAME,
        export_path=None,
        map_session=None,
        reference_layers=None,
        extent_mode="session_union",
    ):
        return self.call(
            "create_population_distribution_map",
            layer_id=layer_id,
            layer_name=layer_name,
            value_field=value_field,
            label_field=label_field,
            classes=classes,
            mode=mode,
            color_ramp=color_ramp,
            title=title,
            legend_title=legend_title,
            auto_layout=auto_layout,
            layout_name=layout_name,
            export_path=export_path,
            map_session=map_session,
            reference_layers=reference_layers,
            extent_mode=extent_mode,
        )

    def create_population_density_map(
        self,
        layer_id=None,
        layer_name=None,
        weight_field=None,
        radius=15,
        pixel_size=5,
        title="Population Density Map",
        auto_layout=False,
        layout_name=DEFAULT_LAYOUT_NAME,
        export_path=None,
        map_session=None,
        reference_layers=None,
        extent_mode="session_union",
    ):
        return self.call(
            "create_population_density_map",
            layer_id=layer_id,
            layer_name=layer_name,
            weight_field=weight_field,
            radius=radius,
            pixel_size=pixel_size,
            title=title,
            auto_layout=auto_layout,
            layout_name=layout_name,
            export_path=export_path,
            map_session=map_session,
            reference_layers=reference_layers,
            extent_mode=extent_mode,
        )

    def create_population_migration_map(
        self,
        origins_layer,
        destinations_layer,
        origin_id_field,
        destination_id_field,
        title="Population Migration Map",
        color="#d1495b",
        auto_layout=False,
        layout_name=DEFAULT_LAYOUT_NAME,
        export_path=None,
        map_session=None,
        reference_layers=None,
        extent_mode="session_union",
    ):
        return self.call(
            "create_population_migration_map",
            origins_layer=origins_layer,
            destinations_layer=destinations_layer,
            origin_id_field=origin_id_field,
            destination_id_field=destination_id_field,
            title=title,
            color=color,
            auto_layout=auto_layout,
            layout_name=layout_name,
            export_path=export_path,
            map_session=map_session,
            reference_layers=reference_layers,
            extent_mode=extent_mode,
        )

    def create_hu_line_comparison_map(
        self,
        layer_id=None,
        layer_name=None,
        weight_field=None,
        label_field=None,
        classes=5,
        color_ramp="YlOrRd",
        title="Hu Huanyong Line Comparison",
        auto_layout=False,
        layout_name=DEFAULT_LAYOUT_NAME,
        export_path=None,
        map_session=None,
        reference_layers=None,
        extent_mode="session_union",
    ):
        return self.call(
            "create_hu_line_comparison_map",
            layer_id=layer_id,
            layer_name=layer_name,
            weight_field=weight_field,
            label_field=label_field,
            classes=classes,
            color_ramp=color_ramp,
            title=title,
            auto_layout=auto_layout,
            layout_name=layout_name,
            export_path=export_path,
            map_session=map_session,
            reference_layers=reference_layers,
            extent_mode=extent_mode,
        )


qgis_client = QGISClient()
