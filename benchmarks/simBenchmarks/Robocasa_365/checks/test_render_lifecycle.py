"""CPU EGL ownership state machine; these are not native rendering evidence."""

import json
import marshal
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter import RoboCasa365BenchmarkAdapter, PILOT_SEED
from benchmarks.simBenchmarks.Robocasa_365.environment import render_lifecycle as repair
from benchkit.errors import CompatibilityError, InfrastructureError


class FakeEGL:
    EGL_DRAW, EGL_READ = 1, 2
    EGL_NO_SURFACE, EGL_NO_CONTEXT = 0, 0

    def __init__(self):
        self.binding = (22, 202, 42, 43, 12450)
        self.contexts = {101, 202, 303}
        self.calls = []
        self.fail = None
        self.restore_fail = False

    def eglGetCurrentDisplay(self): return self.binding[0]
    def eglGetCurrentContext(self): return self.binding[1]
    def eglGetCurrentSurface(self, which): return self.binding[2 if which == self.EGL_DRAW else 3]
    def eglQueryAPI(self): return self.binding[4]

    def eglBindAPI(self, api):
        self.calls.append(("api", api))
        self.binding = self.binding[:4] + (api,)
        return self.fail != "bind"

    def eglMakeCurrent(self, display, draw, read, context):
        self.calls.append(("make", display, draw, read, context))
        if (context and context not in self.contexts) or (self.restore_fail and context == 202):
            return False
        self.binding = (display if context else 0, context, draw, read, self.binding[4])
        return self.fail != "make"

    def eglDestroyContext(self, display, context):
        self.calls.append(("destroy", display, context))
        if self.fail == "destroy":
            return False
        self.contexts.remove(context)
        return True

    def eglReleaseThread(self):
        self.calls.append(("release",))
        self.binding = (0, 0, 0, 0, 12448)
        return self.fail != "release"


class LifecycleChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "render_lifecycle.json"
        self.egl = FakeEGL()
        self.gl_error = 0
        self.framebuffers = {101: {1}, 202: {1}, 303: {1}}
        self.freed = []
        self.rendered = []
        self.read = []
        self.resources = []
        test = self

        class Owner:
            def __init__(self, context=101): self._context = context
            def make_current(self):
                if not test.egl.eglMakeCurrent(11, 0, 0, self._context):
                    raise RuntimeError("make owner failed")
            def free(self): raise AssertionError("unsafe original free must not run")

        class Renderer:
            def __init__(self):
                self.gl_ctx = Owner()
                self.con = test.resource()
                self.gl_ctx.make_current()
                test.resources.append(self)
            def render(self, *args, **kwargs):
                self.gl_ctx.make_current()
                test.rendered.append(args)
            def read_pixels(self, *args, **kwargs):
                test.read.append(args)
                return "unchanged native RGB"

        self.Owner, self.Renderer = Owner, Renderer
        self.gl = SimpleNamespace(glGetError=lambda: self.gl_error,
            glIsFramebuffer=lambda fbo: fbo in self.framebuffers.get(self.egl.eglGetCurrentContext(), set()))
        self.guard = repair.LifecycleGuard(self.egl, self.gl, SimpleNamespace(EGL_DISPLAY=11),
                                          Renderer, Owner, {"test_only": True})
        self.originals = {name: vars(Renderer)[name] for name in ("__init__", "render", "read_pixels")}
        self.guard.begin(self.path)
        self.guard.wrap(self.originals)

    def tearDown(self):
        for renderer in self.resources:
            self.guard.destroy_render(renderer)
        self.temp.cleanup()

    def resource(self, callback=None):
        def free():
            current = self.egl.eglGetCurrentContext()
            self.freed.append(current)
            if callback:
                callback()
            self.framebuffers[current].discard(1)
        return SimpleNamespace(free=free, offFBO=1)

    def renderer(self, context=101, callback=None):
        renderer = self.Renderer.__new__(self.Renderer)
        renderer.gl_ctx = self.Owner(context)
        renderer.con = self.resource(callback)
        self.resources.append(renderer)
        self.guard.live.add(renderer)
        return renderer

    def test_destroy_frees_in_owner_and_restores_full_other_binding_and_api(self):
        previous = self.egl.binding
        renderer = self.renderer()
        self.guard.destroy_render(renderer)
        self.assertEqual(self.freed, [101])
        self.assertEqual(self.egl.binding, previous)
        self.assertEqual(self.framebuffers[202], {1})
        self.assertEqual(self.guard.error_count, 0)
        self.assertNotIn(101, self.egl.contexts)
        self.assertFalse(hasattr(renderer, "con"))

    def test_does_not_restore_destroyed_current_owner(self):
        renderer = self.renderer()
        renderer.gl_ctx.make_current()
        self.guard.destroy_render(renderer)
        self.assertEqual(self.egl.eglGetCurrentContext(), 0)
        self.assertEqual(self.guard.error_count, 0)
        self.assertFalse(any(c[0] == "make" and c[-1] == 101 for c in self.egl.calls[self.egl.calls.index(("destroy", 11, 101)) + 1:]))

    def test_no_prior_context_is_preserved(self):
        self.egl.binding = (0, 0, 0, 0, 12448)
        renderer = self.renderer()
        self.guard.destroy_render(renderer)
        self.assertEqual(self.egl.binding, (0, 0, 0, 0, 12448))

    def test_direct_egl_free_restores_foreign_context_and_surfaces(self):
        previous = self.egl.binding
        self.Owner().free()
        self.assertEqual(self.egl.binding, previous)
        self.assertEqual(self.guard.error_count, 0)

    def test_egl_partial_initialization_without_context_is_safe(self):
        owner = self.Owner.__new__(self.Owner)
        owner.free()
        self.assertEqual(self.guard.error_count, 0)
        self.assertEqual(self.egl.calls, [])

    def test_render_partial_initialization_only_gl_owner(self):
        renderer = self.renderer()
        del renderer.con
        self.guard.destroy_render(renderer)
        self.assertNotIn(101, self.egl.contexts)
        self.assertEqual(self.guard.error_count, 0)

    def test_render_partial_initialization_without_any_resource(self):
        renderer = self.Renderer.__new__(self.Renderer)
        self.resources.append(renderer)
        self.guard.destroy_render(renderer)
        self.assertEqual(self.guard.error_count, 0)

    def test_resource_without_owner_is_quarantined_and_blocks_boundary(self):
        renderer = self.renderer()
        del renderer.gl_ctx
        self.guard.destroy_render(renderer)
        self.assertEqual(self.freed, [])
        self.assertIn(renderer, self.guard.quarantine)
        with self.assertRaises(InfrastructureError):
            self.guard.check("before_observation_release")
        self.assertEqual(json.loads(self.path.read_text())["status"], "faulted")

    def test_repeated_and_same_object_reentrant_cleanup_are_idempotent(self):
        renderer = self.renderer()
        renderer.con = self.resource(lambda: self.guard.destroy_render(renderer))
        self.guard.destroy_render(renderer)
        self.guard.destroy_render(renderer)
        self.assertEqual(self.freed, [101])
        self.assertEqual(sum(c[0] == "destroy" for c in self.egl.calls), 1)
        self.assertEqual(self.guard.counts["reentrant_cleanup_calls"], 2)

    def test_other_object_reentrant_cleanup_restores_outer_owner(self):
        nested = self.renderer(303)
        previous = self.egl.binding
        outer = self.renderer(callback=lambda: self.guard.destroy_render(nested))
        self.guard.destroy_render(outer)
        self.assertEqual(self.freed, [101, 303])
        self.assertEqual(self.egl.binding, previous)
        self.assertEqual(self.guard.error_count, 0)

    def test_con_free_exception_is_durable_despite_finalizer_not_raising(self):
        renderer = self.renderer(callback=lambda: (_ for _ in ()).throw(RuntimeError("injected free fault")))
        previous = self.egl.binding
        self.guard.destroy_render(renderer)
        self.assertEqual(self.egl.binding, previous)
        self.assertIn(101, self.egl.contexts)
        data = json.loads(self.path.read_text())
        self.assertEqual(data["status"], "faulted")
        self.assertIn("injected free fault", data["errors"][0]["message"])
        with self.assertRaises(InfrastructureError): self.guard.check("metrics")

    def test_false_destroy_return_is_not_silently_swallowed(self):
        renderer = self.renderer()
        self.egl.fail = "destroy"
        self.guard.destroy_render(renderer)
        self.assertGreater(self.guard.error_count, 0)
        self.assertIn(101, self.egl.contexts)
        self.assertEqual(self.egl.eglGetCurrentContext(), 202)

    def test_release_failure_does_not_restore_a_destroyed_owner(self):
        renderer = self.renderer()
        renderer.gl_ctx.make_current()
        self.egl.fail = "release"
        self.guard.destroy_render(renderer)
        self.assertGreater(self.guard.error_count, 0)
        self.assertNotIn(101, self.egl.contexts)
        self.assertEqual(self.egl.eglGetCurrentContext(), 0)

    def test_failed_previous_binding_restore_is_sticky(self):
        renderer = self.renderer()
        self.egl.restore_fail = True
        self.guard.destroy_render(renderer)
        with self.assertRaises(InfrastructureError): self.guard.check("release")
        self.assertIn("render_restore", [r["phase"] for r in json.loads(self.path.read_text())["errors"]])

    def test_cleanup_on_foreign_thread_performs_no_egl_operation(self):
        renderer = self.renderer()
        thread = threading.Thread(target=lambda: self.guard.destroy_render(renderer))
        thread.start()
        thread.join()
        self.assertEqual(self.egl.calls, [])
        with self.assertRaises(InfrastructureError): self.guard.check("release")

    def test_readback_in_wrong_context_fails_before_native_read(self):
        renderer = self.renderer()
        with self.assertRaises(InfrastructureError): renderer.read_pixels(256, 256)
        self.assertEqual(self.read, [])

    def test_destroyed_framebuffer_fails_before_native_read(self):
        renderer = self.renderer()
        renderer.gl_ctx.make_current()
        self.framebuffers[101].clear()
        with self.assertRaises(InfrastructureError): renderer.read_pixels(256, 256)
        self.assertEqual(self.read, [])

    def test_native_post_read_error_prevents_array_release(self):
        renderer = self.renderer()
        renderer.gl_ctx.make_current()
        def broken(*args, **kwargs):
            self.gl_error = 1282
            return "uninitialized native data"
        self.originals["read_pixels"] = broken
        with self.assertRaises(InfrastructureError): renderer.read_pixels(256, 256)
        self.assertEqual(self.guard.counts["readback_calls"], 0)

    def test_valid_native_pixels_unchanged_and_counts_checked(self):
        renderer = self.renderer()
        renderer.render(256, 256)
        self.assertEqual(renderer.read_pixels(256, 256), "unchanged native RGB")
        self.assertEqual(self.guard.counts["render_calls"], 1)
        self.assertEqual(self.guard.counts["readback_calls"], 1)

    def test_gc_equivalent_inside_native_readback_restores_live_framebuffer(self):
        retired = self.renderer(303)
        active = self.renderer(101)
        active.gl_ctx.make_current()
        previous = self.egl.binding
        def read(*args, **kwargs):
            self.guard.destroy_render(retired)
            return "unchanged native RGB"
        self.originals["read_pixels"] = read
        self.assertEqual(active.read_pixels(256, 256), "unchanged native RGB")
        self.assertEqual(self.egl.binding, previous)
        self.assertEqual(self.framebuffers[101], {1})

    def test_constructor_failure_is_sticky_and_partial_owner_released(self):
        def broken(renderer):
            renderer.gl_ctx = self.Owner()
            raise RuntimeError("partial native init")
        self.originals["__init__"] = broken
        renderer = self.Renderer.__new__(self.Renderer)
        self.resources.append(renderer)
        with self.assertRaises(RuntimeError): renderer.__init__()
        self.guard.destroy_render(renderer)
        self.assertNotIn(101, self.egl.contexts)
        with self.assertRaises(InfrastructureError): self.guard.check("release")

    def test_overwritten_patch_is_detected(self):
        self.Renderer.render = lambda *args: None
        with self.assertRaises(InfrastructureError): self.guard.check("release")

    def test_receipt_write_failure_blocks_observation(self):
        with patch.object(repair, "atomic_write_json", side_effect=OSError("disk unavailable")):
            with self.assertRaises(InfrastructureError): self.guard.check("release", persist=True)
        self.guard.persist()
        self.assertEqual(json.loads(self.path.read_text())["status"], "faulted")

    def test_finalizer_fault_during_receipt_write_is_flushed_as_faulted(self):
        native_write = repair.atomic_write_json
        count = 0
        def interrupted(path, data):
            nonlocal count
            count += 1
            if count == 1:
                self.guard.fault("destructor_during_receipt_write", RuntimeError("injected cleanup fault"))
            native_write(path, data)
        self.guard.closed = True
        with patch.object(repair, "atomic_write_json", side_effect=interrupted):
            with self.assertRaises(InfrastructureError): self.guard.check("after_close", persist=True)
        self.assertEqual(count, 2)
        receipt = json.loads(self.path.read_text())
        self.assertEqual(receipt["status"], "faulted")
        self.assertEqual(receipt["error_count"], 1)
        self.assertEqual(receipt["errors"][0]["phase"], "destructor_during_receipt_write")

    def test_second_session_requires_closed_and_no_live_contexts(self):
        with self.assertRaises(CompatibilityError): self.guard.begin(self.path.parent / "second.json")
        renderer = self.renderer()
        with self.assertRaises(InfrastructureError): self.guard.finish()
        self.assertEqual(json.loads(self.path.read_text())["status"], "faulted")
        self.guard.destroy_render(renderer)

    def test_clean_close_is_durable_and_allows_new_receipt(self):
        renderer = self.renderer()
        self.guard.destroy_render(renderer)
        self.guard.finish()
        before = self.path.read_bytes()
        self.guard.begin(self.path.parent / "second.json")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(json.loads(before)["status"], "closed")


class TrackChecks(unittest.TestCase):
    def test_code_pin_accepts_equivalent_pyc_code_but_rejects_changed_constants(self):
        original = compile("def outer(value):\n    return lambda: value + 17\n", "pinned-source.py", "exec")
        cached = marshal.loads(marshal.dumps(original))
        self.assertTrue(repair._same_code(original, cached))
        changed = compile("def outer(value):\n    return lambda: value + 18\n", "pinned-source.py", "exec")
        self.assertFalse(repair._same_code(original, changed))
        relocated = compile("def outer(value):\n    return lambda: value + 17\n", "other-source.py", "exec")
        self.assertFalse(repair._same_code(original, relocated))
        self.assertFalse(repair._same_code(original, original.replace(co_code=b"\x09\x00")))
        self.assertFalse(repair._same_code(original, original.replace(co_flags=original.co_flags ^ 0x100)))
        self.assertFalse(repair._same_constant((True,), (1,)))
        self.assertFalse(repair._same_constant(frozenset([True]), frozenset([1])))

    def test_legacy_track_remains_explicitly_unchanged_protocol(self):
        native = RoboCasa365BenchmarkAdapter()
        repaired = RoboCasa365BenchmarkAdapter(render_track=repair.TRACK)
        self.assertEqual(native.descriptor.protocol_version, "target-first2-development/rgb/native-horizons/v1")
        self.assertEqual(repaired.descriptor.protocol_version,
                         "target-first2-development/rgb/native-horizons/egl-owner-restore-v1/v2")
        self.assertEqual(native.action_spec, repaired.action_spec)
        self.assertEqual(native.observation_spec, repaired.observation_spec)
        self.assertEqual(native.environment_step_cap, repaired.environment_step_cap)
        self.assertEqual([e.task for e in native.episodes(PILOT_SEED)], [e.task for e in repaired.episodes(PILOT_SEED)])
        with self.assertRaises(ValueError): RoboCasa365BenchmarkAdapter(render_track="automatic")

    def test_native_track_rejects_already_patched_process(self):
        with patch.object(repair, "_ACTIVE", object()):
            with self.assertRaises(CompatibilityError): repair.require_native_track()

    def test_material_track_is_distinct_and_cross_track_process_reuse_fails(self):
        material = RoboCasa365BenchmarkAdapter(render_track=repair.MATERIAL_TRACK)
        old = RoboCasa365BenchmarkAdapter(render_track=repair.TRACK)
        self.assertTrue(material.descriptor.protocol_version.endswith("/egl-owner-material-clamp-v1/v3"))
        self.assertTrue(old.descriptor.protocol_version.endswith("/egl-owner-restore-v1/v2"))
        self.assertEqual(material.action_spec, old.action_spec)
        self.assertEqual(material.observation_spec, old.observation_spec)
        with patch.object(repair, "_ACTIVE", SimpleNamespace(track=repair.TRACK)):
            with self.assertRaises(CompatibilityError):
                repair.install(Path("unused"), Path("unused"), track=repair.MATERIAL_TRACK)

    def test_sticky_guard_blocks_observation_metrics_and_artifacts(self):
        adapter = RoboCasa365BenchmarkAdapter(render_track=repair.TRACK)
        session = adapter.open_episode(adapter.episodes(PILOT_SEED)[0])
        session.renderer_guard = SimpleNamespace(check=lambda *args, **kwargs: (_ for _ in ()).throw(InfrastructureError("sticky")))
        for call in (lambda: session._observe({}), session.metrics, session.artifacts):
            with self.assertRaises(InfrastructureError): call()


class MaterialChecks(unittest.TestCase):
    class Geom:
        def __init__(self, value):
            self.value, self.writes = value, []
        @property
        def shininess(self):
            return self.value
        @shininess.setter
        def shininess(self, value):
            self.writes.append(value)
            self.value = value

    def setUp(self):
        class Renderer:
            def __init__(self): pass
            def render(self): pass
            def read_pixels(self): pass
        class EGLClass: pass
        self.renderer = Renderer()
        self.renderer.scn = SimpleNamespace(ngeom=0, geoms=[])
        self.renderer.con = object()
        self.native_calls = []
        def native(*args, **kwargs):
            self.native_calls.append((args, kwargs, [g.shininess for g in self.renderer.scn.geoms]))
            return "native output"
        self.module = SimpleNamespace(mjr_render=native)
        self.native = native
        self.guard = repair.LifecycleGuard(None, None, None, Renderer, EGLClass, {},
                                          track=repair.MATERIAL_TRACK, mujoco_module=self.module)
        self.guard.active_renderer = self.renderer
        self.guard.live.add(self.renderer)
        self.originals = {name: vars(Renderer)[name] for name in ("__init__", "render", "read_pixels")}

    def values(self, values, count=None):
        self.renderer.scn.geoms = [self.Geom(v) for v in values]
        self.renderer.scn.ngeom = len(values) if count is None else count

    def call(self, native=None, **changes):
        args = {"viewport": object(), "scn": self.renderer.scn, "con": self.renderer.con, **changes}
        return self.guard.material_draw(native or self.native, **args)

    def test_both_bounds_are_clipped_only_during_draw_and_restored(self):
        self.values([-1., 2., .375, -0., 0., 1.])
        self.assertEqual(self.call(), "native output")
        self.assertEqual(self.native_calls[0][2], [0., 1., .375, -0., 0., 1.])
        self.assertEqual([g.shininess for g in self.renderer.scn.geoms], [-1., 2., .375, -0., 0., 1.])
        self.assertEqual([g.writes for g in self.renderer.scn.geoms], [[0., -1.], [1., 2.], [], [], [], []])
        self.assertEqual(self.guard.counts["material_geometries_clamped"], 2)
        self.assertEqual(self.guard.counts["material_draw_calls"], 1)

    def test_native_render_exception_restores_every_scene_value(self):
        self.values([-1., 2.])
        def broken(**kwargs): raise RuntimeError("native draw fault")
        with self.assertRaisesRegex(RuntimeError, "native draw fault"): self.call(broken)
        self.assertEqual([g.shininess for g in self.renderer.scn.geoms], [-1., 2.])

    def test_nonfinite_is_rejected_before_any_assignment_or_draw(self):
        for invalid in (float("nan"), float("inf"), -float("inf")):
            self.values([-1., invalid])
            with self.assertRaises(InfrastructureError): self.call()
            self.assertEqual([g.writes for g in self.renderer.scn.geoms], [[], []])
        self.assertEqual(self.native_calls, [])

    def test_geometry_beyond_native_ngeom_is_not_inspected_or_changed(self):
        self.values([-1., float("nan")], count=1)
        self.call()
        self.assertEqual(self.renderer.scn.geoms[1].writes, [])

    def test_unmanaged_renderer_or_different_scene_and_context_rejected(self):
        self.values([-1.])
        for params in ({"scn": object()}, {"con": object()}):
            with self.assertRaises(InfrastructureError): self.call(**params)
        self.guard.active_renderer = None
        with self.assertRaises(InfrastructureError): self.call()
        self.assertEqual(self.native_calls, [])

    def test_foreign_thread_fails_before_scene_writes(self):
        self.values([-1.])
        errors = []
        def run():
            try: self.call()
            except Exception as exc: errors.append(exc)
        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
        self.assertTrue(errors)
        self.assertEqual(self.renderer.scn.geoms[0].writes, [])

    def test_bad_signature_and_geometry_bound_are_rejected(self):
        self.values([])
        for count in (-1, 10001):
            self.renderer.scn.ngeom = count
            with self.assertRaises(InfrastructureError): self.call()
        with self.assertRaises(InfrastructureError):
            self.guard.material_draw(self.native, object(), self.renderer.scn)

    def test_native_model_and_xml_are_not_modified(self):
        self.values([-1.])
        model = SimpleNamespace(material_shininess=[-1.], xml=b'<material shininess="-1"/>')
        self.renderer.model = model
        self.call()
        self.assertEqual(model.material_shininess, [-1.])
        self.assertEqual(model.xml, b'<material shininess="-1"/>')

    def test_material_hook_is_installed_only_for_new_track(self):
        self.values([-1.])
        self.guard.wrap(self.originals)
        self.assertIsNot(self.module.mjr_render, self.native)
        self.module.mjr_render(object(), self.renderer.scn, self.renderer.con)
        self.assertEqual(self.native_calls[0][2], [0.])
        self.assertEqual(self.renderer.scn.geoms[0].shininess, -1.)

    def test_old_track_never_installs_material_hook(self):
        self.guard.track = repair.TRACK
        self.guard.wrap(self.originals)
        self.assertIs(self.module.mjr_render, self.native)
        self.assertIsNone(self.guard.receipt()["material_transform"])

    def test_draw_without_managed_context_is_sticky_through_hook(self):
        self.guard.wrap(self.originals)
        self.guard.active_renderer = None
        with self.assertRaises(InfrastructureError):
            self.module.mjr_render(object(), self.renderer.scn, self.renderer.con)
        self.assertEqual(self.guard.errors[-1]["phase"], "material_draw")

    def test_scene_restore_failure_is_sticky_and_not_claimed_success(self):
        class RefusesRestore(self.Geom):
            @self.Geom.shininess.setter
            def shininess(self, value):
                if value == -1.:
                    raise RuntimeError("restore failed")
                self.value = value
        self.renderer.scn.geoms = [RefusesRestore(-1.)]
        self.renderer.scn.ngeom = 1
        with self.assertRaises(InfrastructureError): self.call()
        self.assertEqual(self.guard.errors[0]["phase"], "material_scene_restore")


if __name__ == "__main__":
    unittest.main()
