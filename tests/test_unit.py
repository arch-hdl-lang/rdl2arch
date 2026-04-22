"""Unit tests for identifier_filter and validator error paths."""

import pytest
from systemrdl import RDLCompiler

from rdl2arch.identifier_filter import filter_identifier
from rdl2arch.scan_design import scan
from rdl2arch.udps import ALL_UDPS
from rdl2arch.validate_design import UnsupportedRdlError, validate


def _compile_rdl(tmp_path, source: str):
    rdl = tmp_path / "x.rdl"
    rdl.write_text(source)
    rdlc = RDLCompiler()
    for udp in ALL_UDPS:
        rdlc.register_udp(udp, soft=False)
    rdlc.compile_file(str(rdl))
    return rdlc.elaborate().top


def test_identifier_filter_reserved() -> None:
    assert filter_identifier("bus") == "bus_"
    assert filter_identifier("match") == "match_"
    assert filter_identifier("SysDomain") == "SysDomain_"
    assert filter_identifier("enable") == "enable"


def test_scan_basic(tmp_path) -> None:
    top = _compile_rdl(tmp_path, """
        addrmap tiny {
            reg {
                field { sw = rw; hw = r; reset = 0x1; } go[0:0];
            } ctrl @ 0x0;
        };
    """)
    d = scan(top)
    assert d.module_name == "Tiny"
    assert d.package_name == "TinyPkg"
    assert len(d.regs) == 1
    assert d.regs[0].name == "ctrl"
    assert d.regs[0].fields[0].name == "go"
    assert d.regs[0].fields[0].reset == 1


def test_scan_regfile_flattens(tmp_path) -> None:
    top = _compile_rdl(tmp_path, """
        addrmap t {
            regfile {
                reg { field { sw = rw; hw = r; reset = 0; } f[0:0]; } r0 @ 0x0;
                reg { field { sw = rw; hw = r; reset = 0; } f[0:0]; } r1 @ 0x4;
            } rf @ 0x10;
        };
    """)
    d = scan(top)
    names = [r.name for r in d.regs]
    assert names == ["rf_r0", "rf_r1"]
    assert d.regs[0].base_address == 0x10
    assert d.regs[1].base_address == 0x14
    # Regs inside a regfile container are scalar, not array.
    assert d.regs[0].array_count is None


def test_scan_reg_array_kept_as_one(tmp_path) -> None:
    """RDL `reg ch[3]` becomes one RegModel with array_count=3 (one
    Vec-typed reg in the generated ARCH), not three separately-named
    scalar RegModels."""
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                field { sw = rw; hw = r; reset = 0; } v[7:0];
            } ch[3] @ 0x0 += 0x4;
        };
    """)
    d = scan(top)
    assert len(d.regs) == 1
    reg = d.regs[0]
    assert reg.name == "ch"
    assert reg.array_count == 3
    assert reg.array_stride == 4
    assert reg.base_address == 0x0
    # `elements()` enumerates per-instance addresses for the address decode.
    assert list(reg.elements()) == [(0, 0x0), (1, 0x4), (2, 0x8)]
    # State references use Vec subscript form.
    assert reg.state_ref(0) == "ch_r[0]"
    assert reg.state_ref(2) == "ch_r[2]"


def test_validate_rejects_mem(tmp_path) -> None:
    top = _compile_rdl(tmp_path, """
        addrmap t {
            external mem {
                mementries = 16;
                memwidth = 32;
            } buf @ 0x100;
        };
    """)
    d = scan(top)
    with pytest.raises(UnsupportedRdlError, match="mem"):
        validate(d)


# ── emit_read_pulse / emit_write_pulse UDPs ────────────────────────────────


def test_scan_default_pulse_flags_false(tmp_path) -> None:
    """Regs without the UDP get emit_*_pulse = False."""
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg { field { sw = rw; hw = r; reset = 0; } v[31:0]; } r0 @ 0x0;
        };
    """)
    d = scan(top)
    assert d.regs[0].emit_read_pulse is False
    assert d.regs[0].emit_write_pulse is False


def test_scan_picks_up_read_pulse(tmp_path) -> None:
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                emit_read_pulse = true;
                field { sw = r; hw = w; reset = 0; } v[31:0];
            } claim @ 0x0;
        };
    """)
    d = scan(top)
    assert d.regs[0].emit_read_pulse is True
    assert d.regs[0].emit_write_pulse is False


def test_scan_picks_up_write_pulse(tmp_path) -> None:
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                emit_write_pulse = true;
                field { sw = w; hw = r; reset = 0; } v[31:0];
            } complete @ 0x0;
        };
    """)
    d = scan(top)
    assert d.regs[0].emit_read_pulse is False
    assert d.regs[0].emit_write_pulse is True


def test_emit_pulse_ports_and_comb(tmp_path) -> None:
    """End-to-end: scan → emit produces the expected ports + comb assigns."""
    from rdl2arch.cpuif.axi4lite import AXI4Lite_Cpuif
    from rdl2arch.emit_regblock import emit_regblock
    top = _compile_rdl(tmp_path, """
        addrmap p {
            reg {
                emit_read_pulse = true;
                field { sw = r; hw = w; reset = 0; } v[31:0];
            } claim @ 0x0;
            reg {
                emit_write_pulse = true;
                field { sw = w; hw = r; reset = 0; } v[31:0];
            } complete @ 0x4;
            reg {
                emit_read_pulse = true;
                emit_write_pulse = true;
                field { sw = rw; hw = rw; reset = 0; } v[31:0];
            } both @ 0x8;
            reg {
                // No UDP — no pulse ports for this one.
                field { sw = rw; hw = r; reset = 0; } v[31:0];
            } plain @ 0xC;
        };
    """)
    d = scan(top)
    src = emit_regblock(d, AXI4Lite_Cpuif(d.addr_width, d.data_width))

    # Port declarations
    assert "port claim_read_pulse:" in src
    assert "port complete_write_pulse:" in src
    assert "port both_read_pulse:" in src
    assert "port both_write_pulse:" in src
    # Unflagged reg must NOT get pulse ports
    assert "plain_read_pulse" not in src
    assert "plain_write_pulse" not in src
    # Comb assignments wire the pulse to rd_fire/wr_fire + address match
    assert "claim_read_pulse  = rd_fire and" in src
    assert "complete_write_pulse = wr_fire and" in src


def test_reset_style_defaults_to_sync(tmp_path) -> None:
    """Default `reset_style` keeps the historical `Reset<Sync>` emit
    so existing callers aren't silently changed."""
    from rdl2arch.cpuif.axi4lite import AXI4Lite_Cpuif
    from rdl2arch.emit_regblock import emit_regblock
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                field { sw = rw; hw = r; reset = 0; } v[31:0];
            } r0 @ 0x0;
        };
    """)
    d = scan(top)
    src = emit_regblock(d, AXI4Lite_Cpuif(d.addr_width, d.data_width))
    assert "port rst:      in Reset<Sync>;" in src
    assert "Reset<Async" not in src


def test_reset_style_async_low_emits_async_negative(tmp_path) -> None:
    """`ASYNC_LOW` emits `Reset<Async, Low>` — needed for clock-gated
    RISC-V integrations (Ibex `rst_ni`)."""
    from rdl2arch import ResetStyle  # re-exported at top level
    from rdl2arch.cpuif.axi4lite import AXI4Lite_Cpuif
    from rdl2arch.emit_regblock import emit_regblock
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                field { sw = rw; hw = r; reset = 0; } v[31:0];
            } r0 @ 0x0;
        };
    """)
    d = scan(top)
    src = emit_regblock(
        d,
        AXI4Lite_Cpuif(d.addr_width, d.data_width),
        reset_style=ResetStyle.ASYNC_LOW,
    )
    assert "port rst:      in Reset<Async, Low>;" in src
    assert "Reset<Sync>" not in src


def test_reset_style_async_high(tmp_path) -> None:
    from rdl2arch import ResetStyle
    from rdl2arch.cpuif.axi4lite import AXI4Lite_Cpuif
    from rdl2arch.emit_regblock import emit_regblock
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                field { sw = rw; hw = r; reset = 0; } v[31:0];
            } r0 @ 0x0;
        };
    """)
    d = scan(top)
    src = emit_regblock(
        d,
        AXI4Lite_Cpuif(d.addr_width, d.data_width),
        reset_style=ResetStyle.ASYNC_HIGH,
    )
    assert "port rst:      in Reset<Async>;" in src


def test_cli_reset_style_flag(tmp_path) -> None:
    """`--reset-style async-low` flows through to the emitted `.arch`."""
    from rdl2arch.__main__ import main
    rdl_file = tmp_path / "mini.rdl"
    rdl_file.write_text("""
        addrmap m {
            reg {
                field { sw = rw; hw = r; reset = 0; } v[31:0];
            } r0 @ 0x0;
        };
    """)
    rc = main([
        str(rdl_file),
        "-o", str(tmp_path),
        "--reset-style", "async-low",
    ])
    assert rc == 0
    mod_src = (tmp_path / "m.arch").read_text()
    assert "port rst:      in Reset<Async, Low>;" in mod_src


def test_emit_pulse_rejects_array_regs(tmp_path) -> None:
    """v1: pulse UDPs on an array reg is rejected (per-element pulse
    would need a UInt<N> output which we haven't implemented yet)."""
    from rdl2arch.cpuif.axi4lite import AXI4Lite_Cpuif
    from rdl2arch.emit_regblock import emit_regblock
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                emit_read_pulse = true;
                field { sw = r; hw = w; reset = 0; } v[31:0];
            } slots[4] @ 0x0;
        };
    """)
    d = scan(top)
    with pytest.raises(ValueError, match="emit_read_pulse"):
        emit_regblock(d, AXI4Lite_Cpuif(d.addr_width, d.data_width))


# =========================================================================
# Interrupt / sticky support
# =========================================================================


_IRQ_RDL = """
    addrmap t {
        reg {
            field { sw=rw; hw=w; onwrite=woclr; intr; } a[0:0];
            field { sw=rw; hw=w; onwrite=woclr; intr; } b[1:1];
        } irq_status @ 0x0;
        reg {
            field { sw=rw; hw=r; reset=0x0; } ea[0:0];
            field { sw=rw; hw=r; reset=0x0; } eb[1:1];
        } irq_enable @ 0x4;
        irq_status.a->enable = irq_enable.ea;
        irq_status.b->mask   = irq_enable.eb;
    };
"""


def test_scan_captures_intr_properties(tmp_path) -> None:
    top = _compile_rdl(tmp_path, _IRQ_RDL)
    d = scan(top)
    irq_status = next(r for r in d.regs if r.name == "irq_status")
    irq_enable = next(r for r in d.regs if r.name == "irq_enable")

    assert irq_status.has_intr_field is True
    assert irq_enable.has_intr_field is False

    a = next(f for f in irq_status.fields if f.name == "a")
    b = next(f for f in irq_status.fields if f.name == "b")
    # RDL auto-sets stickybit=true when intr is declared.
    assert a.is_intr and a.is_stickybit
    assert b.is_intr and b.is_stickybit
    # Enable linkage is a FieldNode; mask is None on `a` (only `b` has it).
    assert a.enable_field is not None
    assert a.mask_field is None
    assert b.enable_field is None
    assert b.mask_field is not None


def test_emit_sticky_hw_set_lane(tmp_path) -> None:
    """Sticky + intr fields emit `state <= state | hwif_in` (OR-latch),
    non-intr hw-writable fields emit the plain `state <= hwif_in` copy."""
    from rdl2arch.cpuif.axi4lite import AXI4Lite_Cpuif
    from rdl2arch.emit_regblock import emit_regblock
    top = _compile_rdl(tmp_path, _IRQ_RDL)
    d = scan(top)
    src = emit_regblock(d, AXI4Lite_Cpuif(d.addr_width, d.data_width))
    # Sticky OR-latch for the intr sources.
    assert "irq_status_r.a <= irq_status_r.a | hwif_in.irq_status_a;" in src
    assert "irq_status_r.b <= irq_status_r.b | hwif_in.irq_status_b;" in src
    # The enable register's fields are `hw = r` (not hw-writable), so no
    # hwif_in-sourced seq assignment should be emitted for them. The SW
    # write lane still assigns `irq_enable_r.ea <= s_axi.w_data[0]` which
    # is expected — we only exclude the HW-driven ones.
    assert "irq_enable_r.ea <= hwif_in" not in src
    assert "irq_enable_r.eb <= hwif_in" not in src


def test_emit_intr_output_port_and_comb(tmp_path) -> None:
    """A reg with any `intr` field gets a `<reg>_intr: out Bool` port
    and an OR-reduced comb assignment honoring enable/mask linkage."""
    from rdl2arch.cpuif.axi4lite import AXI4Lite_Cpuif
    from rdl2arch.emit_regblock import emit_regblock
    top = _compile_rdl(tmp_path, _IRQ_RDL)
    d = scan(top)
    src = emit_regblock(d, AXI4Lite_Cpuif(d.addr_width, d.data_width))
    # Output port declared exactly once for the status reg; the enable
    # reg has no intr fields so it shouldn't get a port.
    assert "port irq_status_intr:" in src
    assert "port irq_enable_intr:" not in src
    # Comb equation: enable uses `& en`, mask uses `& ~mask`.
    assert "(irq_status_r.a & irq_enable_r.ea) != 1'h0" in src
    assert "(irq_status_r.b & (~irq_enable_r.eb)) != 1'h0" in src
    # Two contribs → `or` joined.
    assert " or " in src


def test_emit_plain_intr_field_contrib(tmp_path) -> None:
    """An intr field with no enable/mask linkage contributes a bare
    `<reg>_r.<f> != 0` term to the OR."""
    from rdl2arch.cpuif.axi4lite import AXI4Lite_Cpuif
    from rdl2arch.emit_regblock import emit_regblock
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                field { sw=rw; hw=w; onwrite=woclr; intr; } a[0:0];
            } irq @ 0x0;
        };
    """)
    d = scan(top)
    src = emit_regblock(d, AXI4Lite_Cpuif(d.addr_width, d.data_width))
    # Exactly one contribution — no parentheses + `or` needed.
    assert "irq_intr = irq_r.a != 1'h0;" in src


def test_emit_non_sticky_intr_field(tmp_path) -> None:
    """Explicit `stickybit = false` gives a transparent (non-latching)
    intr field — the hw-set lane is `<= hwif_in` (plain copy), not
    the OR-latch."""
    from rdl2arch.cpuif.axi4lite import AXI4Lite_Cpuif
    from rdl2arch.emit_regblock import emit_regblock
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                field { sw=r; hw=w; intr; stickybit = false; } live[0:0];
            } irq @ 0x0;
        };
    """)
    d = scan(top)
    src = emit_regblock(d, AXI4Lite_Cpuif(d.addr_width, d.data_width))
    assert "irq_r.live <= hwif_in.irq_live;" in src
    # No OR-latch RHS should appear.
    assert "irq_r.live | hwif_in" not in src


# --- validation error paths ---


def test_validate_rejects_edge_intr(tmp_path) -> None:
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                field { sw=rw; hw=w; posedge intr; } a[0:0];
            } r0 @ 0x0;
        };
    """)
    with pytest.raises(UnsupportedRdlError, match=r"intr type = posedge"):
        validate(scan(top))


def test_validate_rejects_field_wide_sticky(tmp_path) -> None:
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                field { sw=rw; hw=w; onwrite=woclr; sticky; intr; } a[3:0];
            } r0 @ 0x0;
        };
    """)
    with pytest.raises(UnsupportedRdlError, match=r"field-wide `sticky`"):
        validate(scan(top))


def test_validate_rejects_stickybit_without_intr(tmp_path) -> None:
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                field { sw=rw; hw=w; onwrite=woclr; stickybit; } a[0:0];
            } r0 @ 0x0;
        };
    """)
    with pytest.raises(UnsupportedRdlError, match=r"`stickybit` without `intr`"):
        validate(scan(top))


def test_validate_rejects_haltenable(tmp_path) -> None:
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                field { sw=rw; hw=w; onwrite=woclr; intr; } a[0:0];
                field { sw=rw; hw=r; reset=0; } h[1:1];
            } r0 @ 0x0;
            r0.a->haltenable = r0.h;
        };
    """)
    with pytest.raises(UnsupportedRdlError, match=r"haltenable"):
        validate(scan(top))
