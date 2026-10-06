"""CPU-only SIM wire checks; no native simulator or provider is contacted."""

import base64
import builtins
import copy
import unittest
from unittest.mock import patch

from benchkit.contracts import Observation, ObservationSpec, Transition
from benchkit.errors import InfrastructureError
from benchkit.sim_server import wire

try:
    import numpy as np
except ImportError:
    np = None


class JsonWireChecks(unittest.TestCase):
    def test_roundtrip(self):
        self.assertEqual(wire.loads(wire.dumps({"text": "机器人", "items": (1, 2.5, True, None)})),
                         {"text": "机器人", "items": [1, 2.5, True, None]})
        self.assertEqual(wire.PROTOCOL, "starvla-rsi.sim-server/v1")
        self.assertTrue(issubclass(wire.WireError, InfrastructureError))

    def test_malformed_messages(self):
        for payload in (b"", b"[]", b"null", b"1", b"{} {}", b"{", b"\xff",
                        b'{"x":1,"x":2}', b'{"nested":{"x":1,"x":2}}',
                        b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}',
                        b'{"x":1e999}', b'{"x":"\\ud800"}', "{}", bytearray(b"{}")):
            with self.subTest(payload=payload), self.assertRaises(wire.WireError):
                wire.loads(payload)

    def test_rejected_values(self):
        for value in ({1: "bad"}, {"x": float("nan")}, {"x": float("inf")},
                      {"x": object()}, {"x": b"bytes"}, {"x": "\ud800"}):
            with self.subTest(value=value), self.assertRaises(wire.WireError):
                wire.dumps(value)

    def test_nesting_and_cycles(self):
        value = {}
        for _ in range(70):
            value = {"nested": value}
        cyclic = {}
        cyclic["cycle"] = cyclic
        for item in (value, cyclic):
            with self.assertRaises(wire.WireError):
                wire.dumps(item)
        with self.assertRaises(wire.WireError):
            wire.loads(b'{"x":' * 70 + b"0" + b"}" * 70)

    def test_bounded_utf8_message(self):
        with patch.object(wire, "MAX_MESSAGE_BYTES", 20):
            with self.assertRaises(wire.WireError):
                wire.dumps({"x": "机" * 5})
            with self.assertRaises(wire.WireError):
                wire.loads(b'{"x":"' + b" " * 20 + b'"}')


class ObservationWireChecks(unittest.TestCase):
    def setUp(self):
        self.spec = ObservationSpec(state_names=("x", "y"))
        self.observation = Observation(0, "Reach", state=(0.25, -1), metadata={"target": [1, 0]})

    def test_no_image_transport_without_numpy(self):
        original = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name == "numpy" or name.startswith("numpy."):
                raise AssertionError("No-image transport must not import NumPy")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded):
            encoded = wire.encode_observation(self.observation, self.spec)
            result = wire.decode_observation(wire.loads(wire.dumps(encoded)), self.spec)
            self.assertEqual(result.state, [0.25, -1.0])
            self.assertEqual(result.metadata, {"target": [1, 0]})
            result.metadata["target"][0] = 9
            self.assertEqual(self.observation.metadata["target"], [1, 0])

    def test_empty_state_requires_none(self):
        spec = ObservationSpec()
        result = wire.decode_observation(wire.encode_observation(Observation(0, ""), spec), spec)
        self.assertIsNone(result.state)
        with self.assertRaises(wire.WireError):
            wire.encode_observation(Observation(0, "", state=()), spec)

    def test_invalid_observation_fields(self):
        encoded = wire.encode_observation(self.observation, self.spec)
        for key, value in (("step", True), ("step", -1), ("step", 1.0), ("instruction", None),
                           ("images", {"undeclared": {}}), ("images", []),
                           ("state", None), ("state", [0]), ("state", [False, 0]),
                           ("state", [float("inf"), 0]), ("metadata", [])):
            candidate = {**encoded, key: value}
            with self.subTest(key=key, value=value), self.assertRaises(wire.WireError):
                wire.decode_observation(candidate, self.spec)
        for candidate in ({**encoded, "private": 1}, {k: v for k, v in encoded.items() if k != "state"}):
            with self.assertRaises(wire.WireError):
                wire.decode_observation(candidate, self.spec)

    def test_private_and_duplicate_specs_rejected(self):
        for spec in (ObservationSpec(privileged=True), ObservationSpec(cameras=("rgb", "rgb")),
                     ObservationSpec(state_names=("x", "x"))):
            with self.assertRaises(wire.WireError):
                wire.encode_observation(Observation(0, ""), spec)

    def test_transition_roundtrip(self):
        transition = Transition(self.observation, 1.25, False, True, {"native_count": 4})
        result = wire.decode_transition(wire.loads(wire.dumps(wire.encode_transition(transition, self.spec))), self.spec)
        self.assertEqual(result.reward, 1.25)
        self.assertFalse(result.terminated)
        self.assertTrue(result.truncated)
        self.assertEqual(result.info, {"native_count": 4})
        self.assertNotIn("native_count", result.observation.metadata)

    def test_invalid_transition_fields(self):
        value = wire.encode_transition(Transition(self.observation), self.spec)
        for key, item in (("reward", True), ("reward", "0"), ("reward", float("nan")),
                          ("terminated", 1), ("truncated", 0), ("info", []),
                          ("info", {"x": float("inf")})):
            with self.subTest(key=key, item=item), self.assertRaises(wire.WireError):
                wire.decode_transition({**value, key: item}, self.spec)
        with self.assertRaises(wire.WireError):
            wire.encode_transition(Transition(self.observation, terminated=1), self.spec)
        with self.assertRaises(wire.WireError):
            wire.decode_transition({**value, "extra": 1}, self.spec)


@unittest.skipIf(np is None, "NumPy is required only for RGB image fixtures")
class ImageWireChecks(unittest.TestCase):
    def setUp(self):
        self.spec = ObservationSpec(cameras=("front", "wrist"))
        self.images = {"front": np.arange(18, dtype=np.uint8).reshape(2, 3, 3),
                       "wrist": np.zeros((1, 2, 3), dtype=np.uint8)}
        self.observation = Observation(3, "Move", images=self.images)

    def encoded(self):
        return wire.encode_observation(self.observation, self.spec)

    def test_rgb_roundtrip_is_independent(self):
        result = wire.decode_observation(wire.loads(wire.dumps(self.encoded())), self.spec)
        for camera, pixels in self.images.items():
            np.testing.assert_array_equal(result.images[camera], pixels)
            self.assertTrue(result.images[camera].flags.writeable)
            self.assertFalse(np.shares_memory(result.images[camera], pixels))
        result.images["front"][0, 0, 0] = 255
        self.assertEqual(self.images["front"][0, 0, 0], 0)

    def test_strided_arrays_encode_in_hwc_order(self):
        self.images["front"] = self.images["front"][:, ::-1, :]
        result = wire.decode_observation(self.encoded(), self.spec)
        np.testing.assert_array_equal(result.images["front"], self.images["front"])

    def test_image_dtype_shape_and_camera_checks(self):
        for image in (np.zeros((2, 2, 3), dtype=np.float32), np.zeros((2, 2), dtype=np.uint8),
                      np.zeros((2, 2, 4), dtype=np.uint8), np.zeros((0, 2, 3), dtype=np.uint8),
                      "local-file.png", [[[0, 0, 0]]]):
            with self.subTest(image_type=type(image)), self.assertRaises(wire.WireError):
                wire.encode_observation(Observation(0, "", images={"front": image, "wrist": self.images["wrist"]}), self.spec)
        with self.assertRaises(wire.WireError):
            wire.encode_observation(Observation(0, "", images={"front": self.images["front"]}), self.spec)

    def test_malformed_rgb_payloads(self):
        original = self.encoded()
        for key, value in (("shape", [True, 6, 3]), ("shape", [2, 3, 4]), ("shape", [0, 1, 3]),
                           ("shape", [2**60, 2**60, 3]), ("dtype", "float32"),
                           ("encoding", "pickle"), ("data", "*" * 24), ("data", ""),
                           ("data", base64.b64encode(b"a" * 17).decode("ascii"))):
            candidate = copy.deepcopy(original)
            candidate["images"]["front"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(wire.WireError):
                wire.decode_observation(candidate, self.spec)
        candidate = copy.deepcopy(original)
        candidate["images"]["front"]["path"] = "/private/file"
        with self.assertRaises(wire.WireError):
            wire.decode_observation(candidate, self.spec)

    def test_total_image_bound(self):
        with patch.object(wire, "MAX_MESSAGE_BYTES", 28):
            with self.assertRaises(wire.WireError):
                self.encoded()
        encoded = self.encoded()
        with patch.object(wire, "MAX_MESSAGE_BYTES", 100):
            with self.assertRaises(wire.WireError):
                wire.decode_observation(encoded, self.spec)

    def test_noncanonical_base64_rejected(self):
        one = ObservationSpec(cameras=("rgb",))
        # RGB byte counts are multiples of three: padding itself is invalid.
        value = wire.encode_observation(Observation(0, "", images={"rgb": np.zeros((1, 1, 3), dtype=np.uint8)}), one)
        value["images"]["rgb"]["data"] = "AAA="
        with self.assertRaises(wire.WireError):
            wire.decode_observation(value, one)


if __name__ == "__main__":
    unittest.main()
