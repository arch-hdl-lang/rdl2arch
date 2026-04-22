"""cocotb tests for the `interrupts` RDL fixture.

Exercises the sticky / intr / enable-mask plumbing end-to-end against
the generated SV:

  - Sticky latching: a 1-cycle pulse on `hwif_in.irq_status_<src>`
    stays visible in SW readback until SW writes 1 to clear.
  - Enable linkage: `irq_status.rx_done->enable = irq_enable.rx_done_en`
    suppresses the intr output until SW arms the enable.
  - Mask linkage: `irq_status.err->mask = irq_enable.err_mask`
    inverts the polarity — enable-side disables, mask-side disables.
  - Non-sticky `live` field mirrors hwif_in each cycle and contributes
    to the intr output without latching.

Field bit order inside the packed struct matches declaration order
(MSB first), so `hwif_in` layout is:
  bit 3: irq_status_rx_done (MSB)
  bit 2: irq_status_tx_done
  bit 1: irq_status_err
  bit 0: irq_status_live  (LSB)
"""

import cocotb
from cocotb.triggers import RisingEdge

from common import setup


# --- hwif_in bit helpers --------------------------------------------------
# Declaration-order MSB-first: rx_done=bit3, tx_done=bit2, err=bit1, live=bit0.
_RX_DONE = 1 << 3
_TX_DONE = 1 << 2
_ERR     = 1 << 1
_LIVE    = 1 << 0


async def _pulse_hwif(dut, mask: int, cycles: int = 1) -> None:
    dut.hwif_in.value = mask
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.hwif_in.value = 0
    await RisingEdge(dut.clk)


# --- reset values ---------------------------------------------------------


@cocotb.test()
async def reset_clears_everything(dut):
    drv = await setup(dut)
    assert await drv.read(0x0) == 0, "irq_status should reset to 0"
    assert await drv.read(0x4) == 0, "irq_enable should reset to 0"
    assert int(dut.irq_status_intr.value) == 0, "intr out should be 0 at reset"


# --- sticky latching ------------------------------------------------------


@cocotb.test()
async def sticky_latches_hw_pulse(dut):
    """A 1-cycle hw pulse on rx_done should stay latched in the status
    register until SW write-1-to-clear."""
    drv = await setup(dut)
    # Arm enable first so we can observe the masked intr output too.
    await drv.write(0x4, 0x1)  # rx_done_en = 1

    await _pulse_hwif(dut, _RX_DONE, cycles=1)
    # Status reads 1 even though hwif_in dropped back to 0 a cycle ago.
    assert await drv.read(0x0) & 0x1 == 1, "rx_done should be sticky"
    # Intr output asserted (enabled & latched).
    assert int(dut.irq_status_intr.value) == 1

    # SW w1c clears it.
    await drv.write(0x0, 0x1)
    assert await drv.read(0x0) & 0x1 == 0, "rx_done should be cleared"
    assert int(dut.irq_status_intr.value) == 0


# --- enable-companion linkage --------------------------------------------


@cocotb.test()
async def enable_gates_intr_output(dut):
    """With enable = 0, a latched bit still reads 1 in status but does
    NOT drive irq_status_intr. Arming the enable surfaces the intr."""
    drv = await setup(dut)
    await _pulse_hwif(dut, _TX_DONE)
    # tx_done is sticky → bit 1 is set in status.
    assert await drv.read(0x0) & 0x2 == 0x2
    # Enable for tx_done is 0 → intr out stays low.
    assert int(dut.irq_status_intr.value) == 0

    # Arm enable → intr asserts immediately (combinational path).
    await drv.write(0x4, 0x2)  # tx_done_en = 1
    # Same-cycle comb — read after one edge for settle.
    await RisingEdge(dut.clk)
    assert int(dut.irq_status_intr.value) == 1


# --- mask-companion linkage (inverted polarity) --------------------------


@cocotb.test()
async def mask_inverts_enable_polarity(dut):
    """`err->mask` uses opposite polarity from `enable`: mask=0 passes
    the source through, mask=1 suppresses it."""
    drv = await setup(dut)
    await _pulse_hwif(dut, _ERR)
    assert await drv.read(0x0) & 0x4 == 0x4, "err should be latched"

    # mask=0 → intr visible.
    await RisingEdge(dut.clk)
    assert int(dut.irq_status_intr.value) == 1

    # Assert mask → intr suppressed even though err bit is still latched.
    await drv.write(0x4, 0x4)  # err_mask = 1
    await RisingEdge(dut.clk)
    assert int(dut.irq_status_intr.value) == 0
    assert await drv.read(0x0) & 0x4 == 0x4, "err still latched in status"


# --- non-sticky `live` source --------------------------------------------


@cocotb.test()
async def live_field_is_transparent(dut):
    """The non-sticky `live` field should follow hwif_in each cycle
    (no OR-latch) and contribute to the intr output with no linkage."""
    drv = await setup(dut)

    dut.hwif_in.value = _LIVE
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    # `live` reads 1 while hwif_in holds.
    assert await drv.read(0x0) & 0x8 == 0x8
    assert int(dut.irq_status_intr.value) == 1

    # Drop hwif_in → live follows on the next edge (no sticky latch).
    dut.hwif_in.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    assert await drv.read(0x0) & 0x8 == 0, "live should NOT be sticky"
    assert int(dut.irq_status_intr.value) == 0


# --- multi-source OR reduction -------------------------------------------


@cocotb.test()
async def intr_output_is_or_of_sources(dut):
    """Any one enabled+latched source should drive the composite intr
    output; clearing every source should take it low."""
    drv = await setup(dut)
    # Arm every enable bit.
    await drv.write(0x4, 0x3)  # rx_done_en | tx_done_en; err_mask stays 0

    # rx_done → intr high
    await _pulse_hwif(dut, _RX_DONE)
    await RisingEdge(dut.clk)
    assert int(dut.irq_status_intr.value) == 1

    # Add err latch → intr still high (mask is 0 so err contributes)
    await _pulse_hwif(dut, _ERR)
    await RisingEdge(dut.clk)
    assert int(dut.irq_status_intr.value) == 1

    # Clear both sticky bits → intr drops.
    await drv.write(0x0, 0x1 | 0x4)
    await RisingEdge(dut.clk)
    assert int(dut.irq_status_intr.value) == 0
