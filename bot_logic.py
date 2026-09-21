"""Sonar Radar bot logic (modular wrapper).

This file keeps the public API of the legacy `bot_logic.py` intact, while
splitting the implementation into smaller modules under `bot_logic_mod/`.

Important: do NOT import bot_logic_mod.* directly from other files; always
import from `bot_logic` so the export/injection layer stays consistent.
"""

from __future__ import annotations

import importlib
import types

# Import modules (order matters: base first)
_modules = [
    importlib.import_module('bot_logic_mod.base'),
    importlib.import_module('bot_logic_mod.menu'),
    importlib.import_module('bot_logic_mod.admin'),
    importlib.import_module('bot_logic_mod.servers'),
    importlib.import_module('bot_logic_mod.ops'),
    importlib.import_module('bot_logic_mod.ui'),
    importlib.import_module('bot_logic_mod.configs'),
    importlib.import_module('bot_logic_mod.tunnels'),
]

# Collect all public symbols
_exports = {}
for m in _modules:
    for k,v in m.__dict__.items():
        if k.startswith('_'):
            continue
        _exports[k] = v

# Inject missing symbols into each module so cross-module global lookups work
for m in _modules:
    for k,v in _exports.items():
        if k.startswith('_'):
            continue
        if k not in m.__dict__:
            m.__dict__[k] = v

# Re-export from this module (legacy API)
globals().update(_exports)

# Help static tools
__all__ = sorted([k for k in _exports.keys() if not k.startswith('_')])
