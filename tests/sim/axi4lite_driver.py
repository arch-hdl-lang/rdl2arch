"""Minimal AXI4-Lite initiator driver for functional verification of rdl2arch output.

Drives the pybind11-generated sim model directly (no asyncio / cocotb). Each
`tick()` raises the clock, calls `eval()`, lowers the clock, calls `eval()` —
matching a two-phase Verilator cycle.

Single-outstanding transactions only; enough to exercise register behavior.
"""

from __future__ import annotations


def tick(dut) -> None:
    dut.clk = 0
    dut.eval()
    dut.clk = 1
    dut.eval()


def reset(dut, cycles: int = 3) -> None:
    dut.rst = 1
    for _ in range(cycles):
        tick(dut)
    dut.rst = 0
    tick(dut)


class Axi4LiteDriver:
    def __init__(self, dut, *, port: str = "s_axi"):
        self.dut = dut
        self.prefix = port
        self._set("aw_valid", 0)
        self._set("w_valid", 0)
        self._set("ar_valid", 0)
        self._set("b_ready", 1)
        self._set("r_ready", 1)
        self._set("w_strb", 0xF)
        self._set("aw_prot", 0)
        self._set("ar_prot", 0)

    def _sig(self, name: str) -> str:
        return f"{self.prefix}_{name}"

    def _get(self, name: str) -> int:
        return getattr(self.dut, self._sig(name))

    def _set(self, name: str, value: int) -> None:
        setattr(self.dut, self._sig(name), value)

    def write(self, addr: int, data: int, strb: int = 0xF, timeout: int = 32) -> None:
        self._set("aw_addr", addr)
        self._set("w_data", data)
        self._set("w_strb", strb)
        self._set("aw_valid", 1)
        self._set("w_valid", 1)
        # Settle comb, then check the *pre-tick* ready state.
        for _ in range(timeout):
            self.dut.eval_comb()
            if self._get("aw_ready") and self._get("w_ready"):
                tick(self.dut)
                break
            tick(self.dut)
        else:
            raise TimeoutError(f"AXI write AW/W handshake timeout @ {addr:#x}")
        self._set("aw_valid", 0)
        self._set("w_valid", 0)
        for _ in range(timeout):
            self.dut.eval_comb()
            if self._get("b_valid"):
                break
            tick(self.dut)
        else:
            raise TimeoutError(f"AXI write B handshake timeout @ {addr:#x}")
        bresp = self._get("b_resp")
        if bresp != 0:
            raise AssertionError(f"AXI write @ {addr:#x}: bresp={bresp}")
        # Consume the B handshake.
        tick(self.dut)

    def read(self, addr: int, timeout: int = 32) -> int:
        self._set("ar_addr", addr)
        self._set("ar_valid", 1)
        for _ in range(timeout):
            self.dut.eval_comb()
            if self._get("ar_ready"):
                tick(self.dut)
                break
            tick(self.dut)
        else:
            raise TimeoutError(f"AXI read AR handshake timeout @ {addr:#x}")
        self._set("ar_valid", 0)
        for _ in range(timeout):
            self.dut.eval_comb()
            if self._get("r_valid"):
                break
            tick(self.dut)
        else:
            raise TimeoutError(f"AXI read R handshake timeout @ {addr:#x}")
        data = self._get("r_data")
        rresp = self._get("r_resp")
        if rresp != 0:
            raise AssertionError(f"AXI read @ {addr:#x}: rresp={rresp}")
        tick(self.dut)
        return data
