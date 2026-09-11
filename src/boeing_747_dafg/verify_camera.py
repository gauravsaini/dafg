"""Verification module for Multi-Angle Camera Inspection System."""

from pathlib import Path
import sys

def main():
    root = Path(__file__).resolve().parent.parent.parent
    cam_file = root / "src" / "camera_system.js"

    if not cam_file.exists():
        print("Error: src/camera_system.js does not exist")
        sys.exit(1)

    code = cam_file.read_text()

    required_presets = [
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

    for p in required_presets:
        if f"{p}:" not in code:
            print(f"Error: Missing camera preset '{p}' in src/camera_system.js")
            sys.exit(1)

    required_features = [
        "class CameraSystem",
        "setAngle",
        "update",
        "setupKeyboard",
        "updateHUD",
        "captureScreenshot",
    ]

    for f in required_features:
        if f not in code:
            print(f"Error: Missing camera feature '{f}' in src/camera_system.js")
            sys.exit(1)

    print("CAMERA_SYSTEM_VERIFIED")
    sys.exit(0)

if __name__ == "__main__":
    main()
