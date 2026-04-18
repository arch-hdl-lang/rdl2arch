"""Shared helpers for cocotb + Verilator tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


# Make the shared driver modules importable regardless of how cocotb launched.
_HERE = Path(__file__).resolve().parent
_PKG_ROOT = _HERE.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from drivers.apb4 import Apb4Driver  # noqa: E402
from drivers.axi4lite import Axi4LiteDriver  # noqa: E402


def make_driver(dut):
    """Construct the right bus driver based on COCOTB_CPUIF env var."""
    cpuif = os.environ.get("COCOTB_CPUIF", "axi4-lite")
    if cpuif == "axi4-lite":
        return Axi4LiteDriver(dut, port="s_axi")
    if cpuif == "apb4":
        return Apb4Driver(dut, port="s_apb")
    raise RuntimeError(f"Unknown COCOTB_CPUIF={cpuif!r}")


async def setup(dut):
    """Start clock, apply reset, init driver, return the driver."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    drv = make_driver(dut)
    dut.rst.value = 1
    await drv.init()
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)
    return drv
