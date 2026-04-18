"""Minimal APB4 initiator driver for functional verification."""

from __future__ import annotations

from .axi4lite_driver import tick


class Apb4Driver:
    def __init__(self, dut, *, port: str = "s_apb"):
        self.dut = dut
        self.prefix = port
        self._set("psel", 0)
        self._set("penable", 0)
        self._set("pwrite", 0)
        self._set("pstrb", 0xF)
        self._set("pprot", 0)

    def _sig(self, name: str) -> str:
        return f"{self.prefix}_{name}"

    def _get(self, name: str) -> int:
        return getattr(self.dut, self._sig(name))

    def _set(self, name: str, value: int) -> None:
        setattr(self.dut, self._sig(name), value)

    def _xfer(self, addr: int, wdata: int | None, timeout: int) -> int:
        is_write = wdata is not None
        self._set("paddr", addr)
        self._set("pwrite", 1 if is_write else 0)
        if is_write:
            self._set("pwdata", wdata)
        # Setup phase: psel=1, penable=0
        self._set("psel", 1)
        self._set("penable", 0)
        tick(self.dut)
        # Access phase: penable=1; hold until pready==1
        self._set("penable", 1)
        result = 0
        for _ in range(timeout):
            self.dut.eval_comb()
            if self._get("pready"):
                if not is_write:
                    result = self._get("prdata")
                if self._get("pslverr"):
                    raise AssertionError(f"APB @ {addr:#x}: pslverr")
                tick(self.dut)
                break
            tick(self.dut)
        else:
            raise TimeoutError(f"APB pready timeout @ {addr:#x}")
        # Idle
        self._set("psel", 0)
        self._set("penable", 0)
        return result

    def write(self, addr: int, data: int, timeout: int = 32) -> None:
        self._xfer(addr, data, timeout)

    def read(self, addr: int, timeout: int = 32) -> int:
        return self._xfer(addr, None, timeout)
