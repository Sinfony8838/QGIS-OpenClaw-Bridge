import unittest
from importlib import util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "geoai_agent_plugin" / "services" / "service_utils.py"
MODULE_SPEC = util.spec_from_file_location("service_utils", MODULE_PATH)
SERVICE_UTILS = util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(SERVICE_UTILS)

is_layer_parameter_definition = SERVICE_UTILS.is_layer_parameter_definition
layout_frame_for_paper = SERVICE_UTILS.layout_frame_for_paper
normalize_paper_size = SERVICE_UTILS.normalize_paper_size
resolve_processing_inputs = SERVICE_UTILS.resolve_processing_inputs
sort_and_limit_rows = SERVICE_UTILS.sort_and_limit_rows


class FakeDefinition:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


FakeFeatureSource = type("QgsProcessingParameterFeatureSource", (FakeDefinition,), {})
FakeString = type("QgsProcessingParameterString", (FakeDefinition,), {})
FakeSink = type("QgsProcessingParameterFeatureSink", (FakeDefinition,), {})


class FakeLayer:
    def __init__(self, layer_id):
        self._layer_id = layer_id

    def id(self):
        return self._layer_id


class ServiceUtilsTest(unittest.TestCase):
    def test_is_layer_parameter_definition_detects_input_layers_only(self):
        self.assertTrue(is_layer_parameter_definition(FakeFeatureSource("INPUT")))
        self.assertFalse(is_layer_parameter_definition(FakeString("FIELD")))
        self.assertFalse(is_layer_parameter_definition(FakeSink("OUTPUT")))

    def test_resolve_processing_inputs_only_resolves_layer_like_params(self):
        alpha_layer = FakeLayer("layer_alpha")
        beta_layer = FakeLayer("layer_beta")

        def resolver(layer_id=None, layer_name=None):
            lookup = {
                "alpha": alpha_layer,
                "beta": beta_layer,
            }
            return lookup.get(layer_name or layer_id)

        fixed, resolved = resolve_processing_inputs(
            params={
                "INPUT": "alpha",
                "FIELD": "alpha",
                "LAYERS": ["alpha", "beta", "missing"],
            },
            definitions=[
                FakeFeatureSource("INPUT"),
                FakeString("FIELD"),
                type("QgsProcessingParameterMultipleLayers", (FakeDefinition,), {})("LAYERS"),
            ],
            layer_resolver=resolver,
        )

        self.assertIs(fixed["INPUT"], alpha_layer)
        self.assertEqual(fixed["FIELD"], "alpha")
        self.assertEqual(fixed["LAYERS"], [alpha_layer, beta_layer, "missing"])
        self.assertEqual([layer.id() for layer in resolved], ["layer_alpha", "layer_beta"])

    def test_sort_and_limit_rows_orders_before_limiting(self):
        rows = [
            {"feature_id": 1, "population": 300},
            {"feature_id": 2, "population": 100},
            {"feature_id": 3, "population": 200},
        ]

        result = sort_and_limit_rows(rows, order_by="population", limit=2)
        self.assertEqual([row["feature_id"] for row in result], [2, 3])

    def test_normalize_paper_size_defaults_to_landscape(self):
        paper = normalize_paper_size("A4")
        self.assertEqual(paper["label"], "A4 landscape")
        self.assertGreater(paper["width"], paper["height"])

    def test_layout_frame_for_paper_scales_map_and_legend(self):
        frame = layout_frame_for_paper("A3 portrait")
        self.assertGreater(frame["paper"]["height"], frame["paper"]["width"])
        self.assertGreater(frame["map"]["height"], frame["legend"]["height"] - 1)
        self.assertGreater(frame["legend"]["x"], frame["map"]["x"])


if __name__ == "__main__":
    unittest.main()
