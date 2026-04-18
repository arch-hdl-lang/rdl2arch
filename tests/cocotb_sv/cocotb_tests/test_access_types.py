"""cocotb tests for the `access_types` RDL fixture."""

import cocotb

from common import setup


@cocotb.test()
async def w1c_clears(dut):
    drv = await setup(dut)
    await drv.write(0x0, 0x0F << 24)   # woclr on mixed.w1c_field[31:24] (reset 0xff)
    rd = await drv.read(0x0)
    assert (rd >> 24) & 0xFF == 0xF0, f"w1c={(rd >> 24) & 0xFF:#x}"


@cocotb.test()
async def w1s_sets(dut):
    drv = await setup(dut)
    await drv.write(0x4, 0xAA)   # woset on writes.w1s_field[7:0] (reset 0x00)
    rd = await drv.read(0x4)
    assert rd & 0xFF == 0xAA


@cocotb.test()
async def wclr_any_write(dut):
    drv = await setup(dut)
    await drv.write(0x4, 0xAB << 16)   # wclr clears regardless of wdata
    rd = await drv.read(0x4)
    assert (rd >> 16) & 0xFF == 0x00


@cocotb.test()
async def wot_toggles(dut):
    drv = await setup(dut)
    await drv.write(0x4, 0xAA << 24)   # toggle bits
    rd = await drv.read(0x4)
    assert (rd >> 24) & 0xFF == 0xAA
    await drv.write(0x4, 0xFF << 24)
    rd = await drv.read(0x4)
    assert (rd >> 24) & 0xFF == (0xAA ^ 0xFF)


@cocotb.test()
async def rclr_on_read(dut):
    drv = await setup(dut)
    rd1 = await drv.read(0x8)
    assert rd1 & 0xFF == 0xFF
    rd2 = await drv.read(0x8)
    assert rd2 & 0xFF == 0x00


@cocotb.test()
async def rset_on_read(dut):
    drv = await setup(dut)
    rd1 = await drv.read(0x8)
    assert (rd1 >> 8) & 0xFF == 0x00
    rd2 = await drv.read(0x8)
    assert (rd2 >> 8) & 0xFF == 0xFF
