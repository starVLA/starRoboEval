"""Native CALVIN long-horizon chains and initial states, in pure Python (no NumPy, no pyhash).

Mirrors calvin_agent/evaluation/multistep_sequences.py:get_sequences(1000) and
utils.py:get_env_state_for_initial_condition at the pinned CALVIN revision.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
import random

from benchkit.errors import CompatibilityError

NUM_SEQUENCES = 1000  # Native evaluate_policy.py NUM_SEQUENCES.
SEQUENCE_LENGTH = 5
# sha256 of canonical_json() over long_horizon_sequences.json's chains.
SEQUENCES_SHA256 = "90191d9ac76baecb4f292ab766bbbf3ae65dbf43a83bbe5c376d99db10fd6446"

# Native task_categories: a chain never repeats a category.
TASK_CATEGORIES = {
    "rotate_red_block_right": 1, "rotate_red_block_left": 1,
    "rotate_blue_block_right": 1, "rotate_blue_block_left": 1,
    "rotate_pink_block_right": 1, "rotate_pink_block_left": 1,
    "push_red_block_right": 1, "push_red_block_left": 1,
    "push_blue_block_right": 1, "push_blue_block_left": 1,
    "push_pink_block_right": 1, "push_pink_block_left": 1,
    "move_slider_left": 2, "move_slider_right": 2,
    "open_drawer": 3, "close_drawer": 3,
    "lift_red_block_table": 4, "lift_red_block_slider": 5, "lift_red_block_drawer": 6,
    "lift_blue_block_table": 4, "lift_blue_block_slider": 5, "lift_blue_block_drawer": 6,
    "lift_pink_block_table": 4, "lift_pink_block_slider": 5, "lift_pink_block_drawer": 6,
    "place_in_slider": 7, "place_in_drawer": 7,
    "turn_on_lightbulb": 8, "turn_off_lightbulb": 8, "turn_on_led": 8, "turn_off_led": 8,
    "push_into_drawer": 9, "stack_block": 10, "unstack_block": 11,
}

_SLIDERS = ["slider_right", "slider_left"]
# Native symbolic `tasks` table: (condition, effect) variants. Key order matters:
# np.random.choice draws from list(tasks.keys()).
TASKS = {
    "rotate_red_block_right": [({"red_block": "table", "grasped": 0}, {"red_block": "table"})],
    "rotate_red_block_left": [({"red_block": "table", "grasped": 0}, {"red_block": "table"})],
    "rotate_blue_block_right": [({"blue_block": "table", "grasped": 0}, {"blue_block": "table"})],
    "rotate_blue_block_left": [({"blue_block": "table", "grasped": 0}, {"blue_block": "table"})],
    "rotate_pink_block_right": [({"pink_block": "table", "grasped": 0}, {"pink_block": "table"})],
    "rotate_pink_block_left": [({"pink_block": "table", "grasped": 0}, {"pink_block": "table"})],
    "push_red_block_right": [({"red_block": "table", "grasped": 0}, {"red_block": "table"})],
    "push_red_block_left": [({"red_block": "table", "grasped": 0}, {"red_block": "table"})],
    "push_blue_block_right": [({"blue_block": "table", "grasped": 0}, {"blue_block": "table"})],
    "push_blue_block_left": [({"blue_block": "table", "grasped": 0}, {"blue_block": "table"})],
    "push_pink_block_right": [({"pink_block": "table", "grasped": 0}, {"pink_block": "table"})],
    "push_pink_block_left": [({"pink_block": "table", "grasped": 0}, {"pink_block": "table"})],
    "move_slider_left": [({"slider": "right", "grasped": 0}, {"slider": "left"})],
    "move_slider_right": [({"slider": "left", "grasped": 0}, {"slider": "right"})],
    "open_drawer": [({"drawer": "closed", "grasped": 0}, {"drawer": "open"})],
    "close_drawer": [({"drawer": "open", "grasped": 0}, {"drawer": "closed"})],
    "lift_red_block_table": [({"red_block": "table", "grasped": 0}, {"red_block": "grasped", "grasped": 1})],
    "lift_red_block_slider": [
        ({"red_block": "slider_left", "slider": "right", "grasped": 0}, {"red_block": "grasped", "grasped": 1}),
        ({"red_block": "slider_right", "slider": "left", "grasped": 0}, {"red_block": "grasped", "grasped": 1}),
    ],
    "lift_red_block_drawer": [
        ({"red_block": "drawer", "drawer": "open", "grasped": 0}, {"red_block": "grasped", "grasped": 1})],
    "lift_blue_block_table": [({"blue_block": "table", "grasped": 0}, {"blue_block": "grasped", "grasped": 1})],
    "lift_blue_block_slider": [
        ({"blue_block": "slider_left", "slider": "right", "grasped": 0}, {"blue_block": "grasped", "grasped": 1}),
        ({"blue_block": "slider_right", "slider": "left", "grasped": 0}, {"blue_block": "grasped", "grasped": 1}),
    ],
    "lift_blue_block_drawer": [
        ({"blue_block": "drawer", "drawer": "open", "grasped": 0}, {"blue_block": "grasped", "grasped": 1})],
    "lift_pink_block_table": [({"pink_block": "table", "grasped": 0}, {"pink_block": "grasped", "grasped": 1})],
    "lift_pink_block_slider": [
        ({"pink_block": "slider_left", "slider": "right", "grasped": 0}, {"pink_block": "grasped", "grasped": 1}),
        ({"pink_block": "slider_right", "slider": "left", "grasped": 0}, {"pink_block": "grasped", "grasped": 1}),
    ],
    "lift_pink_block_drawer": [
        ({"pink_block": "drawer", "drawer": "open", "grasped": 0}, {"pink_block": "grasped", "grasped": 1})],
    "place_in_slider": [
        ({"red_block": "grasped", "slider": "right", "grasped": 1}, {"red_block": "slider_right", "grasped": 0}),
        ({"red_block": "grasped", "slider": "left", "grasped": 1}, {"red_block": "slider_left", "grasped": 0}),
        ({"blue_block": "grasped", "slider": "right", "grasped": 1}, {"blue_block": "slider_right", "grasped": 0}),
        ({"blue_block": "grasped", "slider": "left", "grasped": 1}, {"blue_block": "slider_left", "grasped": 0}),
        ({"pink_block": "grasped", "slider": "right", "grasped": 1}, {"pink_block": "slider_right", "grasped": 0}),
        ({"pink_block": "grasped", "slider": "left", "grasped": 1}, {"pink_block": "slider_left", "grasped": 0}),
    ],
    "place_in_drawer": [
        ({"red_block": "grasped", "drawer": "open", "grasped": 1}, {"red_block": "drawer", "grasped": 0}),
        ({"blue_block": "grasped", "drawer": "open", "grasped": 1}, {"blue_block": "drawer", "grasped": 0}),
        ({"pink_block": "grasped", "drawer": "open", "grasped": 1}, {"pink_block": "drawer", "grasped": 0}),
    ],
    "stack_block": [
        ({"red_block": "grasped", "blue_block": "table", "grasped": 1},
         {"red_block": "stacked_top", "blue_block": "stacked_bottom", "grasped": 0}),
        ({"red_block": "grasped", "pink_block": "table", "grasped": 1},
         {"red_block": "stacked_top", "pink_block": "stacked_bottom", "grasped": 0}),
        ({"blue_block": "grasped", "red_block": "table", "grasped": 1},
         {"blue_block": "stacked_top", "red_block": "stacked_bottom", "grasped": 0}),
        ({"blue_block": "grasped", "pink_block": "table", "grasped": 1},
         {"blue_block": "stacked_top", "pink_block": "stacked_bottom", "grasped": 0}),
        ({"pink_block": "grasped", "red_block": "table", "grasped": 1},
         {"pink_block": "stacked_top", "red_block": "stacked_bottom", "grasped": 0}),
        ({"pink_block": "grasped", "blue_block": "table", "grasped": 1},
         {"pink_block": "stacked_top", "blue_block": "stacked_bottom", "grasped": 0}),
    ],
    "unstack_block": [
        ({"red_block": "stacked_top", "blue_block": "stacked_bottom", "grasped": 0},
         {"red_block": "table", "blue_block": "table"}),
        ({"red_block": "stacked_top", "pink_block": "stacked_bottom", "grasped": 0},
         {"red_block": "table", "pink_block": "table"}),
        ({"blue_block": "stacked_top", "red_block": "stacked_bottom", "grasped": 0},
         {"blue_block": "table", "red_block": "table"}),
        ({"blue_block": "stacked_top", "pink_block": "stacked_bottom", "grasped": 0},
         {"blue_block": "table", "pink_block": "table"}),
        ({"pink_block": "stacked_top", "red_block": "stacked_bottom", "grasped": 0},
         {"pink_block": "table", "red_block": "table"}),
        ({"pink_block": "stacked_top", "blue_block": "stacked_bottom", "grasped": 0},
         {"pink_block": "table", "blue_block": "table"}),
    ],
    "turn_on_lightbulb": [({"lightbulb": 0, "grasped": 0}, {"lightbulb": 1})],
    "turn_off_lightbulb": [({"lightbulb": 1, "grasped": 0}, {"lightbulb": 0})],
    "turn_on_led": [({"led": 0, "grasped": 0}, {"led": 1})],
    "turn_off_led": [({"led": 1, "grasped": 0}, {"led": 0})],
    "push_into_drawer": [
        ({"red_block": "table", "blue_block": _SLIDERS, "pink_block": _SLIDERS, "drawer": "open", "grasped": 0},
         {"red_block": "drawer", "grasped": 0}),
        ({"blue_block": "table", "red_block": _SLIDERS, "pink_block": _SLIDERS, "drawer": "open", "grasped": 0},
         {"blue_block": "drawer", "grasped": 0}),
        ({"pink_block": "table", "blue_block": _SLIDERS, "red_block": _SLIDERS, "drawer": "open", "grasped": 0},
         {"pink_block": "drawer", "grasped": 0}),
    ],
}

# Native get_sequences possible_conditions; dict order is the product order.
POSSIBLE_CONDITIONS = {
    "led": [0, 1], "lightbulb": [0, 1], "slider": ["right", "left"], "drawer": ["closed", "open"],
    "red_block": ["table", "slider_right", "slider_left"],
    "blue_block": ["table", "slider_right", "slider_left"],
    "pink_block": ["table", "slider_right", "slider_left"],
    "grasped": [0],
}


class LegacyRandomState:
    """The subset of numpy.random.RandomState (legacy MT19937) the native code uses.

    CPython's `random` is the same MT19937 generator: after numpy's integer
    seeding of the 624-word key, getrandbits(32) is one next_uint32 and random()
    is numpy's 53-bit next_double.
    """

    def __init__(self, seed: int):
        key, value = [], seed & 0xFFFFFFFF
        for position in range(624):  # numpy mt19937_seed (Knuth init_genrand)
            key.append(value)
            value = (1812433253 * (value ^ (value >> 30)) + position + 1) & 0xFFFFFFFF
        self._mt = random.Random()
        self._mt.setstate((3, tuple(key) + (624,), None))

    def interval(self, maximum: int) -> int:
        """numpy random_interval: masked rejection sampling in [0, maximum]."""
        if maximum == 0:
            return 0
        mask = (1 << maximum.bit_length()) - 1
        while True:
            value = self._mt.getrandbits(32) & mask
            if value <= maximum:
                return value

    def shuffle(self, items: list) -> None:
        for i in reversed(range(1, len(items))):  # legacy shuffle, typed or untyped path
            j = self.interval(i)
            items[i], items[j] = items[j], items[i]

    def choice_without_replacement(self, population, size: int) -> list:
        order = list(range(len(population)))  # legacy choice: permutation(pop_size)[:size]
        self.shuffle(order)
        return [population[index] for index in order[:size]]

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self._mt.random()


def _matches(state, condition):  # native check_condition
    return all(state[key] in value if isinstance(value, list) else state[key] == value
               for key, value in condition.items())


def _check_sequence(state, sequence):  # native check_sequence
    for task in sequence:
        successors = [{**state, **effect} for condition, effect in TASKS[task] if _matches(state, condition)]
        if len(successors) != 1:
            return False
        state = successors[0]
    categories = [TASK_CATEGORIES[task] for task in sequence]
    return len(categories) == len(set(categories))


def initial_conditions():
    """Native get_sequences initial states: 192 symbolic conditions."""
    def accepted(values):
        return (values.count("table") in [1, 2] and values.count("slider_right") < 2
                and values.count("slider_left") < 2)
    return [dict(zip(POSSIBLE_CONDITIONS, values))
            for values in itertools.product(*POSSIBLE_CONDITIONS.values()) if accepted(values)]


def regenerate():
    """Native get_sequences(1000) from scratch: about 7.1M permutation draws, ~1 min."""
    states = initial_conditions()
    each, extra = divmod(NUM_SEQUENCES, len(states))  # np.array_split section sizes
    counts = [each + 1] * extra + [each] * (len(states) - extra)
    names = list(TASKS)
    results = []
    for index, (state, count) in enumerate(zip(states, counts)):  # get_sequences_for_state2
        rng, found = LegacyRandomState(index), []
        while len(found) < count:
            sequence = rng.choice_without_replacement(names, SEQUENCE_LENGTH)
            if _check_sequence(state, sequence):
                found.append(tuple(sequence))
        results.extend((dict(state), sequence) for sequence in found)
    LegacyRandomState(0).shuffle(results)  # np.random.shuffle under temp_seed(0)
    return results


def canonical_json(chains) -> bytes:
    rows = [[condition, list(tasks)] for condition, tasks in chains]
    return json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()


def sequences():
    """The tracked 1,000 (initial condition, five tasks) chains, hash-checked and feasible."""
    record = json.loads(Path(__file__).with_name("long_horizon_sequences.json").read_bytes())
    rows = record.get("chains") if isinstance(record, dict) else None
    if not isinstance(rows, list) or record.get("schema") != "starvla-rsi.calvin.long-horizon-sequences/v1":
        raise CompatibilityError("CALVIN long-horizon sequence schema differs")
    conditions = initial_conditions()
    chains = []
    for row in rows:
        if (not isinstance(row, list) or len(row) != 2 or row[0] not in conditions
                or list(row[0]) != list(POSSIBLE_CONDITIONS) or not isinstance(row[1], list)
                or len(row[1]) != SEQUENCE_LENGTH or not set(row[1]) <= set(TASKS)
                or not _check_sequence(row[0], row[1])):
            raise CompatibilityError("CALVIN long-horizon chain is not a feasible native chain")
        chains.append((row[0], tuple(row[1])))
    # Regenerating takes about a minute, so startup compares the tracked list
    # to the pin; verify_regeneration() reproduces it from the native algorithm.
    if len(chains) != NUM_SEQUENCES or hashlib.sha256(canonical_json(chains)).hexdigest() != SEQUENCES_SHA256:
        raise CompatibilityError("CALVIN long-horizon sequences differ from the pinned list")
    return chains


def verify_regeneration():
    """Offline reproducibility check: regenerated chains equal the tracked, pinned list."""
    if regenerate() != sequences():
        raise CompatibilityError("CALVIN regenerated sequences differ from the tracked list")
    return SEQUENCES_SHA256


def fnv1_32(data: bytes, value: int = 0) -> int:
    """pyhash.fnv1_32(): FNV-1 with pyhash's default seed 0, not the FNV offset basis."""
    for byte in data:
        value = ((value * 0x01000193) & 0xFFFFFFFF) ^ byte
    return value


def condition_seed(condition) -> int:
    # Native: hasher(str(initial_condition.values())). pyhash hashes a Python 3
    # str on Linux as UTF-16 without its byte-order mark (little-endian x86).
    return fnv1_32(str(condition.values()).encode("utf-16-le"))


ROBOT_OBS = (0.02586889, -0.2313129, 0.5712808, 3.09045411, -0.02908596, 1.50013585, 0.07999963,
             -1.21779124, 1.03987629, 2.11978254, -2.34205014, -0.87015899, 1.64119093, 0.55344928, 1.0)
_SLIDER_LEFT = (-2.40851662e-01, 9.24044687e-02, 4.60990009e-01)
_SLIDER_RIGHT = (7.03416330e-02, 9.24044687e-02, 4.60990009e-01)
_TABLE = ((5.00000896e-02, -1.20000177e-01, 4.59990009e-01), (2.29995412e-01, -1.19995140e-01, 4.59990010e-01))


def env_state(condition):
    """Native get_env_state_for_initial_condition: (15 robot, 24 scene) values."""
    rng = LegacyRandomState(condition_seed(condition))
    table = list(_TABLE)
    rng.shuffle(table)
    low, high = math.pi / 2 - math.pi / 8, math.pi / 2 + math.pi / 8
    scene = [0.0] * 24
    if condition["slider"] == "left":
        scene[0] = 0.28
    if condition["drawer"] == "open":
        scene[1] = 0.22
    if condition["lightbulb"] == 1:
        scene[3] = 0.088
    scene[4], scene[5] = float(condition["lightbulb"]), float(condition["led"])
    places = {"slider_right": _SLIDER_RIGHT, "slider_left": _SLIDER_LEFT}
    # Red, blue, pink at scene[6:9], [12:15], [18:21]; z rotation at 11, 17, 23 (draw order is native).
    scene[6:9] = places.get(condition["red_block"], table[0])
    scene[11] = rng.uniform(low, high)
    blue = places.get(condition["blue_block"], table[1] if condition["red_block"] == "table" else table[0])
    scene[12:15] = blue
    scene[17] = rng.uniform(low, high)
    scene[18:21] = places.get(condition["pink_block"], table[1])
    scene[23] = rng.uniform(low, high)
    return list(ROBOT_OBS), scene
