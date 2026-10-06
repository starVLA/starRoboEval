"""Native eval_policy post-action ordering, isolated for independent regression.

All actors/poses/metrics here are private server state. This wrapper never
creates an action, repeats a control, or calls an expert.
"""
from __future__ import annotations


class NativeOutcome:
    def __init__(self, env, config, tracker_class):
        self.env = env
        self.success = self.finished = self.has_lifted = False
        self.fail_reason = None
        self.check_z_threshold = self.target_actor = self.start_z = None
        self.stop_on_contact = True
        dynamic = getattr(env, "get_dynamic_motion_config", lambda: None)()
        if dynamic and "check_z_threshold" in dynamic:
            self.check_z_threshold = dynamic["check_z_threshold"]
            self.target_actor = dynamic["check_z_actor"] if "check_z_actor" in dynamic else dynamic["target_actor"]
            self.start_z = self.target_actor.get_pose().p[2]
        if dynamic and "stop_on_contact" in dynamic:
            self.stop_on_contact = dynamic["stop_on_contact"]
        self.tracker = tracker_class(env, config)
        self.tracker.on_episode_start()
        env._metrics_tracker = self.tracker

    def after_action(self):
        """Exactly eval_policy's post-eval_func checks, in native order."""
        env = self.env
        if self.check_z_threshold is not None and not self.has_lifted:
            self.has_lifted = self.target_actor.get_pose().p[2] - self.start_z > self.check_z_threshold
        if env.eval_success:
            self.success = self.check_z_threshold is None or self.has_lifted
            self.fail_reason = None if self.success else "object_not_lifted"
            self.finished = True
            return
        if env.use_dynamic:
            if env.check_gripper_contact_dynamic_object() and self.stop_on_contact:
                env.stop_dynamic_object_motion()
            if not getattr(env, "_dynamic_object_stopped", False) and not env.check_dynamic_object_boundary():
                env.eval_fail = True
                self.fail_reason = "out_of_bounds"
                self.tracker.record_out_of_bounds()
                self.finished = True
                return
        if env.eval_fail:
            self.fail_reason = "eval_fail"
            self.finished = True
            return
        self.finished = env.take_action_cnt >= env.step_lim

    def metrics(self, seed):
        value = self.tracker.get_episode_metrics(self.success, self.fail_reason, seed=seed)
        return {"success": bool(value.success), "native_steps": int(value.steps_taken),
                "metrics_tracker_steps": int(value.steps_taken),
                "native_horizon": int(value.max_steps), "route_completion": float(value.route_completion),
                "manipulation_score": float(value.manipulation_score),
                "total_penalty_factor": float(value.total_penalty_factor),
                "fail_reason": value.fail_reason, "native_seed": seed,
                "penalty_events": [{"event_type": p.event_type, "timestep": int(p.timestep),
                                    "penalty_factor": float(p.penalty_factor), "details": p.details}
                                   for p in value.penalty_events]}
