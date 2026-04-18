"""Async AXI4-Lite initiator driver for cocotb + Verilator.

Uses a simple "issue + wait for response" pattern: the driver never checks the
`aw_ready`/`ar_ready` handshake flag explicitly, since the rdl2arch regblock
accepts transactions on the first cycle after the master asserts valid. We
wait for `b_valid`/`r_valid` as the acceptance signal.
"""

from __future__ import annotations

from cocotb.triggers import ReadOnly, RisingEdge


class Axi4LiteDriver:
    def __init__(self, dut, *, port: str = "s_axi"):
        self.dut = dut
        self.prefix = port

    def _sig(self, name: str):
        return getattr(self.dut, f"{self.prefix}_{name}")

    async def init(self):
        self._sig("aw_valid").value = 0
        self._sig("w_valid").value = 0
        self._sig("ar_valid").value = 0
        self._sig("b_ready").value = 1
        self._sig("r_ready").value = 1
        self._sig("w_strb").value = 0xF
        self._sig("aw_prot").value = 0
        self._sig("ar_prot").value = 0

    async def write(self, addr: int, data: int, strb: int = 0xF, timeout: int = 32) -> None:
        self._sig("aw_addr").value = addr
        self._sig("w_data").value = data
        self._sig("w_strb").value = strb
        self._sig("aw_valid").value = 1
        self._sig("w_valid").value = 1
        # Wait for b_valid — the regblock raises it one cycle after it accepts
        # AW+W. Keep valid asserted until then.
        for _ in range(timeout):
            await RisingEdge(self.dut.clk)
            await ReadOnly()
            if int(self._sig("b_valid").value):
                break
        else:
            raise TimeoutError(f"AXI write b_valid timeout @ {addr:#x}")
        bresp = int(self._sig("b_resp").value)
        # Consume the B beat on the next edge and drop valids.
        await RisingEdge(self.dut.clk)
        self._sig("aw_valid").value = 0
        self._sig("w_valid").value = 0
        if bresp != 0:
            raise AssertionError(f"AXI write @ {addr:#x}: bresp={bresp}")

    async def read(self, addr: int, timeout: int = 32) -> int:
        self._sig("ar_addr").value = addr
        self._sig("ar_valid").value = 1
        for _ in range(timeout):
            await RisingEdge(self.dut.clk)
            await ReadOnly()
            if int(self._sig("r_valid").value):
                break
        else:
            raise TimeoutError(f"AXI read r_valid timeout @ {addr:#x}")
        data = int(self._sig("r_data").value)
        rresp = int(self._sig("r_resp").value)
        await RisingEdge(self.dut.clk)
        self._sig("ar_valid").value = 0
        if rresp != 0:
            raise AssertionError(f"AXI read @ {addr:#x}: rresp={rresp}")
        return data
