"""Verification module for PBR materials, textures, and environmental lighting."""

from pathlib import Path
import sys

def main():
    root = Path(__file__).resolve().parent.parent.parent
    mat_file = root / "src" / "materials.js"
    scene_file = root / "src" / "scene_setup.js"

    if not mat_file.exists() or not scene_file.exists():
        print("Error: Missing materials.js or scene_setup.js")
        sys.exit(1)

    mat_code = mat_file.read_text()
    scene_code = scene_file.read_text()

    mat_checks = [
        "createFuselageTexture",
        "createWingTexture",
        "createSpinnerTexture",
        "createRunwayTexture",
        "createTireTexture",
        "fuselage:",
        "wings:",
        "polishedAluminum:",
        "exhaustTitanium:",
        "cockpitGlass:",
        "tireRubber:",
        "navLightRed:",
        "navLightGreen:",
        "strobeWhite:",
        "runway:",
    ]

    for mc in mat_checks:
        if mc not in mat_code:
            print(f"Error: Missing material component '{mc}' in src/materials.js")
            sys.exit(1)

    scene_checks = [
        "PCFShadowMap",
        "ACESFilmicToneMapping",
        "runwayMesh",
        "sunLight",
        "hemiLight",
        "day:",
        "sunset:",
        "night:",
    ]

    for sc in scene_checks:
        if sc not in scene_code:
            print(f"Error: Missing scene component '{sc}' in src/scene_setup.js")
            sys.exit(1)

    print("MATERIALS_LIGHTING_VERIFIED")
    sys.exit(0)

if __name__ == "__main__":
    main()
