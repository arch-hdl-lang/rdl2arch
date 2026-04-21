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
