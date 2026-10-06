"""Dependency-light method declarations; no provider or native environment."""
import copy
import unittest

from benchkit.methods import (METHOD_SCHEMA, USAGE_FIELDS, method_from_policy,
    normalize_method, normalize_usage, normalize_component_usage, sum_component_usage)


def declaration():
    return {"schema_version": METHOD_SCHEMA, "id": "planner-checker", "version": "v1",
            "models": [{"id": "planner", "role": "planning", "model": "declared-model", "provider": None},
                       {"id": "checker", "role": "review", "model": None, "provider": None}],
            "configuration": {"memory": "rolling", "parallel": True}}


class MethodChecks(unittest.TestCase):
    def test_separates_method_from_models_and_preserves_unknowns(self):
        method = normalize_method(declaration())
        self.assertEqual(method["id"], "planner-checker")
        self.assertIsNone(method["models"][1]["model"])
        self.assertIsNone(method["models"][0]["version"])

    def test_normalization_does_not_mutate_input(self):
        original = declaration()
        normalized = normalize_method(original)
        normalized["configuration"]["memory"] = "other"
        self.assertEqual(original["configuration"]["memory"], "rolling")

    def test_legacy_unknown_identity_is_not_inferred_from_profile_name(self):
        method = method_from_policy({"name": "gpt6_astra", "version": "v2", "parameters": {"model": "secret"}})
        self.assertEqual(method["models"], [])
        self.assertEqual(method["configuration"], {})

    def test_legacy_explicit_identity_is_only_a_declaration(self):
        method = method_from_policy({"name": "a-method", "model": "a-model", "provider": "a-provider"})
        self.assertEqual(method["models"][0]["id"], "primary")
        self.assertIsNone(method["models"][0]["version"])

    def test_rejects_duplicate_ids_and_unknown_fields(self):
        for edit in (lambda m: m["models"].append(copy.deepcopy(m["models"][0])),
                     lambda m: m.update(secret="unsafe"),
                     lambda m: m["models"][0].update(receipt="unsafe"),
                     lambda m: m["models"][0].update(id="../../path")):
            value = declaration()
            edit(value)
            with self.assertRaises(ValueError):
                normalize_method(value)

    def test_rejects_configuration_credential_keys_paths_nonfinite_and_unbounded(self):
        variants = [{"nested": {"provider_api_key": "sensitive"}}, {"output": "/private/path"},
                    {"n": float("nan")}, {"items": list(range(9000))}, {"text": "x" * 16385}]
        deep = {}
        for _ in range(10):
            deep = {"next": deep}
        variants.append(deep)
        for config in variants:
            with self.subTest(config_type=type(config)):
                method = declaration()
                method["configuration"] = config
                with self.assertRaises(ValueError):
                    normalize_method(method)

    def test_missing_component_accounting_is_unknown_not_allocated(self):
        rows = normalize_component_usage({"planner": {"calls": 2, "input_tokens": 10}}, declaration())
        self.assertEqual(rows["planner"]["calls"], 2)
        self.assertIsNone(rows["planner"]["latency_s"])
        self.assertTrue(all(value is None for value in rows["checker"].values()))

    def test_component_sum_propagates_unknown_per_field(self):
        left = {"planner": {"calls": 2}, "checker": {"calls": 1}}
        right = {"planner": {"calls": 3}}
        rows = sum_component_usage(left, right, declaration())
        self.assertEqual(rows["planner"]["calls"], 5)
        self.assertIsNone(rows["checker"]["calls"])
        self.assertIsNone(rows["planner"]["estimated_cost_usd"])

    def test_rejects_undeclared_component_negative_boolean_and_nonfinite(self):
        for value in ({"outsider": {}}, {"planner": {"calls": -1}}, {"planner": {"calls": True}},
                      {"planner": {"calls": 1.5}}, {"planner": {"latency_s": float("inf")}},
                      {"planner": {"receipt": "secret"}}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_component_usage(value, declaration())

    def test_empty_usage_has_all_unknown_fields(self):
        self.assertEqual(normalize_usage(None), dict.fromkeys(USAGE_FIELDS))

    def test_cached_tokens_cannot_exceed_known_input_tokens(self):
        with self.assertRaises(ValueError):
            normalize_usage({"input_tokens": 4, "cached_input_tokens": 5})
        self.assertEqual(normalize_usage({"input_tokens": 4, "cached_input_tokens": 4})["cached_input_tokens"], 4)
        self.assertEqual(normalize_usage({"cached_input_tokens": 5})["cached_input_tokens"], 5)


if __name__ == "__main__":
    unittest.main()
