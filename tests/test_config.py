"""Tests for rdl2arch.toml config file support.

Covers the three layers independently:
  (1) `rdl2arch.config.load_config`   — TOML parse + validation
  (2) `ArchExporter.export(...)`      — Python-API kwargs for the new knobs
  (3) `rdl2arch.__main__.main(...)`   — CLI flag + auto-discovery + precedence
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from systemrdl import RDLCompiler

from rdl2arch import ArchExporter, Config, ConfigError, ResetStyle, load_config
from rdl2arch.cpuif.apb4 import APB4_Cpuif
from rdl2arch.cpuif.axi4lite import AXI4Lite_Cpuif
from rdl2arch.scan_design import scan
from rdl2arch.udps import ALL_UDPS


# --- helpers -------------------------------------------------------------


def _compile_rdl(tmp_path: Path, source: str):
    rdl = tmp_path / "x.rdl"
    rdl.write_text(source)
    rdlc = RDLCompiler()
    for udp in ALL_UDPS:
        rdlc.register_udp(udp, soft=False)
    rdlc.compile_file(str(rdl))
    return rdlc.elaborate().top


_TINY_RDL = """
    addrmap m {
        reg {
            field { sw = rw; hw = r; reset = 0; } v[31:0];
        } r0 @ 0x0;
    };
"""


# =========================================================================
# (1) Config loader
# =========================================================================


def test_load_config_missing_file_returns_empty(tmp_path: Path) -> None:
    """No rdl2arch.toml in the walk-up path → Config() with all Nones."""
    cfg = load_config(start=tmp_path)
    assert cfg.addr_width is None
    assert cfg.data_width is None
    assert cfg.reset_style is None
    assert cfg.cpuif == {}
    assert cfg.source_path is None


def test_load_config_explicit_missing_path_errors(tmp_path: Path) -> None:
    """Passing an explicit path that doesn't exist is a user error."""
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(tmp_path / "nope.toml")


def test_load_config_full_example(tmp_path: Path) -> None:
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [rdl2arch]
        addr_width = 16
        data_width = 64
        reset_style = "async-low"

        [cpuif.axi4-lite]
        port_name = "s_axi_main"
        combinational_readback = true

        [cpuif.apb4]
        port_name = "s_apb_dbg"
        """
    )
    cfg = load_config(start=tmp_path)
    assert cfg.addr_width == 16
    assert cfg.data_width == 64
    assert cfg.reset_style == "async-low"
    assert cfg.source_path == (tmp_path / "rdl2arch.toml").resolve()

    axi = cfg.cpuif_for("axi4-lite")
    assert axi.port_name == "s_axi_main"
    assert axi.combinational_readback is True

    apb = cfg.cpuif_for("apb4")
    assert apb.port_name == "s_apb_dbg"
    assert apb.combinational_readback is None  # not set in file


def test_load_config_walks_up_from_subdirectory(tmp_path: Path) -> None:
    """The whole point of auto-discovery — cd into a subdir and still
    find the project's config."""
    (tmp_path / "rdl2arch.toml").write_text(
        '[rdl2arch]\naddr_width = 8\n'
    )
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    cfg = load_config(start=nested)
    assert cfg.addr_width == 8


def test_load_config_rdl2arch_no_config_env(tmp_path: Path, monkeypatch) -> None:
    """Env escape hatch: even with a TOML present, RDL2ARCH_NO_CONFIG=1
    returns empty."""
    (tmp_path / "rdl2arch.toml").write_text(
        '[rdl2arch]\naddr_width = 8\n'
    )
    monkeypatch.setenv("RDL2ARCH_NO_CONFIG", "1")
    cfg = load_config(start=tmp_path)
    assert cfg.addr_width is None
    assert cfg.source_path is None


def test_load_config_unknown_top_level_section(tmp_path: Path) -> None:
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [rdl2ach]   # typo
        addr_width = 8
        """
    )
    with pytest.raises(ConfigError, match=r"unknown top-level section"):
        load_config(start=tmp_path)


def test_load_config_unknown_global_key(tmp_path: Path) -> None:
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [rdl2arch]
        addr_wdith = 8   # typo
        """
    )
    with pytest.raises(ConfigError, match=r"unknown key `addr_wdith`"):
        load_config(start=tmp_path)


def test_load_config_unknown_cpuif_key(tmp_path: Path) -> None:
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [cpuif.axi4-lite]
        prt_name = "x"   # typo
        """
    )
    with pytest.raises(ConfigError, match=r"unknown key `prt_name`"):
        load_config(start=tmp_path)


def test_load_config_unknown_cpuif_token(tmp_path: Path) -> None:
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [cpuif.wishbone]
        port_name = "s_wb"
        """
    )
    with pytest.raises(ConfigError, match=r"unknown cpuif"):
        load_config(start=tmp_path)


def test_load_config_bad_reset_style(tmp_path: Path) -> None:
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [rdl2arch]
        reset_style = "nope"
        """
    )
    with pytest.raises(ConfigError, match=r"reset_style"):
        load_config(start=tmp_path)


def test_load_config_bad_addr_width_type(tmp_path: Path) -> None:
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [rdl2arch]
        addr_width = "16"
        """
    )
    with pytest.raises(ConfigError, match=r"addr_width"):
        load_config(start=tmp_path)


def test_load_config_bad_addr_width_zero(tmp_path: Path) -> None:
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [rdl2arch]
        addr_width = 0
        """
    )
    with pytest.raises(ConfigError, match=r"addr_width"):
        load_config(start=tmp_path)


def test_load_config_bad_combinational_readback_type(tmp_path: Path) -> None:
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [cpuif.axi4-lite]
        combinational_readback = "yes"
        """
    )
    with pytest.raises(ConfigError, match=r"combinational_readback"):
        load_config(start=tmp_path)


def test_load_config_bad_toml(tmp_path: Path) -> None:
    (tmp_path / "rdl2arch.toml").write_text("this is [not valid toml")
    with pytest.raises(ConfigError, match=r"invalid TOML"):
        load_config(start=tmp_path)


def test_load_config_disabled_with_false(tmp_path: Path) -> None:
    """`config_path=False` skips lookup even if a file exists."""
    (tmp_path / "rdl2arch.toml").write_text(
        '[rdl2arch]\naddr_width = 8\n'
    )
    cfg = load_config(config_path=False, start=tmp_path)
    assert cfg.addr_width is None


# =========================================================================
# (2) Python-API: ArchExporter.export(...) overrides
# =========================================================================


def test_scan_addr_width_override(tmp_path: Path) -> None:
    top = _compile_rdl(tmp_path, _TINY_RDL)
    d = scan(top, addr_width=16)
    assert d.addr_width == 16


def test_scan_addr_width_rejects_zero(tmp_path: Path) -> None:
    top = _compile_rdl(tmp_path, _TINY_RDL)
    with pytest.raises(ValueError, match="addr_width"):
        scan(top, addr_width=0)


def test_cpuif_port_name_override() -> None:
    """Instance kwarg shadows the class attr without mutating it."""
    c = AXI4Lite_Cpuif(addr_width=8, data_width=32, port_name="s_axi_main")
    assert c.port_name == "s_axi_main"
    # Class attr untouched — future instances still default to s_axi.
    assert AXI4Lite_Cpuif.port_name == "s_axi"
    c2 = AXI4Lite_Cpuif(addr_width=8, data_width=32)
    assert c2.port_name == "s_axi"


def test_cpuif_combinational_readback_override() -> None:
    c = AXI4Lite_Cpuif(addr_width=8, data_width=32, combinational_readback=True)
    assert c.combinational_readback is True
    # APB default stays True.
    assert APB4_Cpuif(addr_width=8, data_width=32).combinational_readback is True


def test_exporter_addr_width_override(tmp_path: Path) -> None:
    """`addr_width=16` widens the emitted address literals even when
    the biggest register only occupies bit 2."""
    top = _compile_rdl(tmp_path, _TINY_RDL)
    ArchExporter().export(
        top, str(tmp_path),
        addr_width=16,
    )
    arch = (tmp_path / "m.arch").read_text()
    # Bus param uses the overridden width, and the address-literal
    # width in the match table matches it.
    assert "param ADDR_W: const = 16;" in arch
    assert "16'h0" in arch


def test_exporter_port_name_override(tmp_path: Path) -> None:
    top = _compile_rdl(tmp_path, _TINY_RDL)
    ArchExporter().export(
        top, str(tmp_path),
        port_name="s_axi_dbg",
    )
    arch = (tmp_path / "m.arch").read_text()
    assert "port s_axi_dbg: target" in arch
    assert "s_axi_dbg.aw_valid" in arch
    # Default name shouldn't leak in.
    assert "s_axi." not in arch


def test_exporter_combinational_readback_override_for_axi(tmp_path: Path) -> None:
    """Forcing `combinational_readback=True` on AXI drops the seq
    branch that latches `rdata_r <= rdata_mux`. (The state decl for
    rdata_r itself comes from the AXI cpuif's handshake_state and
    isn't affected — the override is scoped to the emitter's seq
    branch, which is the only functional guarantee.)"""
    top = _compile_rdl(tmp_path, _TINY_RDL)
    ArchExporter().export(
        top, str(tmp_path),
        combinational_readback=True,
    )
    arch = (tmp_path / "m.arch").read_text()
    assert "rdata_r <= rdata_mux" not in arch

    # Sanity: default (no override) keeps the latch.
    ArchExporter().export(top, str(tmp_path))
    default_arch = (tmp_path / "m.arch").read_text()
    assert "rdata_r <= rdata_mux" in default_arch


# =========================================================================
# (3) CLI: __main__ flags + config-file precedence
# =========================================================================


def test_cli_addr_width_flag(tmp_path: Path) -> None:
    from rdl2arch.__main__ import main
    rdl = tmp_path / "m.rdl"
    rdl.write_text(_TINY_RDL)
    rc = main([str(rdl), "-o", str(tmp_path),
               "--addr-width", "16",
               "--no-config"])
    assert rc == 0
    arch = (tmp_path / "m.arch").read_text()
    assert "param ADDR_W: const = 16;" in arch


def test_cli_port_name_flag(tmp_path: Path) -> None:
    from rdl2arch.__main__ import main
    rdl = tmp_path / "m.rdl"
    rdl.write_text(_TINY_RDL)
    rc = main([str(rdl), "-o", str(tmp_path),
               "--port-name", "s_axi_dbg",
               "--no-config"])
    assert rc == 0
    arch = (tmp_path / "m.arch").read_text()
    assert "port s_axi_dbg: target" in arch


def test_cli_combinational_readback_flag(tmp_path: Path) -> None:
    from rdl2arch.__main__ import main
    rdl = tmp_path / "m.rdl"
    rdl.write_text(_TINY_RDL)
    rc = main([str(rdl), "-o", str(tmp_path),
               "--combinational-readback", "true",
               "--no-config"])
    assert rc == 0
    arch = (tmp_path / "m.arch").read_text()
    assert "rdata_r <= rdata_mux" not in arch


def test_cli_auto_discovery_loads_config(tmp_path: Path, monkeypatch) -> None:
    """CLI picks up rdl2arch.toml from CWD via walk-up."""
    from rdl2arch.__main__ import main
    rdl = tmp_path / "m.rdl"
    rdl.write_text(_TINY_RDL)
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [rdl2arch]
        reset_style = "async-low"
        addr_width = 12
        """
    )
    monkeypatch.chdir(tmp_path)
    rc = main([str(rdl), "-o", str(tmp_path)])
    assert rc == 0
    arch = (tmp_path / "m.arch").read_text()
    assert "Reset<Async, Low>" in arch
    assert "param ADDR_W: const = 12;" in arch


def test_cli_flag_wins_over_config(tmp_path: Path, monkeypatch) -> None:
    """Precedence: CLI flag > config > default."""
    from rdl2arch.__main__ import main
    rdl = tmp_path / "m.rdl"
    rdl.write_text(_TINY_RDL)
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [rdl2arch]
        reset_style = "async-low"
        """
    )
    monkeypatch.chdir(tmp_path)
    # Config says async-low, CLI says async-high → CLI wins.
    rc = main([str(rdl), "-o", str(tmp_path),
               "--reset-style", "async-high"])
    assert rc == 0
    arch = (tmp_path / "m.arch").read_text()
    assert "Reset<Async>" in arch
    assert "Reset<Async, Low>" not in arch


def test_cli_config_wins_over_default(tmp_path: Path, monkeypatch) -> None:
    """With no CLI flag, config value beats library default."""
    from rdl2arch.__main__ import main
    rdl = tmp_path / "m.rdl"
    rdl.write_text(_TINY_RDL)
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [cpuif.axi4-lite]
        port_name = "s_axi_alt"
        """
    )
    monkeypatch.chdir(tmp_path)
    rc = main([str(rdl), "-o", str(tmp_path)])
    assert rc == 0
    arch = (tmp_path / "m.arch").read_text()
    assert "port s_axi_alt: target" in arch


def test_cli_config_per_cpuif_only_applies_to_selected(tmp_path: Path, monkeypatch) -> None:
    """When `--cpuif apb4` is selected, the `[cpuif.axi4-lite]` section
    is ignored."""
    from rdl2arch.__main__ import main
    rdl = tmp_path / "m.rdl"
    rdl.write_text(_TINY_RDL)
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [cpuif.axi4-lite]
        port_name = "s_axi_alt"

        [cpuif.apb4]
        port_name = "s_apb_alt"
        """
    )
    monkeypatch.chdir(tmp_path)
    rc = main([str(rdl), "-o", str(tmp_path), "--cpuif", "apb4"])
    assert rc == 0
    arch = (tmp_path / "m.arch").read_text()
    assert "port s_apb_alt: target" in arch
    assert "s_axi_alt" not in arch


def test_cli_explicit_config_path(tmp_path: Path) -> None:
    """`--config <path>` loads that file and skips auto-discovery."""
    from rdl2arch.__main__ import main
    rdl = tmp_path / "m.rdl"
    rdl.write_text(_TINY_RDL)
    cfg_path = tmp_path / "custom.toml"
    cfg_path.write_text('[rdl2arch]\naddr_width = 20\n')
    rc = main([str(rdl), "-o", str(tmp_path), "--config", str(cfg_path)])
    assert rc == 0
    arch = (tmp_path / "m.arch").read_text()
    assert "param ADDR_W: const = 20;" in arch


def test_cli_no_config_skips_discovery(tmp_path: Path, monkeypatch) -> None:
    """--no-config ignores even an adjacent rdl2arch.toml."""
    from rdl2arch.__main__ import main
    rdl = tmp_path / "m.rdl"
    rdl.write_text(_TINY_RDL)
    (tmp_path / "rdl2arch.toml").write_text(
        '[rdl2arch]\naddr_width = 12\n'
    )
    monkeypatch.chdir(tmp_path)
    rc = main([str(rdl), "-o", str(tmp_path), "--no-config"])
    assert rc == 0
    arch = (tmp_path / "m.arch").read_text()
    # Default (auto-derived) width for a single 32-bit reg at 0x0: addr=0x3,
    # bit_length == 2. Confirm the override did NOT take effect.
    assert "param ADDR_W: const = 12;" not in arch


def test_cli_config_error_exits_nonzero(tmp_path: Path, monkeypatch, capsys) -> None:
    """A malformed config file fails loudly before any RDL compile."""
    from rdl2arch.__main__ import main
    rdl = tmp_path / "m.rdl"
    rdl.write_text(_TINY_RDL)
    (tmp_path / "rdl2arch.toml").write_text(
        """
        [rdl2arch]
        reset_style = "bogus"
        """
    )
    monkeypatch.chdir(tmp_path)
    rc = main([str(rdl), "-o", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "reset_style" in err
