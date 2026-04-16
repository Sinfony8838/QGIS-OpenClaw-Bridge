import unittest
from importlib import util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "qgis-solver" / "scripts" / "qgis_client.py"
MODULE_SPEC = util.spec_from_file_location("qgis_client", MODULE_PATH)
QGIS_CLIENT_MODULE = util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(QGIS_CLIENT_MODULE)

QGISClient = QGIS_CLIENT_MODULE.QGISClient


class RecordingQgisClient(QGISClient):
    def __init__(self):
        super().__init__(host="127.0.0.1", port=5555, timeout=10)
        self.calls = []

    def call(self, tool_name, **tool_params):
        self.calls.append((tool_name, tool_params))
        return {"status": "success", "tool_name": tool_name, "tool_params": tool_params}


class QgisClientTerrainToolTest(unittest.TestCase):
    def test_set_layer_visibility_forwards_tool_name_and_params(self):
        client = RecordingQgisClient()
        response = client.set_layer_visibility(layer_name="china_population", visible=False)

        self.assertEqual(client.calls[0][0], "set_layer_visibility")
        self.assertEqual(client.calls[0][1]["layer_name"], "china_population")
        self.assertFalse(client.calls[0][1]["visible"])
        self.assertEqual(response["status"], "success")

    def test_set_active_layer_forwards_tool_name_and_params(self):
        client = RecordingQgisClient()
        response = client.set_active_layer(layer_id="layer_demo")

        self.assertEqual(client.calls[0][0], "set_active_layer")
        self.assertEqual(client.calls[0][1]["layer_id"], "layer_demo")
        self.assertEqual(response["status"], "success")
    def test_set_layer_style_alias_forwards_to_set_style_tool(self):
        client = RecordingQgisClient()
        response = client.set_layer_style(layer_name="中国省份人口", fill_color="#ffff00", outline_color="#333333")

        self.assertEqual(client.calls[0][0], "set_style")
        self.assertEqual(client.calls[0][1]["layer_name"], "中国省份人口")
        self.assertEqual(client.calls[0][1]["fill_color"], "#ffff00")
        self.assertEqual(client.calls[0][1]["outline_color"], "#333333")
        self.assertEqual(response["status"], "success")

    def test_get_layer_style_forwards_tool_name_and_params(self):
        client = RecordingQgisClient()
        response = client.get_layer_style(layer_name="china_population")

        self.assertEqual(client.calls[0][0], "get_layer_style")
        self.assertEqual(client.calls[0][1]["layer_name"], "china_population")
        self.assertEqual(response["status"], "success")

    def test_set_layer_labels_forwards_enabled_flag(self):
        client = RecordingQgisClient()
        response = client.set_layer_labels(layer_name="china_population", enabled=False)

        self.assertEqual(client.calls[0][0], "set_layer_labels")
        self.assertEqual(client.calls[0][1]["layer_name"], "china_population")
        self.assertFalse(client.calls[0][1]["enabled"])
        self.assertEqual(response["status"], "success")

    def test_create_terrain_profile_forwards_tool_name_and_params(self):
        client = RecordingQgisClient()
        response = client.create_terrain_profile(
            terrain_layer_name="dem_surface",
            terrain_type="dem",
            profile_points=[{"x": 0, "y": 0}, {"x": 10, "y": 5}],
            sample_distance=2.5,
            title="Terrain Profile",
            map_session="map_demo",
        )

        self.assertEqual(client.calls[0][0], "create_terrain_profile")
        self.assertEqual(client.calls[0][1]["terrain_layer_name"], "dem_surface")
        self.assertEqual(client.calls[0][1]["profile_points"][1]["y"], 5)
        self.assertEqual(client.calls[0][1]["sample_distance"], 2.5)
        self.assertEqual(response["status"], "success")

    def test_create_terrain_model_forwards_tool_name_and_params(self):
        client = RecordingQgisClient()
        client.create_terrain_model(
            terrain_layer_id="layer_terrain",
            terrain_type="contours",
            elevation_field="elev",
            grid_spacing=30,
            vertical_exaggeration=2.0,
            create_hillshade=False,
            color_ramp="Terrain",
            map_session="map_demo",
        )

        self.assertEqual(client.calls[0][0], "create_terrain_model")
        self.assertEqual(client.calls[0][1]["terrain_layer_id"], "layer_terrain")
        self.assertEqual(client.calls[0][1]["elevation_field"], "elev")
        self.assertEqual(client.calls[0][1]["vertical_exaggeration"], 2.0)
        self.assertFalse(client.calls[0][1]["create_hillshade"])


if __name__ == "__main__":
    unittest.main()
