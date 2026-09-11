"""Verification module for Boeing 747 3D geometry and components."""

from pathlib import Path
import sys

def main():
    root = Path(__file__).resolve().parent.parent.parent
    model_file = root / "src" / "boeing747.js"

    if not model_file.exists():
        print("Error: src/boeing747.js does not exist")
        sys.exit(1)

    code = model_file.read_text()

    checks = [
        ("FuselageGroup", "Fuselage group"),
        ("hump", "Iconic upper deck hump geometry"),
        ("Cockpit", "Cockpit structure"),
        ("APU", "APU exhaust nozzle"),
        ("WingsGroup", "Swept wings group"),
        ("37.5", "37.5 degree wing sweep"),
        ("Winglet", "Cantilevered winglets"),
        ("canoe", "Flap track fairings (canoes)"),
        ("EnginesGroup", "4 Turbofan engines"),
        ("bladeCount = 24", "24 Titanium turbine fan blades"),
        ("TailGroup", "Empennage tail group"),
        ("fin", "Vertical stabilizer"),
        ("Horizontal", "Horizontal stabilizers"),
        ("LandingGearGroup", "Landing gear system"),
        ("NoseGear", "2-Wheel nose gear"),
    ]

    for token, desc in checks:
        if token not in code:
            print(f"Error: Missing {desc} ('{token}') in src/boeing747.js")
            sys.exit(1)

    print("MODEL_GEOMETRY_VERIFIED")
    sys.exit(0)

if __name__ == "__main__":
    main()
