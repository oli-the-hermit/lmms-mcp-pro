"""Add or remove one MCP server entry in a JSON config file, keeping everything else intact.

Used by install-windows.ps1 / uninstall-windows.ps1 for claude_desktop_config.json (Chat)
and ~/.claude.json (Code, user scope). Writes a timestamped backup before changing a file.

  python mcp_config.py set    <config.json> <name> <entry.json>
  python mcp_config.py remove <config.json> <name>
"""
import json
import shutil
import sys
import time
from pathlib import Path


def load(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8-sig").strip():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, data: dict) -> None:
    if path.exists():
        backup = path.with_name(path.name + time.strftime(".bak-%Y%m%d-%H%M%S"))
        shutil.copy2(path, backup)
        print(f"    backup: {backup}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[0] not in ("set", "remove"):
        print(__doc__)
        return 2
    cmd, path, name = argv[0], Path(argv[1]), argv[2]
    data = load(path)
    servers = data.setdefault("mcpServers", {})
    if cmd == "set":
        servers[name] = json.loads(Path(argv[3]).read_text(encoding="utf-8-sig"))
        save(path, data)
        print(f"    wrote '{name}' to {path}")
    elif name in servers:
        del servers[name]
        save(path, data)
        print(f"    removed '{name}' from {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
