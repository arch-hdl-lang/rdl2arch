"""TOML config file support for rdl2arch.

Lets a project pin its generator knobs in `rdl2arch.toml` rather than
repeating them on every CLI invocation / every call site of the Python
API. Everything in the file is optional and has a library default;
precedence is CLI flag > config file > default.

File location
-------------
Auto-discovered by walking up from the caller's CWD (or a caller-
provided starting directory) until `rdl2arch.toml` is found or the
filesystem root is hit. Same pattern as `pyproject.toml` /
`.editorconfig`. Pass `config_path=` explicitly to skip the walk and
load a specific file; pass `config_path=False` (or set env
`RDL2ARCH_NO_CONFIG=1`) to disable config-file lookup entirely.

Schema
------
Two sections:

  [rdl2arch]               # global knobs
  addr_width   = 16        # overrides scan_design's max-address derivation
  data_width   = 32        # bus data width; matches --data-width
  reset_style  = "async-low"   # "sync" | "async-low" | "async-high"

  [cpuif.axi4-lite]        # per-cpuif knobs, keyed by the --cpuif CLI token
  port_name              = "s_axi"
  combinational_readback = false

  [cpuif.apb4]
  port_name              = "s_apb"
  combinational_readback = true

Unknown keys in any section are rejected with a clear error — typos
silently no-opping would defeat the purpose of a config file. Unknown
cpuif tokens (anything other than the registered ones) are also
rejected.

The module only loads and validates. It intentionally doesn't know
about `ResetStyle` or `CpuifBase` — mapping the parsed values onto
those types happens in `__main__` / `exporter` so we don't create a
circular import and so Python-API callers can use either raw strings
or typed enums.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

if sys.version_info >= (3, 11):
    import tomllib as _toml
else:  # pragma: no cover - depends on runtime Python version
    try:
        import tomli as _toml
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "rdl2arch requires `tomli` on Python < 3.11. "
            "Install via `pip install tomli`."
        ) from exc


CONFIG_FILENAME = "rdl2arch.toml"

# CLI tokens for the cpuif choices. Must stay in sync with the
# `--cpuif` argparse choices — we cross-check in __main__.
_KNOWN_CPUIF_TOKENS = frozenset({"axi4-lite", "apb4"})

_GLOBAL_KEYS = frozenset({"addr_width", "data_width", "reset_style"})
_CPUIF_KEYS = frozenset({"port_name", "combinational_readback"})

_RESET_STYLE_VALUES = frozenset({"sync", "async-low", "async-high"})


class ConfigError(ValueError):
    """Raised when the config file exists but is malformed.

    Separate from `FileNotFoundError` (file just not present, which is
    fine and leaves everything at defaults).
    """


@dataclass
class CpuifConfig:
    """Overrides for a single cpuif section. None means "not set"."""
    port_name: Optional[str] = None
    combinational_readback: Optional[bool] = None


@dataclass
class Config:
    """Resolved config. All fields are Optional — None means "not set
    in the config file, fall back to CLI / default"."""

    addr_width: Optional[int] = None
    data_width: Optional[int] = None
    reset_style: Optional[str] = None
    cpuif: dict[str, CpuifConfig] = field(default_factory=dict)

    # Where this config was loaded from. None if no file was found /
    # loading was disabled. Useful for diagnostics.
    source_path: Optional[Path] = None

    def cpuif_for(self, token: str) -> CpuifConfig:
        """Return the CpuifConfig for `token`, empty if not set."""
        return self.cpuif.get(token, CpuifConfig())


def find_config_file(
    start: Optional[Union[str, os.PathLike[str]]] = None,
) -> Optional[Path]:
    """Walk up from `start` (default: CWD) looking for rdl2arch.toml.

    Returns the first match or None if none found before the root.
    Never raises — a missing config file is a normal state.
    """
    cur = Path(start).resolve() if start is not None else Path.cwd().resolve()
    # `start` might be a file path; walk up from its parent.
    if cur.is_file():
        cur = cur.parent
    while True:
        candidate = cur / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        if cur.parent == cur:  # filesystem root
            return None
        cur = cur.parent


def load_config(
    config_path: Optional[Union[str, os.PathLike[str], bool]] = None,
    *,
    start: Optional[Union[str, os.PathLike[str]]] = None,
) -> Config:
    """Load and validate a config file.

    `config_path`:
      - `None`: auto-discover (walk up from `start` or CWD)
      - `False`: skip discovery, return an empty Config
      - path-like: load that file exactly; raise ConfigError if it
        doesn't exist (a user who passed `--config` wants that file)

    `RDL2ARCH_NO_CONFIG=1` in env short-circuits to empty Config — an
    escape hatch when auto-discovery would pick up an undesired file.

    Returns a Config with all unset fields as None. Callers apply
    precedence (CLI > config > default) themselves.
    """
    if os.environ.get("RDL2ARCH_NO_CONFIG") == "1":
        return Config()

    # `False` disables discovery. Handle before the Path() branch so
    # mypy knows the remaining union is just str | PathLike | None.
    if isinstance(config_path, bool):
        if config_path is False:
            return Config()
        # bool True is not a meaningful input — reject loudly.
        raise TypeError("config_path=True is not valid; use None or a path")

    path: Optional[Path]
    if config_path is None:
        path = find_config_file(start=start)
        if path is None:
            return Config()
    else:
        path = Path(config_path)
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")

    with open(path, "rb") as fh:
        try:
            raw = _toml.load(fh)
        except _toml.TOMLDecodeError as exc:
            raise ConfigError(f"invalid TOML in {path}: {exc}") from exc

    return _parse(raw, path)


def _parse(raw: dict[str, Any], source: Path) -> Config:
    cfg = Config(source_path=source)

    # Unknown top-level tables are an error — TOML is permissive enough
    # that a typo like `[rdl2ach]` would otherwise be silent.
    allowed_top = {"rdl2arch", "cpuif"}
    for key in raw:
        if key not in allowed_top:
            raise ConfigError(
                f"{source}: unknown top-level section `[{key}]`. "
                f"Allowed: {sorted(allowed_top)}"
            )

    g = raw.get("rdl2arch", {})
    if not isinstance(g, dict):
        raise ConfigError(f"{source}: `[rdl2arch]` must be a table")
    _validate_keys(g, _GLOBAL_KEYS, f"{source}: [rdl2arch]")

    if "addr_width" in g:
        v = g["addr_width"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise ConfigError(
                f"{source}: [rdl2arch].addr_width must be a positive integer, got {v!r}"
            )
        cfg.addr_width = v

    if "data_width" in g:
        v = g["data_width"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise ConfigError(
                f"{source}: [rdl2arch].data_width must be a positive integer, got {v!r}"
            )
        cfg.data_width = v

    if "reset_style" in g:
        v = g["reset_style"]
        if not isinstance(v, str) or v not in _RESET_STYLE_VALUES:
            raise ConfigError(
                f"{source}: [rdl2arch].reset_style must be one of "
                f"{sorted(_RESET_STYLE_VALUES)}, got {v!r}"
            )
        cfg.reset_style = v

    cpuif_section = raw.get("cpuif", {})
    if not isinstance(cpuif_section, dict):
        raise ConfigError(f"{source}: `[cpuif]` must be a table of tables")
    for token, body in cpuif_section.items():
        if token not in _KNOWN_CPUIF_TOKENS:
            raise ConfigError(
                f"{source}: unknown cpuif `[cpuif.{token}]`. "
                f"Known: {sorted(_KNOWN_CPUIF_TOKENS)}"
            )
        if not isinstance(body, dict):
            raise ConfigError(
                f"{source}: `[cpuif.{token}]` must be a table"
            )
        _validate_keys(body, _CPUIF_KEYS, f"{source}: [cpuif.{token}]")

        entry = CpuifConfig()
        if "port_name" in body:
            v = body["port_name"]
            if not isinstance(v, str) or not v:
                raise ConfigError(
                    f"{source}: [cpuif.{token}].port_name must be a non-empty "
                    f"string, got {v!r}"
                )
            entry.port_name = v
        if "combinational_readback" in body:
            v = body["combinational_readback"]
            if not isinstance(v, bool):
                raise ConfigError(
                    f"{source}: [cpuif.{token}].combinational_readback must "
                    f"be a boolean, got {v!r}"
                )
            entry.combinational_readback = v
        cfg.cpuif[token] = entry

    return cfg


def _validate_keys(body: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    for k in body:
        if k not in allowed:
            raise ConfigError(
                f"{where}: unknown key `{k}`. Allowed: {sorted(allowed)}"
            )
