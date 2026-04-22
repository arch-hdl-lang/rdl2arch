# rdl2arch

Generate ARCH HDL register-block source from a SystemRDL 2.0 specification.

`rdl2arch` parses `.rdl` with the MIT-licensed `systemrdl-compiler` and emits
`.arch` source files. The `arch build` compiler handles the final SystemVerilog
emission, along with the correctness guarantees ARCH provides automatically
(single-driver, no-implicit-latch, width safety, CDC).

## Status

v0.1 — implements the Feature A v1 subset of
[`rdl-arch-integration-plan.md`](../rdl-arch-integration-plan.md):

Supported:
- `addrmap` top with flat `reg`s, nested `regfile` containers (flattened into
  the top module), and register arrays (`reg[N]`, unrolled).
- Fields with explicit bit positions and widths up to the bus data width.
- `sw = rw / r / w`, `hw = rw / r / w`.
- `onwrite = woclr / woset / wclr / wset / wot / wzc / wzs / wzt`.
- `onread = rclr / rset`.
- Explicit per-field `reset` values.
- CPU interfaces: AXI4-Lite and APB4 (subordinate), emitted as an ARCH `bus`.
- Read-back via an exhaustive `match` over decoded register addresses.

Not yet supported (rejected with an actionable error):
- RDL `mem` blocks.
- Counters, interrupt / sticky fields.
- AHB-Lite or other CPU interfaces.
- RISC-V CSR semantics — see the companion `rdl2arch-riscv` package.

## Install

```bash
pip install -e .
```

The `rdl2arch` command becomes available on `PATH`.

## Usage

```bash
rdl2arch my_ip.rdl -o out/                  # default: AXI4-Lite
rdl2arch my_ip.rdl -o out/ --cpuif apb4     # APB4 subordinate
```

Produces `out/MyIp.arch` + `out/MyIpPkg.arch`. Compile with the ARCH toolchain:

```bash
arch build out/MyIp.arch out/MyIpPkg.arch
```

### Configuration file

Generator knobs can be pinned in an `rdl2arch.toml` next to your RDL
(auto-discovered by walking up from CWD, same pattern as `pyproject.toml`).
CLI flags take precedence over the file, which takes precedence over the
library default — so the file sets project-wide defaults that individual
invocations can still override.

```toml
# rdl2arch.toml
[rdl2arch]
addr_width   = 16            # override auto-derivation from max register address
data_width   = 32            # bus data width
reset_style  = "async-low"   # "sync" (default) | "async-low" | "async-high"

[cpuif.axi4-lite]            # per-cpuif, keyed by the --cpuif CLI token
port_name              = "s_axi"
combinational_readback = false

[cpuif.apb4]
port_name              = "s_apb"
combinational_readback = true
```

Unknown keys / sections are rejected with an actionable error so typos
don't silently no-op. Pass `--config <path>` to load a specific file,
`--no-config` (or `RDL2ARCH_NO_CONFIG=1`) to skip auto-discovery.

Picking `reset_style = "async-low"` is the recommended setting for
RISC-V / Ibex / OpenTitan integrations where the core clock is gated
during reset — a sync-reset flop under a gated clock never sees the
posedge that would latch its reset value.

### Example outputs

See `tests/expected/` for checked-in samples — one directory per
`<fixture>-<cpuif>` pair, each containing the generated `*.arch` files for the
RDL inputs under `tests/rdl/`. Good for getting a feel for what the emitter
produces before running it on your own specs.

The golden diff test (`pytest tests/test_golden.py`) guards against unintended
emitter changes. To refresh after an intentional change:

```bash
UPDATE_GOLDEN=1 pytest tests/test_golden.py
```

### Library API

```python
from systemrdl import RDLCompiler
from rdl2arch import ArchExporter, ResetStyle

rdlc = RDLCompiler()
rdlc.compile_file("my_ip.rdl")
root = rdlc.elaborate()
ArchExporter().export(
    root.top, "out/",
    # All keyword args are optional; these mirror the TOML knobs:
    reset_style=ResetStyle.ASYNC_LOW,
    addr_width=16,
    port_name="s_axi_main",
    combinational_readback=False,
)
```

## Notes on mapping

- Generated subordinate port defaults to `s_axi` (AXI4-Lite) or `s_apb`
  (APB4); override via `[cpuif.<token>].port_name` in `rdl2arch.toml`
  or `--port-name` on the CLI. `bus` is a reserved ARCH keyword and
  cannot be used as a port name.
- One module per `addrmap`. Shared types (CSR enum, register structs, hwif
  structs) go in a `*Pkg.arch` package.
- RDL `regfile` containers do *not* map to ARCH `regfile` — RDL regfile is a
  heterogeneous container whereas ARCH `regfile` is a homogeneous multi-port
  array. Instead they are flattened into the top module; the path prefix is
  preserved in generated identifiers (`irq.status.pending` → `irq_status_r`).
- Register arrays (`reg[N]`) are unrolled at generation time, producing N
  address-decoded entries (`ch_0`, `ch_1`, …). ARCH's `generate_for` cannot
  contain `reg` declarations at present, so unrolling is the only option.

## License

Apache 2.0.
