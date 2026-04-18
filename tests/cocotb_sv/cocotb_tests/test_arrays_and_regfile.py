"""cocotb tests for the `arrays_and_regfile` RDL fixture."""

import cocotb

from common import setup


@cocotb.test()
async def array_independent_state(dut):
    drv = await setup(dut)
    await drv.write(0x00, 0x11)
    await drv.write(0x04, 0x22)
    await drv.write(0x08, 0x33)
    await drv.write(0x0C, 0x44)
    assert await drv.read(0x00) == 0x11
    assert await drv.read(0x04) == 0x22
    assert await drv.read(0x08) == 0x33
    assert await drv.read(0x0C) == 0x44


@cocotb.test()
async def regfile_addresses(dut):
    drv = await setup(dut)
    await drv.write(0x24, 0xAB)           # irq.enable
    assert await drv.read(0x24) & 0xFF == 0xAB
    await drv.write(0x20, 0xFF)           # irq.status is woclr
    assert await drv.read(0x20) & 0xFF == 0x00
