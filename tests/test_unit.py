"""Unit tests for identifier_filter and validator error paths."""

import pytest
from systemrdl import RDLCompiler

from rdl2arch.identifier_filter import filter_identifier
from rdl2arch.scan_design import scan
from rdl2arch.validate_design import UnsupportedRdlError, validate


def _compile_rdl(tmp_path, source: str):
    rdl = tmp_path / "x.rdl"
    rdl.write_text(source)
    rdlc = RDLCompiler()
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
    assert d.regs[0].address == 0x10
    assert d.regs[1].address == 0x14


def test_scan_reg_array_unrolls(tmp_path) -> None:
    top = _compile_rdl(tmp_path, """
        addrmap t {
            reg {
                field { sw = rw; hw = r; reset = 0; } v[7:0];
            } ch[3] @ 0x0 += 0x4;
        };
    """)
    d = scan(top)
    assert [r.name for r in d.regs] == ["ch_0", "ch_1", "ch_2"]
    assert [r.address for r in d.regs] == [0x0, 0x4, 0x8]


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
