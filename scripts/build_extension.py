"""Build the LMMS MCP Pro desktop extension (dist/lmms-mcp-pro.mcpb).

The extension does not bundle Python: it runs the server from this repo's
virtual environment (editable install), so you keep developing in the repo and
Claude always runs your latest code. Defaults for its settings are taken from
this machine; they can be changed later in Claude > Settings > Extensions.

  .venv\\Scripts\\python scripts\\build_extension.py      (Windows)
  .venv/bin/python scripts/build_extension.py          (Linux/macOS)

Then double-click dist\\lmms-mcp-pro.mcpb (or drag it into Settings > Extensions).
"""
import json
import os
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def default_python() -> str:
    win = REPO / ".venv" / "Scripts" / "python.exe"
    nix = REPO / ".venv" / "bin" / "python"
    return str(win if os.name == "nt" or win.exists() else nix)


def default_lmms() -> str:
    try:
        from lmms_mcp.lmms_app import find_lmms_exe
        exe = find_lmms_exe()
        if exe:
            return str(exe)
    except Exception:  # noqa: BLE001 - detection is best effort
        pass
    return r"C:\Program Files\LMMS\lmms.exe" if os.name == "nt" else "/usr/bin/lmms"


def default_projects() -> str:
    return os.environ.get("LMMS_PROJECTS_DIR") or str(
        Path.home() / "Documents" / "lmms" / "projects" / "Claude")


def version() -> str:
    for line in (REPO / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    return "0.0.0"


def manifest(python: str, projects: str, lmms: str) -> dict:
    return {
        "manifest_version": "0.2",
        "name": "lmms-mcp-pro",
        "display_name": "LMMS MCP Pro",
        "version": version(),
        "description": "Compose, mix and render LMMS projects with Claude.",
        "long_description": (
            "Extended fork of LMMS MCP: extra tools, fixes and workflow tweaks for "
            "composing, mixing and rendering LMMS projects with Claude. Runs from your "
            "local LMMS MCP Pro checkout (editable install)."
        ),
        "author": {"name": "San Milano",
                   "url": "https://github.com/oli-the-hermit/lmms-mcp-pro"},
        "homepage": "https://github.com/oli-the-hermit/lmms-mcp-pro",
        "repository": {"type": "git",
                       "url": "https://github.com/oli-the-hermit/lmms-mcp-pro.git"},
        "license": "MIT",
        "keywords": ["lmms", "music", "daw", "audio", "composition"],
        "server": {
            "type": "python",
            "entry_point": "server/launch.py",
            "mcp_config": {
                "command": "${user_config.python}",
                "args": ["${__dirname}/server/launch.py"],
                "env": {
                    "LMMS_PROJECTS_DIR": "${user_config.projects_dir}",
                    "LMMS_EXECUTABLE": "${user_config.lmms_executable}",
                    "PYTHONUNBUFFERED": "1",
                },
            },
        },
        "user_config": {
            "python": {
                "type": "file",
                "title": "Python of your LMMS MCP Pro install",
                "description": "Usually <repo>\\.venv\\Scripts\\python.exe "
                               "(created by scripts\\install-windows.ps1).",
                "default": python,
            },
            "projects_dir": {
                "type": "directory",
                "title": "Projects folder",
                "description": "Where Claude saves the LMMS projects it creates.",
                "default": projects,
            },
            "lmms_executable": {
                "type": "file",
                "title": "LMMS program (lmms.exe)",
                "description": "Used to check plugins and to render audio. "
                               "Projects can still be made without it.",
                "default": lmms,
            },
        },
        "compatibility": {"platforms": ["win32", "darwin", "linux"]},
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Build dist/lmms-mcp-pro.mcpb")
    ap.add_argument("--python", help="Python that runs the server (default: this repo's .venv)")
    ap.add_argument("--projects", help="Default projects folder")
    ap.add_argument("--lmms", help="Path to lmms.exe")
    ap.add_argument("--out", help="Output .mcpb path (default: dist/lmms-mcp-pro.mcpb)")
    a = ap.parse_args()
    python = a.python or default_python()
    projects = a.projects or default_projects()
    lmms = a.lmms or default_lmms()
    out_dir = REPO / "dist"
    out_dir.mkdir(exist_ok=True)
    out = Path(a.out) if a.out else out_dir / "lmms-mcp-pro.mcpb"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest(python, projects, lmms), indent=2))
        z.write(REPO / "extension" / "server" / "launch.py", "server/launch.py")
        icon = REPO / "extension" / "icon.png"
        if icon.exists():
            z.write(icon, "icon.png")
    print(f"built {out}")
    print(f"  python:   {python}{'' if Path(python).exists() else '   (NOT FOUND - run install-windows.ps1)'}")
    print(f"  projects: {projects}")
    print(f"  lmms:     {lmms}{'' if Path(lmms).exists() else '   (not found - rendering disabled)'}")
    print("Install: double-click the .mcpb file, or Claude > Settings > Extensions > drag it in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
