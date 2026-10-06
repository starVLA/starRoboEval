"""Local CLI/PNG readiness checks; never model inference or simulator access."""
from __future__ import annotations

import io

from benchkit.errors import PolicyPreflightError


def preflight_native_runtime():
    from AgentPolicies.gpt6_astra.transports.codex_cli import preflight_runtime
    preflight_runtime()
    try:
        import numpy as np
        from PIL import Image
        data = np.array([[[0, 127, 255]]], dtype=np.uint8)
        buffer = io.BytesIO()
        Image.fromarray(data).save(buffer, format="PNG")
        with Image.open(io.BytesIO(buffer.getvalue())) as decoded:
            if decoded.mode != "RGB" or not np.array_equal(np.asarray(decoded), data):
                raise ValueError("PNG mismatch")
    except ImportError:
        raise PolicyPreflightError("dependency_unavailable") from None
    except Exception:
        raise PolicyPreflightError("initialization_failed") from None
