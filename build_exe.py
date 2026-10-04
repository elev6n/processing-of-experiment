"""Build a standalone Windows x64 application with PyInstaller."""

from pathlib import Path
import ctypes
import os
import shutil
import struct
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
APP_NAME = "ExperimentProcessor"


def main() -> None:
    """Collect native dependencies and build dist/ExperimentProcessor.exe."""
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise SystemExit("Build with 64-bit Python on Windows (CI uses Python 3.11).")

    # Validate dependencies before removing any previous build.
    import PyInstaller  # noqa: F401
    from PySide6.QtCore import QLibraryInfo

    plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    if not (plugins / "platforms" / "qwindows.dll").is_file():
        raise SystemExit(f"Qt Windows platform plugin is missing: {plugins}")

    output_dirs = [ROOT / "build", ROOT / "dist"]
    # Refuse junctions/symlinks or paths that could escape the project.
    for directory in output_dirs:
        if directory.is_symlink() or directory.resolve() != directory:
            raise SystemExit(f"Refusing to clean redirected directory: {directory}")
    for directory in output_dirs:
        if directory.exists():
            shutil.rmtree(directory)

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--noconsole", "--noupx",
        "--name", APP_NAME,
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--paths", str(ROOT),
    ]
    for module in ("scipy.stats", "scipy.special", "sympy.parsing.sympy_parser"):
        command.extend(["--hidden-import", module])
    # Standard hooks collect .pyd extensions and adjacent numpy/scipy .libs DLLs.
    for package in ("numpy", "scipy"):
        command.extend(["--collect-binaries", package])
    for module in ("tkinter", "matplotlib", "IPython", "pytest", "PyQt5", "PyQt6", "PySide2"):
        command.extend(["--exclude-module", module])
    # Keep Qt's package-relative plugin layout for the PySide6 runtime hook.
    for group in ("platforms", "styles"):
        for library in sorted((plugins / group).glob("*.dll")):
            command.extend(["--add-binary", f"{library}:PySide6/plugins/{group}"])
    icon = ROOT / "assets" / "icon.ico"
    if icon.is_file():
        command.extend(["--icon", str(icon)])
    command.append(str(ROOT / "app.py"))
    # A developer's PATH can contain incompatible DLLs from unrelated tools
    # (e.g. Poppler's ICU). Resolve dependencies only from Python/Qt and Windows.
    environment = os.environ.copy()
    windows_buffer = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetWindowsDirectoryW(windows_buffer, len(windows_buffer)):
        raise SystemExit("Cannot locate the Windows directory.")
    windows = Path(windows_buffer.value)
    environment["SystemRoot"] = str(windows)
    environment["PATH"] = os.pathsep.join(
        str(path) for path in (Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows)
    )
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    executable = ROOT / "dist" / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise SystemExit(f"Build did not produce {executable}")
    print(f"Built {executable}")


if __name__ == "__main__":
    main()
