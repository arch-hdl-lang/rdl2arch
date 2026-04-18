"""cocotb tests for the `minimal` RDL fixture."""

import cocotb
from cocotb.triggers import RisingEdge

from common import setup


@cocotb.test()
async def reset_values(dut):
    drv = await setup(dut)
    # Ctrl resets to 0.
    assert await drv.read(0x0) == 0x0
    # Status: hwif_in.status_status_code not driven -> reads 0.
    dut.hwif_in.value = 0
    await RisingEdge(dut.clk)
    assert await drv.read(0x4) == 0x0


@cocotb.test()
async def ctrl_write_read(dut):
    drv = await setup(dut)
    # enable[0]=1, mode[4:1]=0xA => wdata = (0xA<<1)|1 = 0x15
    await drv.write(0x0, 0x15)
    assert await drv.read(0x0) == 0x15
    # ARCH packs structs LSB→MSB in declaration order. hwif_out has
    # ctrl_enable first (→ bit[0]) and ctrl_mode second (→ bits[4:1]).
    hw = int(dut.hwif_out.value)
    assert hw & 0x1 == 1, f"ctrl_enable={hw & 0x1}"
    assert (hw >> 1) & 0xF == 0xA, f"ctrl_mode={(hw >> 1) & 0xF:#x}"


@cocotb.test()
async def status_mirrors_hwif_in(dut):
    drv = await setup(dut)
    dut.hwif_in.value = 0x42
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    assert await drv.read(0x4) == 0x42
