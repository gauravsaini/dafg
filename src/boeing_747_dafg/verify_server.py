"""Verification module for server and static asset readiness."""

from pathlib import Path
import sys

def main():
    root = Path(__file__).resolve().parent.parent.parent
    required_files = [
        root / "index.html",
        root / "src" / "main.js",
        root / "src" / "boeing747.js",
        root / "src" / "materials.js",
        root / "src" / "camera_system.js",
        root / "src" / "scene_setup.js",
        root / "node_modules" / "three" / "build" / "three.module.js",
    ]

    for f in required_files:
        if not f.exists():
            print(f"Error: Missing required asset {f}")
            sys.exit(1)

    # Verify HTML contains importmap and canvas container
    html_content = (root / "index.html").read_text()
    if 'id="canvas-container"' not in html_content:
        print("Error: Missing canvas-container in index.html")
        sys.exit(1)
    if '<script type="importmap">' not in html_content:
        print("Error: Missing importmap in index.html")
        sys.exit(1)

    print("SERVER_VALIDATION_PASSED")
    sys.exit(0)

if __name__ == "__main__":
    main()
