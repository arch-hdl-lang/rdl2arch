"""cocotb tests for the `readonly` RDL fixture."""

import cocotb
from cocotb.triggers import RisingEdge

from common import setup


@cocotb.test()
async def hwif_in_to_readback(dut):
    drv = await setup(dut)
    # readonly_ip.sensor packs {temperature[15:0], pressure[31:16]} in RDL.
    # hwif_in has two 16-bit fields — packed LSB-first in declaration order
    # of the struct (temperature first → LSB at bits[15:0], pressure → [31:16]).
    # Drive the packed value and verify readback.
    dut.hwif_in.value = (0xBEEF << 16) | 0xCAFE
    for _ in range(2):
        await RisingEdge(dut.clk)
    rd = await drv.read(0x0)
    assert rd == ((0xBEEF << 16) | 0xCAFE), f"got {rd:#x}"
