"""PyInstaller entry point (keeps package-relative imports working)."""

from snapanswer.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
