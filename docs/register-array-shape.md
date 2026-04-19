# Design note: register arrays — unroll-to-scalars vs. Vec-typed reg

**Status:** ✅ Done. Generator emits the Vec-at-module-scope pattern.
**Date logged:** 2026-04-18. Compiler unblocked via arch-com #11 / #13 /
#14 / #15 / #16. Generator-side refactor landed in this commit.

## Current state

When RDL declares a register array (`reg {...} ch[4] @ 0x00 += 0x4;`),
`rdl2arch` unrolls it at generation time into four scalar regs: `ch_0_r`,
`ch_1_r`, `ch_2_r`, `ch_3_r`. The generated ARCH — and the resulting SV — has
four independent `reg` declarations and four match-arm readback entries, one
per element.

This works, and it was the only option available: ARCH's `generate_for` only
accepts `port`, `inst`, `thread`, `assert`, `cover` in its body — not `reg` or
`let`. So Python-level unrolling was the path of least resistance.

## Why it's not great

For small `N` it's readable. For `N = 32` (common in RISC-V-style files) it
produces 32 separately-declared registers in both ARCH and SV. Readers see 32
lines of noise instead of the natural `logic [7:0] r [32];`.

## Attempts and why they didn't land

### Attempt 1 (withdrawn): extend `generate_for` to allow `reg` / `let`

[arch-com#9](https://github.com/arch-hdl-lang/arch-com/pull/9), now closed.
Extended `generate_for` to accept `reg` and `let` decls and unrolled them via
name-suffix substitution (same mechanism as ports). Two problems:

1. **Still ugly.** Produces `r_0`, `r_1`, ..., `r_31` in the SV. Moves the
   unrolling from Python to Rust but the output is the same shape.
2. **Correctness risk in the suffix rewrite.** To make expressions like
   `let lout_i = r_i` work, I had `subst_expr` rewrite any identifier ending
   in `_i`. That silently rewrites peer names defined outside the loop that
   happen to share the suffix — a subtle latent bug. Fixing it properly
   (scope-aware substitution) is more work than the feature is worth given
   point 1.

## The better direction (when we revisit)

**Vec-typed registers.** ARCH already has `Vec<T, N>` for vector signals. Make
reg declarations accept `Vec`:

```
reg ch_r: Vec<ChReg, 4> reset rst => Vec::splat(ChReg { enable: 0, threshold: 0 });
```

Emitted SV:

```
ChReg ch_r [4];
```

Downstream code indexes `ch_r[i]` at runtime where `i` is a signal. No
generate_for, no name mangling, no loop-variable substitution rules.
rdl2arch would emit one `reg` for a register array, one match-arm entry
per element (match on the upper address bits and then dereference via
`ch_r[lower_bits]`).

### What the compiler needs

- `reg name: Vec<T, N> reset ... => expr;` — I think Vec-typed regs may work
  already? Worth spot-checking before assuming it's a compiler change.
- A clean way to spread a struct reset value across all Vec elements
  (`Vec::splat` or equivalent).
- Sim codegen support for Vec<StructType, N> regs (currently sim codegen
  handles Vec<UInt/Bool, N> but struct elements may hit the fallbacks).

### What rdl2arch would change

- `emit_regblock.py` — emit one Vec-typed reg per RDL register array instead of
  N scalars. Address decode becomes a 2-level `match` (upper bits select the
  array, lower bits index into `ch_r`).
- `emit_package.py` — struct is shared across all elements (no longer
  `Ch0Reg` / `Ch1Reg` / ...).
- `scan_design.py` — keep track of register arrays as a group, not N
  independent regs.

## Why we held off now

The current unroll-to-scalars approach works, all tests pass, and this is a
quality-of-life improvement rather than a correctness gap. Generator-side
refactoring is best done deliberately, not under the "one more thing"
momentum of a larger PR.

## Status of the compiler-side pieces

- ✅ `generate_for` body now accepts `seq` / `comb` blocks with a
  write-target rule that forbids scalar LHS from inside the loop
  ([arch-com#11](https://github.com/arch-hdl-lang/arch-com/pull/11)).
- ⏳ Vec<StructType, N> reg end-to-end through `arch sim` / pybind — not yet
  verified. Worth spot-checking before committing rdl2arch to the pattern.
