"""
Action discovery, validation, and dispatch — the built-in twin of plugin_loader.

Every actions/*.py that exposes a module-level ``TOOL`` dict is auto-discovered
here, exactly like a drop-in plugin, so main.py never has to hardcode a tool
declaration or a dispatch branch for it. Adding a new bundled action is then the
same one-file operation as writing a plugin: define ``TOOL`` and a handler.

``TOOL`` shape (see actions/open_app.py for a live example):

    TOOL = {
        "name":        "open_app",              # unique, ^[a-zA-Z_][a-zA-Z0-9_]{0,63}$
        "description":  "...",                   # what Gemini reads to route the call
        "parameters":  {"type": "OBJECT", ...}, # Gemini function-declaration schema
        "handler":      open_app,                # the callable to run
    }

The handler is invoked through signature introspection: it receives ``parameters``
plus whichever of ``player`` / ``speak`` / ``response`` / ``session_memory`` it
actually declares — so existing action signatures work unchanged.

Discovery runs once at startup; import errors, validation errors, and name
collisions are logged and the offending file is skipped — they NEVER raise out
of discover_actions() and never abort the scan of the remaining files.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import re
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_DEFAULT_PARAMS = {"type": "OBJECT", "properties": {}}
_CTX_KEYS = ("player", "speak", "response", "session_memory")

_BEHAVIORS = ("BLOCKING", "NON_BLOCKING")
_SCHEDULING = ("WHEN_IDLE", "SILENT", "INTERRUPT")

from core.common_utils import normalize_optional as _opt_upper


@dataclass
class ActionRecord:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=lambda: dict(_DEFAULT_PARAMS))
    handler: Optional[Callable] = None
    file: str = ""
    valid: bool = False
    error: str = ""
    behavior: Optional[str] = None
    scheduling: Optional[str] = None

class ActionRegistry:
    def __init__(self, actions: dict[str, ActionRecord], logger: Callable[[str], None]):
        self._actions = actions
        self._all_records: list[ActionRecord] = []
        self._logger = logger

    def get_tool_declarations(self) -> list[dict]:
        out = []
        for rec in self._actions.values():
            decl = {"name": rec.name, "description": rec.description,
                    "parameters": rec.parameters}
            if rec.behavior:
                decl["behavior"] = rec.behavior
            out.append(decl)
        return out

    def has(self, name: str) -> bool:
        return name in self._actions

    def scheduling(self, name: str) -> Optional[str]:
        """How this action's result should re-enter the conversation, if it said."""
        rec = self._actions.get(name)
        return rec.scheduling if rec else None

    def names(self) -> set[str]:
        return set(self._actions.keys())

    def run(self, name: str, parameters: dict, ctx: dict | None = None) -> str:
        rec = self._actions.get(name)
        if rec is None or not rec.valid:
            return f"Action '{name}' is not available."
        try:
            return _call_handler(rec.handler, parameters, ctx or {}) or "Done."
        except Exception as e:
            self._logger(f"Action '{name}' crashed during run(): {e}")
            traceback.print_exc()
            return f"Tool '{name}' failed: {e}"

def _call_handler(fn: Callable, parameters: dict, ctx: dict) -> str:
    """Invoke the handler passing only the context kwargs it actually declares
    (or all of them if it has **kwargs), so each action's existing signature
    works unchanged."""
    sig = inspect.signature(fn)
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    kwargs = {}
    for key in _CTX_KEYS:
        if has_var_kw or key in sig.parameters:
            kwargs[key] = ctx.get(key)
    return fn(parameters=parameters, **kwargs)

def _validate(module, filename: str) -> ActionRecord:
    """Returns an ActionRecord; .valid=False + .error set on any problem. Never raises."""
    tool = getattr(module, "TOOL", None)
    if not isinstance(tool, dict):
        return ActionRecord(name=Path(filename).stem, file=filename,
                            error="No module-level TOOL dict (not a discoverable action).")

    name = tool.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return ActionRecord(name=str(name or Path(filename).stem), file=filename,
                            error="TOOL['name'] missing or not a valid identifier.")

    description = tool.get("description")
    if not isinstance(description, str) or not description.strip():
        return ActionRecord(name=name, file=filename,
                            error="TOOL['description'] missing or empty.")

    parameters = tool.get("parameters", _DEFAULT_PARAMS)
    if not isinstance(parameters, dict) or parameters.get("type") != "OBJECT":
        return ActionRecord(name=name, file=filename,
                            error="TOOL['parameters'] must be a dict with \"type\": \"OBJECT\".")

    handler = tool.get("handler")
    if not callable(handler):
        return ActionRecord(name=name, file=filename,
                            error="TOOL['handler'] missing or not callable.")

    return ActionRecord(name=name, description=description.strip(), parameters=parameters,
                        handler=handler, file=filename, valid=True, error="",
                        behavior=_opt_upper(tool.get("behavior"), _BEHAVIORS),
                        scheduling=_opt_upper(tool.get("scheduling"), _SCHEDULING))

def _import_action_module(path: Path):
    """Import one action module, caching it in sys.modules."""
    module_name = f"actions.{path.stem}"
    module = sys.modules.get(module_name)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError("could not build import spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


class _LazyActionHandler:
    """Thread-safe proxy; imports its action module only when invoked."""
    def __init__(self, path: Path):
        self._path = path
        self._module_name = f"actions.{path.stem}"
        self._lock = threading.RLock()
        self._handler = None

    def _load(self):
        if self._handler is not None:
            return self._handler
        with self._lock:
            if self._handler is not None:
                return self._handler
            module = _import_action_module(self._path)
            tool = getattr(module, "TOOL", None)
            handler = tool.get("handler") if isinstance(tool, dict) else None
            if not callable(handler):
                raise RuntimeError(f"{self._path.name} no longer exposes a callable TOOL handler")
            self._handler = handler
            return handler

    def __call__(self, parameters: dict, **ctx):
        return _call_handler(self._load(), parameters, ctx)


def _static_tool_record(path: Path):
    """Return (is_action, record) without importing optional dependencies.

    is_action=False means there is no module-level TOOL and the file must be
    skipped. is_action=True with record=None means TOOL is dynamic, so use the
    eager compatibility path. A literal TOOL returns a validated lazy record.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return None, None
    tool_node = None
    handler_node = None
    found_tool = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "TOOL" for target in node.targets):
                found_tool = True
                tool_node = node.value
                if isinstance(tool_node, ast.Dict):
                    for key_node, value_node in zip(tool_node.keys, tool_node.values):
                        try:
                            key = ast.literal_eval(key_node)
                        except Exception:
                            continue
                        if key == "handler":
                            handler_node = value_node
            for target in node.targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == "TOOL":
                    try:
                        key = ast.literal_eval(target.slice)
                    except Exception:
                        continue
                    if key == "handler":
                        handler_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "TOOL":
            found_tool = True
            tool_node = node.value
            if isinstance(tool_node, ast.Dict):
                for key_node, value_node in zip(tool_node.keys, tool_node.values):
                    try:
                        key = ast.literal_eval(key_node)
                    except Exception:
                        continue
                    if key == "handler":
                        handler_node = value_node
    if not found_tool:
        return False, None
    if not isinstance(tool_node, ast.Dict) or not isinstance(handler_node, ast.Name):
        return True, None
    metadata = {}
    for key_node, value_node in zip(tool_node.keys, tool_node.values):
        try:
            key = ast.literal_eval(key_node)
        except Exception:
            return True, None
        if key == "handler":
            continue
        try:
            metadata[key] = ast.literal_eval(value_node)
        except Exception:
            return True, None
    metadata["handler"] = _LazyActionHandler(path)
    module_stub = type("_StaticToolModule", (), {"TOOL": metadata})()
    return True, _validate(module_stub, path.name)


def discover_actions(actions_dir: Path, reserved_names: set[str] | None = None,
                     logger: Callable[[str], None] = print) -> ActionRegistry:
    """
    Scans actions_dir for *.py files (skips files starting with '_'). Literal
    TOOL declarations are validated from their AST, so action modules and their
    optional dependencies load only on first dispatch. Dynamic declarations use
    the eager compatibility path. Import/validation errors and name collisions
    are logged; they never abort scanning the remaining files.
    """
    reserved = set(reserved_names or ())
    actions_dir.mkdir(parents=True, exist_ok=True)
    valid: dict[str, ActionRecord] = {}
    all_records: list[ActionRecord] = []
    files = sorted(actions_dir.glob("*.py"), key=lambda path: path.name)
    for path in files:
        if path.name.startswith("_"):
            continue
        try:
            is_action, rec = _static_tool_record(path)
            if is_action is False:
                continue
            if rec is None:
                module = _import_action_module(path)
                if getattr(module, "TOOL", None) is None:
                    continue
                rec = _validate(module, path.name)
            if rec.valid and rec.name in reserved:
                rec = ActionRecord(name=rec.name, file=path.name,
                                   error=f"Name '{rec.name}' collides with a reserved core tool — rejected.")
            elif rec.valid and rec.name in valid:
                other = valid[rec.name].file
                rec = ActionRecord(name=rec.name, file=path.name,
                                   error=f"Name '{rec.name}' already used by action '{other}' — rejected.")
        except Exception as e:
            rec = ActionRecord(name=path.stem, file=path.name,
                               error=f"Failed to load: {e}")
            traceback.print_exc()
        all_records.append(rec)
        if rec.valid:
            valid[rec.name] = rec
            logger(f"Action registered (lazy): {rec.name} ({path.name})")
        else:
            logger(f"Action rejected: {path.name} — {rec.error}")
    registry = ActionRegistry(valid, logger)
    registry._all_records = all_records
    logger(f"Action discovery complete: {len(valid)} active.")
    return registry

#by ASDcuber
