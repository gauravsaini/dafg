"""Automated test suite for Boeing 747 Three.js simulation and DAFG gates."""

import json
from pathlib import Path
import pytest
from dafg import GateLedger, ApprovalStore, GateEngine
from dafg.hook import CompletionGuard

ROOT = Path(__file__).resolve().parent.parent

def test_file_structure():
    """Verify all core source and asset files exist."""
    assert (ROOT / "index.html").exists()
    assert (ROOT / "src" / "main.js").exists()
    assert (ROOT / "src" / "boeing747.js").exists()
    assert (ROOT / "src" / "materials.js").exists()
    assert (ROOT / "src" / "camera_system.js").exists()
    assert (ROOT / "src" / "scene_setup.js").exists()
    assert (ROOT / "GATES.md").exists()
    assert (ROOT / "GOAL.md").exists()

def test_geometry_components():
    """Verify structural 747 components are modeled in boeing747.js."""
    code = (ROOT / "src" / "boeing747.js").read_text()
    assert "FuselageGroup" in code
    assert "WingsGroup" in code
    assert "EnginesGroup" in code
    assert "TailGroup" in code
    assert "LandingGearGroup" in code
    assert "NoseGear" in code
    assert "PortWingGear" in code
    assert "StbdWingGear" in code
    assert "PortBodyGear" in code
    assert "StbdBodyGear" in code
    assert "37.5" in code
    assert "bladeCount = 24" in code

def test_camera_presets():
    """Verify all 10 inspection angles are configured."""
    code = (ROOT / "src" / "camera_system.js").read_text()
    required = [
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
    for angle in required:
        assert f"{angle}:" in code

def test_materials_and_textures():
    """Verify PBR materials and procedural canvas textures."""
    code = (ROOT / "src" / "materials.js").read_text()
    assert "createFuselageTexture" in code
    assert "createEngineTexture" in code
    assert "createWingTexture" in code
    assert "createTailTexture" in code
    assert "createSpinnerTexture" in code
    assert "createRunwayTexture" in code
    assert "createTireTexture" in code
    assert "fuselage:" in code
    assert "wings:" in code
    assert "tailLivery:" in code
    assert "engineCowling:" in code
    assert "polishedAluminum:" in code
    assert "cockpitGlass:" in code

def test_screenshots_generated():
    """Verify high-res screenshots exist for all angles."""
    screenshots_dir = ROOT / "screenshots"
    assert screenshots_dir.exists()
    required_shots = [
        "hero.png",
        "cockpit.png",
        "side.png",
        "top.png",
        "front.png",
        "gear.png",
        "engines.png",
        "winglet.png",
        "tail.png",
        "cinematic_runway.png",
        "hero_sunset.png",
        "hero_night.png",
    ]
    for shot in required_shots:
        file = screenshots_dir / shot
        assert file.exists()
        assert file.stat().st_size > 20000

def test_stop_hook_allows_completion():
    """Verify stop hook allows completion with evidence recorded."""
    guard = CompletionGuard(ledger_path=ROOT / "GATES.md")
    decision = guard.evaluate()
    assert decision.allowed is True
    assert decision.decision == "allow"
