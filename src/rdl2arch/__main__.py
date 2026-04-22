"""rdl2arch command-line entry point.

Precedence: CLI flag > `rdl2arch.toml` (auto-discovered, or `--config
<path>`) > library default. See `rdl2arch.config` for the schema.
"""

import argparse
import sys

from systemrdl import RDLCompileError, RDLCompiler

from . import config as _cfg
from .cpuif.apb4 import APB4_Cpuif
from .cpuif.axi4lite import AXI4Lite_Cpuif
from .emit_regblock import ResetStyle
from .exporter import ArchExporter


# --cpuif CLI token -> cpuif class. Keys must match
# rdl2arch.config._KNOWN_CPUIF_TOKENS.
_CPUIF_BY_TOKEN = {
    "axi4-lite": AXI4Lite_Cpuif,
    "apb4": APB4_Cpuif,
}


# A sentinel so we can tell "user didn't pass this CLI flag" apart from
# "user passed the default value". argparse doesn't distinguish the two
# on its own — `default=None` would work for some flags but not for
# choice flags like --reset-style / --cpuif that have a sensible default.
# Using our own sentinel keeps the logic uniform.
class _Unset:
    def __repr__(self) -> str:  # pragma: no cover
        return "<unset>"


_UNSET = _Unset()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="rdl2arch",
        description=(
            "Generate ARCH register-block source from SystemRDL input. "
            "Knobs can also be set in a `rdl2arch.toml` auto-discovered "
            "by walking up from CWD; CLI flags override the file."
        ),
    )
    p.add_argument("input", help="SystemRDL input file (.rdl)")
    p.add_argument("-o", "--output-dir", default=".", help="Output directory")
    p.add_argument("--cpuif", choices=list(_CPUIF_BY_TOKEN), default=_UNSET,
                   help="CPU interface protocol (default: axi4-lite)")
    p.add_argument("--module-name", help="Override module name (default: from RDL top)")
    p.add_argument("--package-name", help="Override package name")
    p.add_argument("--data-width", type=int, default=_UNSET,
                   help="Bus data width (default: 32)")
    p.add_argument("--addr-width", type=int, default=_UNSET,
                   help=("Override the regblock address width. Default "
                         "is auto-derived from the maximum register "
                         "address."))
    p.add_argument("--port-name", default=_UNSET,
                   help=("Override the cpuif subordinate port name. "
                         "Default: cpuif class attr (s_axi / s_apb)."))
    p.add_argument(
        "--combinational-readback",
        choices=["true", "false"],
        default=_UNSET,
        help=("Override the cpuif's readback timing. Default: cpuif "
              "class attr (AXI4-Lite=false, APB4=true). Set `true` to "
              "drop the sequential rdata latch."),
    )
    p.add_argument(
        "--reset-style",
        choices=[s.value for s in ResetStyle],
        default=_UNSET,
        help=(
            "Reset style for the emitted `port rst`. `sync` (default) "
            "→ `Reset<Sync>`. `async-low` → `Reset<Async, Low>` "
            "(RISC-V / Ibex `rst_ni` convention; required under "
            "clock-gated cores where the clock doesn't tick during "
            "reset). `async-high` → `Reset<Async>`."
        ),
    )
    p.add_argument(
        "--config",
        default=None,
        help=(
            "Path to an rdl2arch.toml. Default: walk up from CWD and "
            "load the first match. Use `--no-config` to skip the walk."
        ),
    )
    p.add_argument(
        "--no-config", action="store_true",
        help="Skip the rdl2arch.toml auto-discovery.",
    )
    args = p.parse_args(argv)

    # --- Load config file (if any) --------------------------------------------
    try:
        cfg = _cfg.load_config(
            config_path=False if args.no_config else args.config,
        )
    except _cfg.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # --- Resolve each knob with precedence: CLI > config > default -----------
    from typing import TypeVar
    _T = TypeVar("_T")

    def _resolve(cli_value: object, cfg_value: "_T | None", default: _T) -> _T:
        if cli_value is not _UNSET:
            return cli_value  # type: ignore[return-value]
        if cfg_value is not None:
            return cfg_value
        return default

    cpuif_token = _resolve(args.cpuif, None, "axi4-lite")
    data_width = _resolve(args.data_width, cfg.data_width, 32)
    addr_width = _resolve(args.addr_width, cfg.addr_width, None)
    reset_style_raw = _resolve(args.reset_style, cfg.reset_style, ResetStyle.SYNC.value)

    cpuif_cfg = cfg.cpuif_for(cpuif_token)
    port_name = _resolve(args.port_name, cpuif_cfg.port_name, None)
    comb_cli = (
        _UNSET if args.combinational_readback is _UNSET
        else (args.combinational_readback == "true")
    )
    combinational_readback = _resolve(
        comb_cli, cpuif_cfg.combinational_readback, None
    )

    try:
        reset_style = ResetStyle(reset_style_raw)
    except ValueError:
        # Shouldn't happen: argparse constrains CLI values and config
        # loader validates. Defensive for Python-API callers of main().
        print(f"error: invalid reset_style {reset_style_raw!r}", file=sys.stderr)
        return 1

    # --- Compile RDL -----------------------------------------------------------
    rdlc = RDLCompiler()
    try:
        rdlc.compile_file(args.input)
        root = rdlc.elaborate()
    except RDLCompileError:
        return 1

    cpuif_cls = _CPUIF_BY_TOKEN[cpuif_token]

    files = ArchExporter().export(
        root.top,
        args.output_dir,
        cpuif_cls=cpuif_cls,
        module_name=args.module_name,
        package_name=args.package_name,
        data_width=data_width,
        reset_style=reset_style,
        addr_width=addr_width,
        port_name=port_name,
        combinational_readback=combinational_readback,
    )
    for _, path in files.items():
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
