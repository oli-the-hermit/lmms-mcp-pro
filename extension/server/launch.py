"""Launcher used by the LMMS MCP Pro desktop extension (.mcpb).

Claude starts this file with the Python of your LMMS MCP Pro install (the
"Python" setting of the extension, normally <repo>\\.venv\\Scripts\\python.exe).
The package is installed there in editable mode, so code changes in the repo
apply the next time Claude starts the server.
"""
import sys

try:
    from lmms_mcp.server import main
except ImportError as exc:  # wrong interpreter or package not installed
    sys.stderr.write(
        "LMMS MCP Pro: could not import 'lmms_mcp' with "
        f"{sys.executable}\n  {exc}\n"
        "Run scripts\\install-windows.ps1 in the repo, or point the extension's "
        "'Python' setting at <repo>\\.venv\\Scripts\\python.exe.\n"
    )
    sys.exit(1)

main()
