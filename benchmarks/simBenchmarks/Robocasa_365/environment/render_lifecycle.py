"""Explicit, process-local EGL lifetime compatibility for one pinned native stack.

This module has no simulator imports at module load time. The lifecycle-only
track changes resource ownership/validation. The separate material track also
temporarily bounds scene shininess during a draw and can change pixels; neither
changes model/XML, reset, control or scoring. Native is never silently patched.
A patched process cannot switch tracks.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib
import importlib.metadata
import math
import os
import platform
import threading
import types
import weakref
from pathlib import Path
from typing import Any

from benchkit.artifacts import atomic_write_json
from benchkit.errors import CompatibilityError, InfrastructureError

TRACK = "egl-owner-restore-v1"
MATERIAL_TRACK = "egl-owner-material-clamp-v1"
NATIVE_TRACK = "native-v1"
SOURCE_PINS = {
    "robosuite.utils.binding_utils": "a3d2526fb2e60875e2c3a87b8828b8e3b512781708c80d0c96ee6024980896c8",
    "robosuite.renderers.context.egl_context": "72ff1e153da85b85a35ebd0350c4693d3b89ffd5e1f13ff49813b7a3ad4c51c6",
}
_ACTIVE: Any = None


def require_native_track() -> None:
    if _ACTIVE is not None:
        raise CompatibilityError("native-v1 requires a fresh process without the EGL compatibility track")


def _address(handle: Any) -> int:
    return int(ctypes.cast(handle, ctypes.c_void_p).value or 0)


def _same_code(expected: types.CodeType, actual: types.CodeType) -> bool:
    """Compare code, not marshal's incidental string/reference interning layout."""
    fields = ("co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals",
              "co_stacksize", "co_flags", "co_code", "co_names", "co_varnames",
              "co_freevars", "co_cellvars", "co_name", "co_qualname", "co_filename",
              "co_firstlineno", "co_lnotab", "co_linetable", "co_exceptiontable")
    if any(getattr(expected, field, None) != getattr(actual, field, None) for field in fields):
        return False
    if len(expected.co_consts) != len(actual.co_consts):
        return False
    return all(_same_constant(left, right) for left, right in zip(expected.co_consts, actual.co_consts))


def _same_constant(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, types.CodeType):
        return _same_code(left, right)
    if isinstance(left, tuple):
        return len(left) == len(right) and all(_same_constant(a, b) for a, b in zip(left, right))
    if isinstance(left, frozenset):
        return len(left) == len(right) and all(any(_same_constant(a, b) for b in right) for a in left)
    return left == right


def _source_method(module: Any, cls: type, name: str) -> Any:
    """Reject a replaced Python method, not just a matching on-disk filename."""
    path = Path(module.__file__).resolve(strict=True)
    if path.suffix != ".py" or hashlib.sha256(path.read_bytes()).hexdigest() != SOURCE_PINS[module.__name__]:
        raise CompatibilityError(f"unpinned render source: {module.__name__}")
    method = vars(cls).get(name)
    if (not isinstance(method, types.FunctionType) or method.__globals__ is not vars(module)
            or Path(method.__code__.co_filename).resolve() != path):
        raise CompatibilityError(f"replaced native render method: {cls.__name__}.{name}")
    compiled = compile(path.read_bytes(), method.__code__.co_filename, "exec", dont_inherit=True)
    class_code = next(c for c in compiled.co_consts if isinstance(c, types.CodeType) and c.co_name == cls.__name__)
    expected = next(c for c in class_code.co_consts if isinstance(c, types.CodeType) and c.co_name == name)
    if not _same_code(expected, method.__code__):
        raise CompatibilityError(f"loaded render method differs from pinned source: {cls.__name__}.{name}")
    return method


class LifecycleGuard:
    """Owner-thread guard with sticky, immediately persisted private failures.

    EGL/GL and native classes are injected to allow CPU state-machine regression
    tests. Only ``install`` is a native entrypoint; it verifies all pins first.
    No native render lock is acquired: finalizers can run inside that lock.
    """

    def __init__(self, egl: Any, gl: Any, egl_module: Any, render_class: type,
                 egl_class: type, source_receipt: dict[str, Any], *, track: str = TRACK,
                 mujoco_module: Any = None):
        if track not in (TRACK, MATERIAL_TRACK):
            raise CompatibilityError("unknown EGL compatibility track")
        self.track, self.mujoco_module = track, mujoco_module
        self.active_renderer: Any = None
        self.egl, self.gl, self.egl_module = egl, gl, egl_module
        self.render_class, self.egl_class = render_class, egl_class
        self.source_receipt = source_receipt
        self.owner_thread = threading.get_ident()
        self.receipt_path: Path | None = None
        self.errors: list[dict[str, str]] = []
        self.error_count = 0
        self.counts = {key: 0 for key in (
            "render_contexts_initialized", "render_calls", "readback_calls",
            "native_render_attempts", "native_readback_attempts", "material_transform_attempts",
            "material_draw_calls", "material_geometries_clamped",
            "render_cleanup_calls", "egl_cleanup_calls", "reentrant_cleanup_calls",
            "prior_context_restorations", "no_prior_context_restorations")}
        self.live = weakref.WeakSet()
        self.quarantine: list[Any] = []
        self.expected_methods: list[tuple[type, str, Any]] = []
        self.writing = False
        self.write_pending = False
        self.closed = False

    def begin(self, receipt_path: Path) -> None:
        self.check("begin_session")
        if self.receipt_path is not None and (not self.closed or self.live):
            raise CompatibilityError("finish and release the previous EGL session before opening another")
        path = Path(receipt_path)
        if path.exists():
            raise CompatibilityError("render lifecycle receipt must use a new path")
        self.receipt_path, self.closed = path, False
        self.persist()
        self.check("receipt_created")

    def receipt(self) -> dict[str, Any]:
        return {
            "schema_version": "starvla-rsi.robocasa365.render-lifecycle/v1", "render_track": self.track,
            "status": "faulted" if self.error_count else ("closed" if self.closed else "active"),
            "native_source_unchanged": True, "owner_thread_id": self.owner_thread,
            "same_thread_only": True, "source_binding": self.source_receipt,
            "counts": dict(self.counts), "live_render_contexts": len(self.live),
            "quarantined_objects": len(self.quarantine), "error_count": self.error_count,
            "errors": list(self.errors), "errors_truncated": self.error_count > len(self.errors),
            "scope": "EGL resource ownership and GL error checks; not pixel freshness attestation",
            "counter_semantics": "process cumulative; render_calls/readback_calls count validated returns, not native attempts",
            "material_transform": ({"operation": "temporary expanded-scene shininess clamp to [0,1]",
                "pixels_may_change": True, "native_pixel_parity": False,
                "model_xml_physics_unchanged": True, "restore_scene_after_each_draw": True}
                if self.track == MATERIAL_TRACK else None),
        }

    def persist(self) -> None:
        if self.receipt_path is None:
            return
        if self.writing:
            self.write_pending = True
            return
        self.writing = True
        try:
            # GC can interrupt serialization/replace and record a finalizer
            # error after a healthy receipt snapshot was taken. Flush that
            # pending fault without recursive writes or an unbounded I/O loop.
            for _ in range(3):
                self.write_pending = False
                before = self.error_count
                try:
                    atomic_write_json(self.receipt_path, self.receipt())
                except Exception as exc:
                    self.error_count += 1
                    self.write_pending = True
                    if len(self.errors) < 32:
                        self.errors.append({"phase": "receipt_write", "type": type(exc).__name__, "message": str(exc)[:500]})
                if not self.write_pending and self.error_count == before:
                    break
            else:
                self.error_count += 1
                if len(self.errors) < 32:
                    self.errors.append({"phase": "receipt_write", "type": "RuntimeError",
                                        "message": "bounded receipt flush did not stabilize"})
        finally:
            self.writing = False

    def fault(self, phase: str, exc: Exception) -> None:
        self.error_count += 1
        if len(self.errors) < 32:
            self.errors.append({"phase": phase, "type": type(exc).__name__, "message": str(exc)[:500]})
        self.persist()

    def check(self, phase: str, *, persist: bool = False) -> None:
        if threading.get_ident() != self.owner_thread:
            self.fault(phase, RuntimeError("EGL operations must remain on their installation thread"))
        for cls, name, method in self.expected_methods:
            if vars(cls).get(name) is not method:
                self.fault(phase, RuntimeError(f"render guard replaced: {cls.__name__}.{name}"))
                break
        if persist:
            self.persist()
        if self.error_count:
            raise InfrastructureError(f"{self.track}: sticky renderer fault; inspect evaluator-private render_lifecycle.json")

    def _snapshot(self) -> tuple[Any, Any, Any, Any, Any]:
        e = self.egl
        return (e.eglGetCurrentDisplay(), e.eglGetCurrentContext(),
                e.eglGetCurrentSurface(e.EGL_DRAW), e.eglGetCurrentSurface(e.EGL_READ), e.eglQueryAPI())

    def _bool_call(self, operation: str, *args: Any) -> None:
        if not getattr(self.egl, operation)(*args):
            raise RuntimeError(f"{operation} returned false")

    def _restore(self, previous: tuple[Any, ...], destroyed: int) -> None:
        display, context, draw, read, api = previous
        e = self.egl
        self._bool_call("eglBindAPI", api)
        if _address(context) and _address(context) != destroyed:
            self._bool_call("eglMakeCurrent", display, draw, read, context)
            now = self._snapshot()
            if (tuple(map(_address, now[:4])) != tuple(map(_address, previous[:4]))
                    or int(now[4]) != int(api)):
                raise RuntimeError("EGL previous display/context/read/draw restoration mismatch")
            self.counts["prior_context_restorations"] += 1
        else:
            current_display = e.eglGetCurrentDisplay()
            if _address(e.eglGetCurrentContext()):
                self._bool_call("eglMakeCurrent", current_display, e.EGL_NO_SURFACE,
                                e.EGL_NO_SURFACE, e.EGL_NO_CONTEXT)
            if _address(e.eglGetCurrentContext()):
                raise RuntimeError("EGL cleanup left a context current")
            self.counts["no_prior_context_restorations"] += 1

    def _owner_current(self, owner: Any) -> None:
        owner.make_current()
        if not _address(getattr(owner, "_context", None)) or _address(self.egl.eglGetCurrentContext()) != _address(owner._context):
            raise RuntimeError("EGL owning context did not become current")

    def free_egl(self, owner: Any) -> None:
        """Checked equivalent of native free, with previous binding restoration."""
        if getattr(owner, "_rsi_egl_free_busy", False):
            self.counts["reentrant_cleanup_calls"] += 1
            return
        context = getattr(owner, "_context", None)
        if not _address(context):
            return  # Native initialization can fail before assigning _context.
        owner._rsi_egl_free_busy = True
        previous = None
        destroyed = 0
        error_start = self.error_count
        self.counts["egl_cleanup_calls"] += 1
        try:
            if threading.get_ident() != self.owner_thread:
                raise RuntimeError("EGL cleanup on a foreign thread")
            previous = self._snapshot()
            display = self.egl_module.EGL_DISPLAY
            if _address(self.egl.eglGetCurrentContext()) == _address(context):
                self._bool_call("eglMakeCurrent", display, self.egl.EGL_NO_SURFACE,
                                self.egl.EGL_NO_SURFACE, self.egl.EGL_NO_CONTEXT)
            self._bool_call("eglDestroyContext", display, context)
            destroyed = _address(context)
            owner._context = None
            self._bool_call("eglReleaseThread")
        except Exception as exc:
            self.quarantine.append(owner)
            self.fault("egl_cleanup", exc)
        finally:
            if previous is not None:
                try:
                    self._restore(previous, destroyed)
                except Exception as exc:
                    self.fault("egl_restore", exc)
            owner._rsi_egl_free_busy = False
            self.persist()
        if self.error_count != error_start:
            raise InfrastructureError("EGL cleanup or previous-context restoration failed")

    def destroy_render(self, renderer: Any) -> None:
        """Finalizer cannot raise reliably; record every fault for next boundary."""
        if getattr(renderer, "_rsi_render_cleanup", None) in ("busy", "done"):
            self.counts["reentrant_cleanup_calls"] += 1
            return
        renderer._rsi_render_cleanup = "busy"
        self.counts["render_cleanup_calls"] += 1
        previous = None
        destroyed = 0
        owner = None
        owner_address = 0
        try:
            if threading.get_ident() != self.owner_thread:
                raise RuntimeError("render finalizer on a foreign thread")
            previous = self._snapshot()
            owner = getattr(renderer, "gl_ctx", None)
            con = getattr(renderer, "con", None)
            owner_address = _address(getattr(owner, "_context", None))
            if con is not None:
                if not owner_address:
                    raise RuntimeError("MuJoCo resource exists without its owning EGL context")
                self._owner_current(owner)
                con.free()
                self._gl_errors("mujoco_context_free")
                del renderer.con
            if owner is not None:
                self.free_egl(owner)
                destroyed = owner_address
                del renderer.gl_ctx
            for name in ("scn", "cam", "vopt", "pert"):
                if hasattr(renderer, name):
                    delattr(renderer, name)
            renderer._rsi_render_cleanup = "done"
            self.live.discard(renderer)
        except Exception as exc:
            # Keep failed resources alive: their C/Python finalizers must not
            # later free GPU names in an unrelated context during this process.
            self.quarantine.append(renderer)
            renderer._rsi_render_cleanup = "done"
            self.fault("render_cleanup", exc)
        finally:
            if owner_address and not _address(getattr(owner, "_context", None)):
                destroyed = owner_address
            if previous is not None:
                try:
                    self._restore(previous, destroyed)
                except Exception as exc:
                    self.fault("render_restore", exc)
            self.persist()

    def _gl_errors(self, phase: str) -> None:
        error = int(self.gl.glGetError())
        if error:
            raise RuntimeError(f"{phase}: OpenGL error {error}")

    def _check_readback_context(self, renderer: Any) -> None:
        owner = renderer.gl_ctx
        if _address(self.egl.eglGetCurrentContext()) != _address(owner._context):
            raise RuntimeError("render/readback owning EGL context is not current")
        self._gl_errors("render/readback")
        if int(renderer.con.offFBO) <= 0 or not self.gl.glIsFramebuffer(int(renderer.con.offFBO)):
            raise RuntimeError("render/readback offscreen framebuffer is not live in its owner")
        self._gl_errors("framebuffer_validation")

    def material_draw(self, native_render: Any, *args: Any, **kwargs: Any) -> Any:
        """V3 only: clamp the current draw's expanded scene, never its mjModel.

        OpenGL rejects a shininess exponent outside [0,128]; pinned MuJoCo
        multiplies scene shininess by 128. This is an explicit visual deviation,
        not an error filter. All native GL checks stay enabled afterward.
        """
        self.check("before_material_draw")
        renderer = self.active_renderer
        if (self.track != MATERIAL_TRACK or renderer is None or renderer not in self.live
                or getattr(renderer, "_rsi_render_cleanup", None) is not None):
            raise InfrastructureError("material draw requires the currently managed native renderer")
        if args:
            if len(args) != 3 or kwargs:
                raise InfrastructureError("unexpected native material-draw signature")
            _viewport, scene, context = args
        else:
            if set(kwargs) != {"viewport", "scn", "con"}:
                raise InfrastructureError("unexpected native material-draw keywords")
            scene, context = kwargs["scn"], kwargs["con"]
        if scene is not renderer.scn or context is not renderer.con:
            raise InfrastructureError("material draw scene/context differ from the managed renderer")
        count = int(scene.ngeom)
        if not 0 <= count <= 10000:
            raise InfrastructureError("material draw exceeds the pinned native scene bound")
        self.counts["material_transform_attempts"] += 1
        changes = []
        for index in range(count):
            geom = scene.geoms[index]
            value = float(geom.shininess)
            if not math.isfinite(value):
                raise InfrastructureError("non-finite native scene shininess")
            if not 0 <= value <= 1:
                changes.append((geom, value, min(1.0, max(0.0, value))))
        # Complete validation precedes any assignment, so NaN/inf cannot leave
        # a half-modified scene. Legal values (including -0.0) are never written.
        assigned = []
        try:
            for geom, original, corrected in changes:
                assigned.append((geom, original))
                geom.shininess = corrected
            self.counts["material_geometries_clamped"] += len(changes)
            self.counts["material_draw_calls"] += 1
            return native_render(*args, **kwargs)
        finally:
            restore_errors = []
            for geom, original in reversed(assigned):
                try:
                    geom.shininess = original
                except Exception as exc:
                    restore_errors.append(exc)
            if restore_errors:
                for exc in restore_errors:
                    self.fault("material_scene_restore", exc)
                raise InfrastructureError("temporary material scene values could not be restored")

    def wrap(self, originals: dict[str, Any]) -> None:
        guard = self

        def initialize(renderer, *args, **kwargs):
            guard.check("before_render_context_init")
            guard.live.add(renderer)
            try:
                originals["__init__"](renderer, *args, **kwargs)
                guard.counts["render_contexts_initialized"] += 1
                guard.check("after_render_context_init")
            except Exception as exc:
                guard.fault("render_context_init", exc)
                raise

        def render(renderer, *args, **kwargs):
            guard.check("before_render")
            phase = "before_native_render"
            try:
                guard._owner_current(renderer.gl_ctx)
                guard._check_readback_context(renderer)
                if guard.active_renderer is not None:
                    raise InfrastructureError("reentrant native rendering is unsupported")
                guard.active_renderer = renderer
                phase = "native_render"
                guard.counts["native_render_attempts"] += 1
                try:
                    result = originals["render"](renderer, *args, **kwargs)
                finally:
                    guard.active_renderer = None
                phase = "after_native_render"
                guard._check_readback_context(renderer)
                guard.counts["render_calls"] += 1
                guard.check("after_render")
                return result
            except Exception as exc:
                guard.fault(phase, exc)
                raise InfrastructureError("native render failed closed") from exc

        def read_pixels(renderer, *args, **kwargs):
            guard.check("before_readback")
            phase = "before_native_readback"
            try:
                guard._check_readback_context(renderer)
                phase = "native_readback"
                guard.counts["native_readback_attempts"] += 1
                result = originals["read_pixels"](renderer, *args, **kwargs)
                phase = "after_native_readback"
                guard._check_readback_context(renderer)
                guard.counts["readback_calls"] += 1
                guard.check("after_readback")
                return result
            except Exception as exc:
                guard.fault(phase, exc)
                raise InfrastructureError("native readback failed closed; no RGB released") from exc

        def destroy(renderer):
            guard.destroy_render(renderer)

        def free(owner):
            guard.free_egl(owner)

        for cls, methods in ((self.render_class, {"__init__": initialize, "render": render,
                "read_pixels": read_pixels, "__del__": destroy}), (self.egl_class, {"free": free})):
            for name, method in methods.items():
                setattr(cls, name, method)
                self.expected_methods.append((cls, name, method))
        if self.track == MATERIAL_TRACK:
            if self.mujoco_module is None:
                raise CompatibilityError("material track requires its verified native MuJoCo module")
            native_render = self.mujoco_module.mjr_render
            def material_render(*args, **kwargs):
                try:
                    return guard.material_draw(native_render, *args, **kwargs)
                except Exception as exc:
                    guard.fault("material_draw", exc)
                    raise
            self.mujoco_module.mjr_render = material_render
            self.expected_methods.append((self.mujoco_module, "mjr_render", material_render))

    def finish(self) -> None:
        if self.live:
            self.fault("close", RuntimeError("native render contexts still live after environment cleanup"))
        self.closed = True
        self.check("after_close", persist=True)


def install(receipt_path: Path, native_root: Path, *, track: str = TRACK) -> LifecycleGuard:
    """Install once before any EGL context/environment construction in this process."""
    global _ACTIVE
    if track not in (TRACK, MATERIAL_TRACK):
        raise CompatibilityError("unknown EGL compatibility track")
    if _ACTIVE is not None:
        if _ACTIVE.track != track:
            raise CompatibilityError("different renderer tracks require separate native processes")
        _ACTIVE.begin(receipt_path)
        return _ACTIVE
    if (platform.system() != "Linux" or os.environ.get("MUJOCO_GL") != "egl"
            or os.environ.get("PYOPENGL_PLATFORM") != "egl"):
        raise CompatibilityError("EGL repair requires explicit Linux MUJOCO_GL=egl and PYOPENGL_PLATFORM=egl")
    for package, version in (("robosuite", "1.5.2"), ("mujoco", "3.3.1"), ("numpy", "2.2.5")):
        if importlib.metadata.version(package) != version:
            raise CompatibilityError(f"EGL repair requires {package}=={version}")
    binding = importlib.import_module("robosuite.utils.binding_utils")
    context = importlib.import_module("robosuite.renderers.context.egl_context")
    from OpenGL import GL
    mujoco_module = importlib.import_module("mujoco")
    if track == MATERIAL_TRACK and (not isinstance(mujoco_module.mjr_render, types.BuiltinFunctionType)
            or mujoco_module.mjr_render.__name__ != "mjr_render"
            or mujoco_module.mjr_render.__module__ != "mujoco._render"):
        raise CompatibilityError("material track requires the original native MuJoCo render entrypoint")
    native_root = Path(native_root).resolve(strict=True)
    for module in (binding, context):
        if not Path(module.__file__).resolve().is_relative_to(native_root):
            raise CompatibilityError("EGL source module is outside the verified native root")
    originals = {name: _source_method(binding, binding.MjRenderContext, name) for name in
                 ("__init__", "render", "read_pixels", "__del__", "update_offscreen_size")}
    for name in ("__init__", "make_current", "free", "__del__"):
        _source_method(context, context.EGLGLContext, name)
    if (binding._MUJOCO_GL != "egl" or context.EGL_DISPLAY is not None
            or _address(context.EGL.eglGetCurrentContext())):
        raise CompatibilityError("install EGL repair in a fresh process before any native render context")
    source_receipt = {"files": dict(SOURCE_PINS), "native_root": str(native_root),
                      "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      "packages": {p: importlib.metadata.version(p) for p in ("robosuite", "mujoco", "numpy", "PyOpenGL")}}
    guard = LifecycleGuard(context.EGL, GL, context, binding.MjRenderContext, context.EGLGLContext, source_receipt,
                           track=track, mujoco_module=mujoco_module)
    guard.begin(receipt_path)
    guard.wrap(originals)
    _ACTIVE = guard
    guard.check("installed")
    return guard
