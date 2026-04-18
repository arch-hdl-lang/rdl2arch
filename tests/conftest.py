"""Shared pytest fixtures."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).parent
RDL_DIR = TESTS_DIR / "rdl"
EXPECTED_DIR = TESTS_DIR / "expected"


def find_arch_binary() -> str | None:
    """Locate the `arch` compiler. Prefer ARCH_BIN env var, then the release
    build in the sibling arch-com repo, then PATH."""
    env = os.environ.get("ARCH_BIN")
    if env and Path(env).is_file():
        return env

    # Sibling repo convention used during development.
    sibling = Path.home() / "github" / "arch-com" / "target" / "release" / "arch"
    if sibling.is_file():
        return str(sibling)

    which = shutil.which("arch")
    # The macOS /usr/bin/arch is NOT our compiler; reject it.
    if which and "arch-com" not in which and which != "/usr/bin/arch":
        return which
    return None


@pytest.fixture(scope="session")
def arch_bin() -> str:
    path = find_arch_binary()
    if path is None:
        pytest.skip("ARCH compiler not found (set ARCH_BIN=/path/to/arch)")
    return path


def rdl_fixtures() -> list[Path]:
    return sorted(RDL_DIR.glob("*.rdl"))


def run_arch(arch_bin: str, cmd: str, files: list[Path], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [arch_bin, cmd, *[str(f) for f in files]],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
