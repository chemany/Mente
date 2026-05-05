"""Legacy compatibility alias for ``mente.integrations.bridge``."""

from __future__ import annotations

import sys

from . import bridge as _bridge

sys.modules[__name__] = _bridge
