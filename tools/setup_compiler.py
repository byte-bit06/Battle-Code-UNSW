"""Give unswbc a C++ compiler on machines without one (Windows without Visual Studio).

usage: python tools/setup_compiler.py

Installs Zig (which bundles clang) from PyPI into tools/.zig/ (git-ignored) and writes
tools/.zig/bin/zcxx.cmd. harness.py uses it automatically when no compiler is on PATH; by hand:
    set CXX=zcxx.cmd  and put tools\\.zig\\bin on PATH, then `unswbc run ...`.
"""
import pathlib
import subprocess
import sys
import venv

HERE = pathlib.Path(__file__).resolve().parent
ZIG = HERE / ".zig"


def main() -> None:
    py = ZIG / "Scripts" / "python.exe" if sys.platform == "win32" else ZIG / "bin" / "python"
    if not py.exists():
        venv.create(ZIG, with_pip=True)
    subprocess.check_call([str(py), "-m", "pip", "install", "-q", "ziglang"])
    bindir = ZIG / "bin"
    bindir.mkdir(exist_ok=True)
    if sys.platform == "win32":
        (bindir / "zcxx.cmd").write_text(f'@"{py}" -m ziglang c++ %*\r\n')
    else:
        sh = bindir / "zcxx"
        sh.write_text(f'#!/bin/sh\nexec "{py}" -m ziglang c++ "$@"\n')
        sh.chmod(0o755)
    print("compiler ready:", bindir)


if __name__ == "__main__":
    main()
