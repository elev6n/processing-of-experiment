"""Check the frozen Windows GUI executable and its standalone startup."""

from pathlib import Path
import os
import subprocess
import tempfile

import pefile
from PyInstaller.archive.readers import CArchiveReader


def main() -> None:
    """Verify native dependencies, GUI subsystem and startup from an empty folder."""
    executable = Path(__file__).resolve().parents[1] / "dist" / "ExperimentProcessor.exe"
    archive = CArchiveReader(str(executable))
    names = [name.replace("\\", "/") for name in archive.toc]
    for fragment in ("platforms/qwindows.dll", ".pyd", "numpy.libs/", "scipy.libs/"):
        if not any(fragment in name for name in names):
            raise RuntimeError(f"Required native dependency missing: {fragment}")
    modules = archive.open_embedded_archive("PYZ.pyz").toc
    for module in ("scipy.stats", "scipy.special", "sympy.parsing.sympy_parser"):
        if module not in modules:
            raise RuntimeError(f"Required module missing: {module}")
    image = pefile.PE(str(executable), fast_load=True)
    if image.OPTIONAL_HEADER.Subsystem != 2 or image.FILE_HEADER.Machine != 0x8664:
        raise RuntimeError("Expected a Windows GUI x64 executable")
    image.close()

    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    for key in ("PYTHONPATH", "PYTHONHOME"):
        environment.pop(key, None)
    with tempfile.TemporaryDirectory() as directory:
        process = subprocess.Popen(
            [str(executable)], cwd=directory, env=environment, creationflags=subprocess.CREATE_NO_WINDOW
        )
        try:
            try:
                code = process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                print("EXE dependencies and standalone startup: OK")
            else:
                raise RuntimeError(f"Application exited unexpectedly: {code}")
        finally:
            if process.poll() is None:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"], check=True, capture_output=True
                )
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
