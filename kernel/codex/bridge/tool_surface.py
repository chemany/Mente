"""Vendored Codex capability-surface helpers for the Mente outer bridge."""

from __future__ import annotations

from ast import literal_eval
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re


_REPO_ROOT = Path(__file__).resolve().parents[3]
_TOOLS_LIB_RS = _REPO_ROOT / "kernel/codex/upstream/codex-rs/tools/src/lib.rs"
_PLUGIN_LIB_RS = _REPO_ROOT / "kernel/codex/upstream/codex-rs/plugin/src/lib.rs"
_SKILLS_LIB_RS = _REPO_ROOT / "kernel/codex/upstream/codex-rs/skills/src/lib.rs"
_APP_SERVER_ROOT = _REPO_ROOT / "kernel/codex/upstream/sdk/python/src/codex_app_server"
_CODEX_PROTOCOL_MODELS_RS = _REPO_ROOT / "kernel/codex/upstream/codex-rs/protocol/src/models.rs"

_TOOL_NAME_PATTERN = re.compile(r'name:\s*"([^"]+)"\.to_string\(\)')
_TOOL_SPEC_NAME_PATTERN = re.compile(r'=>\s*"([^"]+)"')
_TOOL_CONST_PATTERN = re.compile(r'pub const [A-Z0-9_]*TOOL_NAME: &str = "([^"]+)";')
_PUB_USE_PATTERN = re.compile(r"pub use [^:]+::([A-Za-z0-9_]+);")
_PUB_FN_PATTERN = re.compile(r"pub fn ([A-Za-z0-9_]+)")
_PUB_STRUCT_PATTERN = re.compile(r"pub struct ([A-Za-z0-9_]+)")


@dataclass(frozen=True)
class CapabilitySurfaceSection:
    """A vendored upstream capability section and the identifiers it exports."""

    source_path: str
    identifiers: tuple[str, ...]


@dataclass(frozen=True)
class NativeToolSurface:
    """Vendored upstream native tool surface derived from upstream sources."""

    source_path: str
    names: tuple[str, ...]
    module_paths: tuple[str, ...]


@dataclass(frozen=True)
class VendoredCapabilitySurface:
    """Mente-facing map of vendored Codex native capability surfaces."""

    source_of_truth: str
    native_tools: NativeToolSurface
    plugin_hooks: CapabilitySurfaceSection
    skill_loading: CapabilitySurfaceSection
    app_server_touchpoints: tuple[str, ...]
    app_server_exports: tuple[str, ...]



def _relative(path: Path) -> str:
    return str(path.relative_to(_REPO_ROOT))


@lru_cache(maxsize=1)
def _tool_source_files() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in _TOOLS_LIB_RS.parent.glob("*.rs")
            if path.name != "lib.rs" and not path.name.endswith("_tests.rs")
        )
    )


@lru_cache(maxsize=1)
def _parse_native_tool_names() -> tuple[str, ...]:
    names: set[str] = set()
    for source_file in _tool_source_files():
        content = source_file.read_text(encoding="utf-8")
        names.update(_TOOL_NAME_PATTERN.findall(content))
        names.update(_TOOL_CONST_PATTERN.findall(content))

    tool_spec_content = (_TOOLS_LIB_RS.parent / "tool_spec.rs").read_text(encoding="utf-8")
    protocol_models_content = _CODEX_PROTOCOL_MODELS_RS.read_text(encoding="utf-8")
    view_image_match = re.search(
        r'pub const VIEW_IMAGE_TOOL_NAME: &str = "([^"]+)";',
        protocol_models_content,
    )
    names.update(
        name
        for name in _TOOL_SPEC_NAME_PATTERN.findall(tool_spec_content)
        if name in {"tool_search", "local_shell", "image_generation", "web_search"}
    )
    if view_image_match is not None:
        names.add(view_image_match.group(1))
    normalized = {name for name in names if re.fullmatch(r"[a-z0-9_]+", name)}
    return tuple(sorted(normalized))


@lru_cache(maxsize=1)
def _parse_plugin_identifiers() -> tuple[str, ...]:
    content = _PLUGIN_LIB_RS.read_text(encoding="utf-8")
    identifiers = set(_PUB_USE_PATTERN.findall(content))
    identifiers.update(_PUB_STRUCT_PATTERN.findall(content))
    return tuple(sorted(identifiers))


@lru_cache(maxsize=1)
def _parse_skill_identifiers() -> tuple[str, ...]:
    content = _SKILLS_LIB_RS.read_text(encoding="utf-8")
    return tuple(sorted(set(_PUB_FN_PATTERN.findall(content))))


@lru_cache(maxsize=1)
def _parse_app_server_exports() -> tuple[str, ...]:
    init_py = _APP_SERVER_ROOT / "__init__.py"
    content = init_py.read_text(encoding="utf-8")
    marker = "__all__ = "
    start = content.index(marker) + len(marker)
    exports = literal_eval(content[start:].strip())
    return tuple(exports)


@lru_cache(maxsize=1)
def get_vendored_capability_surface() -> VendoredCapabilitySurface:
    """Return the vendored Codex capability map used as Mente's source of truth."""

    app_server_files = (
        _APP_SERVER_ROOT / "__init__.py",
        _APP_SERVER_ROOT / "api.py",
        _APP_SERVER_ROOT / "client.py",
        _APP_SERVER_ROOT / "async_client.py",
        _APP_SERVER_ROOT / "models.py",
        _APP_SERVER_ROOT / "_run.py",
    )
    return VendoredCapabilitySurface(
        source_of_truth="vendored_upstream",
        native_tools=NativeToolSurface(
            source_path=_relative(_TOOLS_LIB_RS),
            names=_parse_native_tool_names(),
            module_paths=tuple(_relative(path) for path in _tool_source_files()),
        ),
        plugin_hooks=CapabilitySurfaceSection(
            source_path=_relative(_PLUGIN_LIB_RS),
            identifiers=_parse_plugin_identifiers(),
        ),
        skill_loading=CapabilitySurfaceSection(
            source_path=_relative(_SKILLS_LIB_RS),
            identifiers=_parse_skill_identifiers(),
        ),
        app_server_touchpoints=tuple(_relative(path) for path in app_server_files),
        app_server_exports=_parse_app_server_exports(),
    )



def get_vendored_native_tool_names() -> list[str]:
    """Return vendored native tool names without mixing in Mente bridge tools."""

    return list(get_vendored_capability_surface().native_tools.names)



def filter_vendored_native_tools(allowed_names: list[str] | tuple[str, ...]) -> list[str]:
    """Filter native tools by vendored upstream order and membership only."""

    allowed = set(allowed_names)
    return [name for name in get_vendored_native_tool_names() if name in allowed]
