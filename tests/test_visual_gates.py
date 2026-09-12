import pytest
import tempfile
from pathlib import Path
from dafg.visual import (
    PNGReader,
    PixelDiff,
    RegionAnalyzer,
    VisualGateConfig,
    VisualGateEngine,
    VisualAssertion,
)
from dafg.gates import GateLedger, GateEngine, Gate, GateResult


def create_test_png(filepath: Path, width: int, height: int, color: tuple[int, int, int] = (128, 128, 128), rgba: bool = False):
    """Create a minimal valid PNG file with a solid color."""
    import struct, zlib
    
    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack('>I', zlib.crc32(c) & 0xffffffff)
        return struct.pack('>I', len(data)) + c + crc
    
    color_type = 6 if rgba else 2
    
    # IHDR
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, color_type, 0, 0, 0)
    ihdr = chunk(b'IHDR', ihdr_data)
    
    # IDAT
    raw = b''
    for y in range(height):
        raw += b'\x00'  # No filter
        for x in range(width):
            if rgba:
                raw += bytes(color) + b'\xff'
            else:
                raw += bytes(color)
    compressed = zlib.compress(raw)
    idat = chunk(b'IDAT', compressed)
    
    # IEND
    iend = chunk(b'IEND', b'')
    
    filepath.write_bytes(b'\x89PNG\r\n\x1a\n' + ihdr + idat + iend)


def test_png_reader_valid_rgb(tmp_path):
    p = tmp_path / "test_rgb.png"
    create_test_png(p, 10, 10, (255, 0, 0))
    w, h, px = PNGReader.read(p)
    assert w == 10
    assert h == 10
    assert len(px) == 100
    assert px[0] == (255, 0, 0, 255)  # RGB is padded with 255 alpha


def test_png_reader_valid_rgba(tmp_path):
    p = tmp_path / "test_rgba.png"
    create_test_png(p, 5, 5, (0, 255, 0), rgba=True)
    w, h, px = PNGReader.read(p)
    assert w == 5
    assert h == 5
    assert len(px) == 25
    assert px[0] == (0, 255, 0, 255)


def test_png_reader_invalid(tmp_path):
    p = tmp_path / "test_invalid.txt"
    p.write_text("not a png")
    with pytest.raises(ValueError, match="Not a valid PNG file"):
        PNGReader.read(p)


def test_pixel_diff_identical():
    img = (2, 2, [(0,0,0,255)] * 4)
    res = PixelDiff.compare(img, img)
    assert res.passed is True
    assert res.diff_ratio == 0.0


def test_pixel_diff_different():
    img_a = (2, 2, [(0,0,0,255)] * 4)
    img_b = (2, 2, [(255,255,255,255)] * 4)
    res = PixelDiff.compare(img_a, img_b)
    assert res.passed is False
    assert res.diff_ratio == 1.0


def test_pixel_diff_size_mismatch():
    img_a = (2, 2, [(0,0,0,255)] * 4)
    img_b = (3, 3, [(0,0,0,255)] * 9)
    res = PixelDiff.compare(img_a, img_b)
    assert res.passed is False
    assert res.diff_ratio == 1.0


def test_region_analyzer_all_black():
    px = [(0,0,0,255)] * 4
    ratio = RegionAnalyzer.check_blackness(2, 2, px)
    assert ratio == 0.0


def test_region_analyzer_non_black():
    px = [(255,255,255,255)] * 4
    ratio = RegionAnalyzer.check_blackness(2, 2, px)
    assert ratio == 1.0


def test_visual_config_defaults():
    cfg = VisualGateConfig(reference_image="ref.png", capture_command="cmd", output_path="out.png")
    assert cfg.assertions == [VisualAssertion.PERCEPTUAL_DIFF]
    assert cfg.diff_threshold == 0.05
    assert cfg.blackness_threshold == 0.95
    assert cfg.retries == 2


def test_engine_missing_ref(tmp_path):
    cfg = VisualGateConfig(reference_image=str(tmp_path / "missing.png"), capture_command="true", output_path="out.png")
    vge = VisualGateEngine()
    res = vge.execute(cfg)
    assert res.passed is False
    assert "Reference image not found" in res.capture_error


def test_engine_execute_success(tmp_path):
    ref_path = tmp_path / "ref.png"
    out_path = tmp_path / "out.png"
    create_test_png(ref_path, 2, 2, (100, 100, 100))
    create_test_png(out_path, 2, 2, (100, 100, 100))
    
    # Capture command does nothing, relies on out_path already existing
    cfg = VisualGateConfig(
        reference_image=str(ref_path),
        capture_command="exit 0",
        output_path=str(out_path)
    )
    vge = VisualGateEngine()
    res = vge.execute(cfg)
    assert res.passed is True


def test_ledger_parse_visual_properties():
    md = """
- [ ] G1: Visual Gate
  CHECK: capture.sh
  VISUAL_REF: ref.png
  VISUAL_DIFF: 0.1
  VISUAL_RETRIES: 3
  VISUAL_ASSERTIONS: PERCEPTUAL_DIFF, REGION_BLACKNESS
  DETERMINISM: NO_ANIMATIONS=1
"""
    ledger = GateLedger.parse(md)
    gate = ledger.get_gate("G1")
    assert gate.visual_ref == "ref.png"
    assert gate.visual_diff == 0.1
    assert gate.visual_retries == 3
    assert gate.visual_assertions == "PERCEPTUAL_DIFF, REGION_BLACKNESS"
    assert gate.determinism == "NO_ANIMATIONS=1"
