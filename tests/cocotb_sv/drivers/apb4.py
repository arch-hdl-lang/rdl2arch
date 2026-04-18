"""Async APB4 initiator driver for cocotb + Verilator."""

from __future__ import annotations

from cocotb.triggers import RisingEdge, ReadOnly


class Apb4Driver:
    def __init__(self, dut, *, port: str = "s_apb"):
        self.dut = dut
        self.prefix = port

    def _sig(self, name: str):
        return getattr(self.dut, f"{self.prefix}_{name}")

    async def init(self):
        self._sig("psel").value = 0
        self._sig("penable").value = 0
        self._sig("pwrite").value = 0
        self._sig("pstrb").value = 0xF
        self._sig("pprot").value = 0

    async def _xfer(self, addr: int, wdata: int | None, timeout: int) -> int:
        is_write = wdata is not None
        self._sig("paddr").value = addr
        self._sig("pwrite").value = 1 if is_write else 0
        if is_write:
            self._sig("pwdata").value = wdata
        # Setup phase: psel=1, penable=0
        self._sig("psel").value = 1
        self._sig("penable").value = 0
        await RisingEdge(self.dut.clk)
        # Access phase: penable=1, wait for pready
        self._sig("penable").value = 1
        result = 0
        for _ in range(timeout):
            await ReadOnly()
            if int(self._sig("pready").value):
                if not is_write:
                    result = int(self._sig("prdata").value)
                if int(self._sig("pslverr").value):
                    raise AssertionError(f"APB @ {addr:#x}: pslverr")
                break
            await RisingEdge(self.dut.clk)
        else:
            raise TimeoutError(f"APB pready timeout @ {addr:#x}")
        await RisingEdge(self.dut.clk)
        self._sig("psel").value = 0
        self._sig("penable").value = 0
        return result

    async def write(self, addr: int, data: int, timeout: int = 32) -> None:
        await self._xfer(addr, data, timeout)

    async def read(self, addr: int, timeout: int = 32) -> int:
        return await self._xfer(addr, None, timeout)
