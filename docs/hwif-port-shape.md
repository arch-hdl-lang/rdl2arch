# Design note: hwif port shape — struct vs. flat

**Status:** deferred. Current generator emits struct-typed hwif ports.
**Date logged:** 2026-04-17. Updated 2026-04-18 after ARCH v0.41.1
flipped packed-struct bit layout to SV convention (first-declared =
MSB), which removes the "convention-surprise" motivation for switching
but not the dual-backend test divergence.

## Current state

`rdl2arch` emits two packed struct ports on every generated regblock:

```
port hwif_in:  in  MyIpHwifIn;
port hwif_out: out MyIpHwifOut;
```

Each struct member is one field's worth of bits (`status_status_code: UInt<8>`,
`ctrl_enable: UInt<1>`, etc.). After `arch build`, the SV output is a packed
struct typedef in the package and two packed-struct ports on the module.

## The friction this causes

Test code can't be backend-agnostic. Driving a field from a test is different
on each of the two backends we run:

| Backend | How you reach `hwif_in.status_status_code` |
|---|---|
| cocotb + Verilator | `dut.hwif_in.value = packed_int`  (packed struct is surfaced as one integer — must bit-pack) |
| cocotb_shim + `arch_cocotb` pybind | `dut._model.hwif_in.status_status_code = 0x42` (pybind exposes struct members) — but `ArchSignal.value = int` fails because it `setattr(model, 'hwif_in', int)` onto a struct |

There's no single line of Python that reads or writes a field on both.

This same coupling also showed up as compiler bugs in arch-com's sim codegen
(struct-field width inference, struct-literal reset lowering, struct-typed
port init) — most of which we fixed, but the category would never have
existed without the struct port.

## Options considered

| | Change | Tradeoff |
|---|---|---|
| **A. Flat ports** | Emit each hwif field as an individual scalar port (`hwif_in_status_status_code`). Drop hwif struct types from the package. | Changes rdl2arch's public signature. Ergonomic — tests read/write signals directly by name; no packed-struct bit math; users wire individual signals into their SoC top anyway. Matches PeakRDL-regblock convention. Eliminates the struct-access backend asymmetry. |
| **B. Compat shim in tests** | Keep struct ports. Write a Python wrapper that normalizes field access across backends. | Adds test-side complexity forever. Tests still need to know packed-bit positions for the Verilator decode path. No generator change. |
| **C. arch_cocotb struct signals** | Teach arch-com's `ArchSignal` to handle struct-typed signals (get/set per-field). | Asymmetric — only fixes the arch-com side. Verilator side still sees packed integer, so tests still diverge. Doesn't solve the problem on its own. |

## Recommendation if revisited

**Option A.** It's the only one where the test body is literally identical on
both backends, and it removes the generator's dependence on arch-com's struct
handling in sim codegen. Cost is a one-time change to the generator's module
interface (visible to users but strictly more ergonomic).

Sketch of the change:

1. `emit_package.py` — drop `<Module>HwifIn` / `<Module>HwifOut` struct types.
2. `emit_regblock.py` — emit one `port hwif_<flat_field_name>: in/out UInt<W>`
   per hwif-exposed field; write/read them directly instead of via struct
   member access.
3. cocotb tests — switch from `dut.hwif_in.value` bit-packing to
   `dut.hwif_<flat_field_name>.value` per field. Same code on both backends.
4. Delete the sync `tests/sim/test_functional.py`; replace with a single
   cocotb test set driven by both the Verilator runner and an arch_sim runner.

## Why we held off

The struct-port shape currently works end-to-end on both backends with
separate test sets, all 35 tests green. Unifying the tests is a quality-of-life
improvement, not a correctness blocker. Logging the design decision so a
future pass can make the change deliberately rather than discovering the
divergence from scratch.
