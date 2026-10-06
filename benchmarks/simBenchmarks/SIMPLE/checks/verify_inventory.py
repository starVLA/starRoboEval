"""Read-only native source/reset inventory audit; never imports a simulator.

Only Python source and released DR0 meta/episodes.jsonl are read. The optional
--emit mode prints reviewable inventory JSON; it never writes a pin or asset.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path


BACKENDS = {
    ("simple.envs.loco_manipulation:LocoManipulationEnv", "g1_wholebody"): "amo",
    ("simple.envs.sonic_loco_manip:SonicLocoManipEnv", "g1_sonic"): "sonic",
}
REVISION = "5e3d6f84e85343e34e9bca8d157f0d7813231185"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def collect(simple_root, eval_root):
    """Resolve released identities through native Gym registration and task AST."""
    root, data = Path(simple_root), Path(eval_root) / "simple-eval"
    registration_path = root / "src/simple/envs/__init__.py"
    registrations = {}
    for node in ast.walk(ast.parse(registration_path.read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "register":
            fields = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords}
            registrations[fields["id"].removeprefix("simple/")] = fields
    tasks = []
    for path in sorted(data.glob("*/dr-level-0/meta/episodes.jsonl")):
        task_id = path.parents[2].name
        registration = registrations[task_id]
        uid = registration["kwargs"]["task"]
        relative = f"src/simple/tasks/{uid}.py"
        source = (root / relative).read_bytes()
        tree = ast.parse(source)
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        fields = {node.target.id: node.value for node in cls.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}
        if ast.literal_eval(fields["uid"]) != uid:
            raise ValueError(f"native task UID mismatch: {task_id}")
        metadata = ast.literal_eval(fields["metadata"])
        robot = {kw.arg: ast.literal_eval(kw.value) for kw in fields["robot_cfg"].keywords}["uid"]
        backend = BACKENDS.get((registration["entry_point"], robot))
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if [row["episode_index"] for row in rows] != list(range(10)):
            raise ValueError(f"expected ten ordered released DR0 episodes: {task_id}")
        serialized = rows[0]["environment_config"]
        conf = json.loads(serialized)
        if conf["uid"] != uid or conf["robot_cfg"]["uid"] != robot:
            raise ValueError(f"released task/robot differs from implementation: {task_id}")
        # Every selected native reset uses this exact language formatting rule.
        instructions = [node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Attribute) and t.attr == "_instruction" for t in node.targets)
            and isinstance(node.value, ast.Call)]
        if len(instructions) != 1 or ast.unparse(instructions[0]) != "language_template.format(self._target.asset.name)":
            raise ValueError(f"native instruction construction changed: {task_id}")
        state = conf["dr_state_dict"]
        tasks.append({
            "task_id": task_id, "task_uid": uid, "env_entry_point": registration["entry_point"],
            "robot_uid": robot, "backend": backend,
            "backend_gate": None if backend else "unsupported native environment/robot pair",
            "reference_native_horizon": metadata["max_episode_steps"],
            "native_metadata": metadata, "released_metadata": conf["metadata"],
            "instruction": state["language"].format(state["target"]["name"]),
            "dr_level": 0, "episode_index": 0, "released_episode_count": len(rows),
            "scene_uid": state["scene"]["uid"],
            "native_source": relative, "native_source_sha256": sha256(source),
            "reset_metadata_sha256": sha256(path.read_bytes()),
            "environment_config_sha256": sha256(serialized.encode()),
        })
    if len(tasks) != 12:
        raise ValueError(f"expected the frozen 12 released tasks, got {len(tasks)}")
    return {"schema": "simple-released-task-inventory/v1", "revision": REVISION,
        "scope": "released-12", "order": "lexicographic native task ID", "task_count": 12,
        "registration_source_sha256": sha256(registration_path.read_bytes()), "tasks": tasks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simple-root", default="/mnt/workspace/users/jinhuiye/SIMPLE-5e3d6f8")
    parser.add_argument("--eval-root", default="/mnt/workspace/users/jinhuiye/SIMPLE/data/evals")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args()
    actual = collect(args.simple_root, args.eval_root)
    if args.emit:
        print(json.dumps(actual, indent=2))
        return
    if args.inventory is None:
        parser.error("--inventory is required unless --emit is selected")
    if json.loads(args.inventory.read_text()) != actual:
        raise ValueError("frozen SIMPLE inventory differs from native source/released metadata")
    print("Verified all 12 native registrations, robots/backends, horizons and DR0 episode-0 metadata pins; no native execution.")


if __name__ == "__main__":
    main()
