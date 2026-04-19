"""cocotb tests for the `readonly` RDL fixture."""

import cocotb
from cocotb.triggers import RisingEdge

from common import setup


@cocotb.test()
async def hwif_in_to_readback(dut):
    drv = await setup(dut)
    # RDL spec: sensor register is {temperature[15:0], pressure[31:16]}.
    # hwif_in struct = {sensor_temperature, sensor_pressure}; first-declared
    # is MSB in the packed struct, so hwif_in bit layout is:
    #   [31:16] sensor_temperature, [15:0] sensor_pressure.
    # Register readback is MSB-first concat {pressure, temperature}:
    #   [31:16] pressure, [15:0] temperature.
    temperature = 0x1234
    pressure    = 0x5678
    dut.hwif_in.value = (temperature << 16) | pressure
    for _ in range(2):
        await RisingEdge(dut.clk)
    rd = await drv.read(0x0)
    assert rd == (pressure << 16) | temperature, f"got {rd:#x}"
