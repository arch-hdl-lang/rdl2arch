"""Functional sim tests — verify actual register behavior, not just compilability.

Each test builds a pybind11-wrapped sim model from an RDL fixture, then exercises
it with an AXI4-Lite or APB4 driver, checking that register reads/writes behave
per the RDL spec.
"""

from pathlib import Path

import pytest

from rdl2arch.cpuif import APB4_Cpuif, AXI4Lite_Cpuif

from conftest import RDL_DIR
from sim.apb4_driver import Apb4Driver
from sim.axi4lite_driver import Axi4LiteDriver, reset, tick
from sim.harness import build_sim, fresh_dut


pytest.importorskip("pybind11")


# ── minimal.rdl ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def minimal_axi(arch_bin, tmp_path_factory):
    return build_sim(RDL_DIR / "minimal.rdl", AXI4Lite_Cpuif,
                     tmp_path_factory.mktemp("minimal_axi"), arch_bin)


def test_minimal_reset_values(minimal_axi) -> None:
    dut = fresh_dut(minimal_axi)
    reset(dut)
    drv = Axi4LiteDriver(dut)
    assert drv.read(0x0) == 0x0
    dut.hwif_in.status_status_code = 0
    tick(dut)
    assert drv.read(0x4) == 0x0


def test_minimal_ctrl_write_read(minimal_axi) -> None:
    dut = fresh_dut(minimal_axi)
    reset(dut)
    drv = Axi4LiteDriver(dut)
    # enable[0], mode[4:1]. Set mode=0xA, enable=1 → wdata = (0xA<<1)|1 = 0x15.
    drv.write(0x0, 0x15)
    assert drv.read(0x0) == 0x15
    assert dut.hwif_out.ctrl_enable == 1
    assert dut.hwif_out.ctrl_mode == 0xA


def test_minimal_status_mirrors_hwif_in(minimal_axi) -> None:
    dut = fresh_dut(minimal_axi)
    reset(dut)
    drv = Axi4LiteDriver(dut)
    dut.hwif_in.status_status_code = 0x42
    tick(dut); tick(dut)
    assert drv.read(0x4) == 0x42


def test_minimal_sw_only_field_not_hwif_out(minimal_axi) -> None:
    dut = fresh_dut(minimal_axi)
    assert not hasattr(dut.hwif_out, "status_status_code")


# ── access_types.rdl ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def access_axi(arch_bin, tmp_path_factory):
    return build_sim(RDL_DIR / "access_types.rdl", AXI4Lite_Cpuif,
                     tmp_path_factory.mktemp("access_axi"), arch_bin)


def test_w1c_clears_written_bits(access_axi) -> None:
    # w1c_field[31:24] reset=0xff, onwrite=woclr.
    dut = fresh_dut(access_axi)
    reset(dut)
    drv = Axi4LiteDriver(dut)
    # After reset: w1c_field = 0xff. Write 0x0F to bits[31:24] → cleared bits = 0x0F.
    # Expect field = 0xff & ~0x0F = 0xF0.
    drv.write(0x0, 0x0F << 24)
    rd = drv.read(0x0)
    assert (rd >> 24) & 0xFF == 0xF0, f"w1c got {(rd >> 24) & 0xFF:#x}"


def test_w1s_sets_written_bits(access_axi) -> None:
    # writes.w1s_field[7:0] reset=0x0, onwrite=woset.
    dut = fresh_dut(access_axi)
    reset(dut)
    drv = Axi4LiteDriver(dut)
    drv.write(0x4, 0xAA)
    rd = drv.read(0x4)
    assert rd & 0xFF == 0xAA


def test_wclr_any_write_clears(access_axi) -> None:
    # writes.any_clr[23:16] reset=0xf0, onwrite=wclr (any write → zero).
    dut = fresh_dut(access_axi)
    reset(dut)
    drv = Axi4LiteDriver(dut)
    # Write with random data at bits[23:16] — field should go to 0 regardless.
    drv.write(0x4, 0xAB << 16)
    rd = drv.read(0x4)
    assert (rd >> 16) & 0xFF == 0x00


def test_toggle_field(access_axi) -> None:
    # writes.toggle_field[31:24] reset=0x00, onwrite=wot (write-one-to-toggle).
    dut = fresh_dut(access_axi)
    reset(dut)
    drv = Axi4LiteDriver(dut)
    drv.write(0x4, 0xAA << 24)   # toggle bits {7,5,3,1}
    rd = drv.read(0x4)
    assert (rd >> 24) & 0xFF == 0xAA
    drv.write(0x4, 0xFF << 24)   # toggle every bit
    rd = drv.read(0x4)
    assert (rd >> 24) & 0xFF == (0xAA ^ 0xFF)


def test_rclr_on_read(access_axi) -> None:
    # reads.rclr_field[7:0] reset=0xff, onread=rclr.
    dut = fresh_dut(access_axi)
    reset(dut)
    drv = Axi4LiteDriver(dut)
    rd1 = drv.read(0x8)
    assert rd1 & 0xFF == 0xFF
    rd2 = drv.read(0x8)
    assert rd2 & 0xFF == 0x00, "rclr should clear after read"


def test_rset_on_read(access_axi) -> None:
    # reads.rset_field[15:8] reset=0x00, onread=rset.
    dut = fresh_dut(access_axi)
    reset(dut)
    drv = Axi4LiteDriver(dut)
    rd1 = drv.read(0x8)
    assert (rd1 >> 8) & 0xFF == 0x00
    rd2 = drv.read(0x8)
    assert (rd2 >> 8) & 0xFF == 0xFF, "rset should set after read"


# ── arrays_and_regfile.rdl ───────────────────────────────────────────────────

@pytest.fixture(scope="module")
def channelized_axi(arch_bin, tmp_path_factory):
    return build_sim(RDL_DIR / "arrays_and_regfile.rdl", AXI4Lite_Cpuif,
                     tmp_path_factory.mktemp("chan_axi"), arch_bin)


def test_reg_array_independent_state(channelized_axi) -> None:
    # ch[4] at 0x00, 0x04, 0x08, 0x0c. Writing one must not affect others.
    dut = fresh_dut(channelized_axi)
    reset(dut)
    drv = Axi4LiteDriver(dut)
    drv.write(0x00, 0x11)
    drv.write(0x04, 0x22)
    drv.write(0x08, 0x33)
    drv.write(0x0C, 0x44)
    assert drv.read(0x00) == 0x11
    assert drv.read(0x04) == 0x22
    assert drv.read(0x08) == 0x33
    assert drv.read(0x0C) == 0x44


def test_regfile_addresses(channelized_axi) -> None:
    # irq.status @ 0x20, irq.enable @ 0x24
    dut = fresh_dut(channelized_axi)
    reset(dut)
    drv = Axi4LiteDriver(dut)
    drv.write(0x24, 0xAB)
    assert drv.read(0x24) & 0xFF == 0xAB
    # irq.status.pending is woclr — write 0xFF should clear to 0
    drv.write(0x20, 0xFF)
    assert drv.read(0x20) & 0xFF == 0x00


# ── APB fixture — reuse minimal.rdl over APB instead of AXI ─────────────────

@pytest.fixture(scope="module")
def minimal_apb(arch_bin, tmp_path_factory):
    # name_suffix gives this build a distinct pybind init symbol so it can
    # coexist in-process with the AXI build of the same RDL.
    return build_sim(RDL_DIR / "minimal.rdl", APB4_Cpuif,
                     tmp_path_factory.mktemp("minimal_apb"), arch_bin,
                     name_suffix="Apb")


def test_apb_ctrl_write_read(minimal_apb) -> None:
    dut = fresh_dut(minimal_apb)
    reset(dut)
    drv = Apb4Driver(dut)
    drv.write(0x0, 0x15)
    assert drv.read(0x0) == 0x15
    assert dut.hwif_out.ctrl_enable == 1
    assert dut.hwif_out.ctrl_mode == 0xA


def test_apb_status_hwif_in(minimal_apb) -> None:
    dut = fresh_dut(minimal_apb)
    reset(dut)
    drv = Apb4Driver(dut)
    dut.hwif_in.status_status_code = 0x7E
    tick(dut); tick(dut)
    assert drv.read(0x4) == 0x7E
