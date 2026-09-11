"""Verification module for capturing and checking screenshots across all camera inspection angles."""

from pathlib import Path
import subprocess
import sys

def main():
    root = Path(__file__).resolve().parent.parent.parent
    screenshots_dir = root / "screenshots"
    if not screenshots_dir.exists():
        print("Error: screenshots directory was not created")
        sys.exit(1)

    required_angles = [
        "hero",
        "cockpit",
        "side",
        "top",
        "front",
        "gear",
        "engines",
        "winglet",
        "tail",
        "cinematic_runway",
    ]

    for angle in required_angles:
        img_path = screenshots_dir / f"{angle}.png"
        if not img_path.exists():
            print(f"Error: Missing screenshot for angle '{angle}'")
            sys.exit(1)
        size = img_path.stat().st_size
        if size < 20000:
            print(f"Error: Screenshot for '{angle}' is suspiciously small ({size} bytes)")
            sys.exit(1)

    print("ALL_ANGLES_CAPTURED_AND_VERIFIED")
    sys.exit(0)

if __name__ == "__main__":
    main()
