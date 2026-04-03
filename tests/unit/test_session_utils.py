import unittest
from importlib import util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "geoai_agent_plugin" / "services" / "session_utils.py"
MODULE_SPEC = util.spec_from_file_location("session_utils", MODULE_PATH)
SESSION_UTILS = util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(SESSION_UTILS)

build_layer_id_sequence = SESSION_UTILS.build_layer_id_sequence
chart_slot_position = SESSION_UTILS.chart_slot_position
ordered_session_entries = SESSION_UTILS.ordered_session_entries
unique_name = SESSION_UTILS.unique_name


class SessionUtilsTest(unittest.TestCase):
    def test_unique_name_uses_suffix_when_conflict_exists(self):
        result = unique_name("GeoAI_Output", {"GeoAI_Output"}, suffix_hint="map_1_demo")
        self.assertEqual(result, "GeoAI_Output_map_1_demo")

    def test_unique_name_adds_numeric_suffix_when_needed(self):
        result = unique_name(
            "GeoAI_Output",
            {"GeoAI_Output", "GeoAI_Output_map_1_demo", "GeoAI_Output_map_1_demo_2"},
            suffix_hint="map_1_demo",
        )
        self.assertEqual(result, "GeoAI_Output_map_1_demo_3")

    def test_ordered_session_entries_sorts_top_layers_first(self):
        entries = [
            {"layer_id": "polygon", "layer_name": "polygon", "role": "polygon", "order": 1},
            {"layer_id": "heatmap", "layer_name": "heatmap", "role": "surface", "order": 2},
            {"layer_id": "points", "layer_name": "points", "role": "point", "order": 3},
        ]
        ordered = ordered_session_entries(entries)
        self.assertEqual([entry["layer_id"] for entry in ordered], ["points", "heatmap", "polygon"])

    def test_build_layer_id_sequence_skips_hidden_layout_entries(self):
        entries = [
            {"layer_id": "points", "layer_name": "points", "role": "point", "order": 1, "include_in_layout": True},
            {"layer_id": "temp", "layer_name": "temp", "role": "polygon", "order": 2, "include_in_layout": False},
            {"layer_id": "heatmap", "layer_name": "heatmap", "role": "surface", "order": 3, "include_in_layout": True},
        ]
        self.assertEqual(build_layer_id_sequence(entries), ["points", "heatmap"])

    def test_chart_slot_position_tiles_two_columns(self):
        primary = chart_slot_position(0)
        secondary = chart_slot_position(1)
        third = chart_slot_position(2)
        self.assertEqual(primary["x"], secondary["x"] - (primary["width"] + 8.0))
        self.assertEqual(primary["y"], secondary["y"])
        self.assertEqual(third["y"], primary["y"] + primary["height"] + 8.0)


if __name__ == "__main__":
    unittest.main()
