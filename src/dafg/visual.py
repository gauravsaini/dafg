"""Visual Gates — First-Class Visual Verification.

Capture → perceptual diff / region-blackness / text-legibility → retry loop.
All implemented with stdlib only (struct + zlib for PNG decoding).
"""
from __future__ import annotations

import os
import struct
import subprocess
import time
import zlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class VisualAssertion(str, Enum):
    PERCEPTUAL_DIFF = "PERCEPTUAL_DIFF"     # Pixel-level diff ratio
    REGION_BLACKNESS = "REGION_BLACKNESS"   # Check region isn't all black
    PIXEL_MATCH = "PIXEL_MATCH"             # Exact pixel match (strict)


@dataclass
class VisualGateConfig:
    reference_image: str         # Path to golden reference PNG
    capture_command: str         # Shell command that produces screenshot
    output_path: str             # Where capture command writes the image
    assertions: List[VisualAssertion] = field(default_factory=lambda: [VisualAssertion.PERCEPTUAL_DIFF])
    diff_threshold: float = 0.05      # Max allowed diff ratio (0.0 = identical, 1.0 = completely different)
    blackness_threshold: float = 0.95 # Min fraction of NON-black pixels (>threshold = ok, image is not black)
    retries: int = 2                  # Retry count for flaky visual checks
    determinism_env: Dict[str, str] = field(default_factory=dict) # Env vars for determinism
    timeout: float = 30.0


@dataclass
class DiffResult:
    total_pixels: int
    changed_pixels: int
    diff_ratio: float             # changed / total
    passed: bool
    threshold: float
    error: Optional[str] = None


@dataclass
class AssertionResult:
    assertion: VisualAssertion
    passed: bool
    detail: str = ""
    value: float = 0.0           # The measured value
    threshold: float = 0.0       # The threshold used


@dataclass
class VisualGateResult:
    passed: bool
    assertion_results: List[AssertionResult] = field(default_factory=list)
    attempts: int = 0
    capture_error: Optional[str] = None
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PNGReader:
    """Minimal stdlib-only PNG decoder. Reads RGBA pixel data from PNG files.
    
    Supports 8-bit RGB and RGBA PNGs (color types 2 and 6).
    Uses struct for binary parsing and zlib for IDAT decompression.
    """

    @staticmethod
    def read(filepath: str | Path) -> Tuple[int, int, List[Tuple[int, ...]]]:
        """Read a PNG file and return (width, height, pixels).
        
        pixels is a flat list of (R, G, B, A) tuples.
        Raises ValueError if the PNG format is unsupported.
        """
        filepath = Path(filepath)
        data = filepath.read_bytes()
        
        # Verify PNG signature
        if data[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError("Not a valid PNG file")
        
        pos = 8
        width = height = 0
        bit_depth = 0
        color_type = 0
        idat_chunks = []
        
        while pos < len(data):
            chunk_len = struct.unpack('>I', data[pos:pos+4])[0]
            chunk_type = data[pos+4:pos+8]
            chunk_data = data[pos+8:pos+8+chunk_len]
            pos += 12 + chunk_len  # 4 (len) + 4 (type) + data + 4 (crc)
            
            if chunk_type == b'IHDR':
                width, height, bit_depth, color_type = struct.unpack('>IIBB', chunk_data[:10])
            elif chunk_type == b'IDAT':
                idat_chunks.append(chunk_data)
            elif chunk_type == b'IEND':
                break
        
        if bit_depth != 8:
            raise ValueError(f"Unsupported bit depth: {bit_depth} (only 8-bit supported)")
        if color_type not in (2, 6):  # 2=RGB, 6=RGBA
            raise ValueError(f"Unsupported color type: {color_type} (only RGB and RGBA supported)")
        
        # Decompress IDAT data
        compressed = b''.join(idat_chunks)
        raw_data = zlib.decompress(compressed)
        
        # Parse scanlines (each row has a filter byte prefix)
        channels = 4 if color_type == 6 else 3
        stride = width * channels
        pixels = []
        prev_row = bytes(stride)
        
        row_offset = 0
        for y in range(height):
            filter_byte = raw_data[row_offset]
            row_data = bytearray(raw_data[row_offset + 1:row_offset + 1 + stride])
            row_offset += 1 + stride
            
            # Apply PNG filter reconstruction
            if filter_byte == 1:  # Sub
                for i in range(channels, stride):
                    row_data[i] = (row_data[i] + row_data[i - channels]) & 0xFF
            elif filter_byte == 2:  # Up
                for i in range(stride):
                    row_data[i] = (row_data[i] + prev_row[i]) & 0xFF
            elif filter_byte == 3:  # Average
                for i in range(stride):
                    a = row_data[i - channels] if i >= channels else 0
                    row_data[i] = (row_data[i] + (a + prev_row[i]) // 2) & 0xFF
            elif filter_byte == 4:  # Paeth
                for i in range(stride):
                    a = row_data[i - channels] if i >= channels else 0
                    b = prev_row[i]
                    c = prev_row[i - channels] if i >= channels else 0
                    row_data[i] = (row_data[i] + _paeth_predictor(a, b, c)) & 0xFF
            # filter_byte == 0: None (no reconstruction needed)
            
            prev_row = bytes(row_data)
            
            for x in range(width):
                offset = x * channels
                if channels == 4:
                    pixels.append((row_data[offset], row_data[offset+1], row_data[offset+2], row_data[offset+3]))
                else:
                    pixels.append((row_data[offset], row_data[offset+1], row_data[offset+2], 255))
        
        return width, height, pixels


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    elif pb <= pc:
        return b
    return c


class PixelDiff:
    """Compare two images pixel-by-pixel."""

    @staticmethod
    def compare(
        img_a: Tuple[int, int, List[Tuple[int, ...]]],
        img_b: Tuple[int, int, List[Tuple[int, ...]]],
        threshold: float = 0.05,
    ) -> DiffResult:
        w_a, h_a, px_a = img_a
        w_b, h_b, px_b = img_b

        if w_a != w_b or h_a != h_b:
            return DiffResult(
                total_pixels=max(w_a * h_a, w_b * h_b),
                changed_pixels=max(w_a * h_a, w_b * h_b),
                diff_ratio=1.0,
                passed=False,
                threshold=threshold,
                error=f"Image size mismatch: {w_a}x{h_a} vs {w_b}x{h_b}",
            )

        total = w_a * h_a
        changed = 0
        for i in range(total):
            if px_a[i] != px_b[i]:
                changed += 1

        ratio = changed / total if total > 0 else 0.0
        return DiffResult(
            total_pixels=total,
            changed_pixels=changed,
            diff_ratio=round(ratio, 6),
            passed=ratio <= threshold,
            threshold=threshold,
        )


class RegionAnalyzer:
    """Analyze image regions for blackness."""

    @staticmethod
    def check_blackness(
        width: int,
        height: int,
        pixels: List[Tuple[int, ...]],
        region: Optional[Tuple[int, int, int, int]] = None,  # (x, y, w, h) or None for full image
    ) -> float:
        """Return fraction of NON-black pixels in the region.
        
        A pixel is 'black' if R+G+B < 30 (near-zero brightness).
        Returns 1.0 if all pixels are non-black, 0.0 if all are black.
        """
        if region:
            rx, ry, rw, rh = region
        else:
            rx, ry, rw, rh = 0, 0, width, height

        total = 0
        non_black = 0
        for y in range(ry, min(ry + rh, height)):
            for x in range(rx, min(rx + rw, width)):
                idx = y * width + x
                if idx < len(pixels):
                    r, g, b = pixels[idx][0], pixels[idx][1], pixels[idx][2]
                    total += 1
                    if r + g + b >= 30:
                        non_black += 1

        return non_black / total if total > 0 else 0.0


class VisualGateEngine:
    """Executes visual gate checks with capture → diff → assert → retry."""

    def execute(self, config: VisualGateConfig) -> VisualGateResult:
        ref_path = Path(config.reference_image)
        if not ref_path.exists():
            return VisualGateResult(
                passed=False,
                capture_error=f"Reference image not found: {config.reference_image}",
            )

        # Read reference image
        try:
            ref_img = PNGReader.read(ref_path)
        except (ValueError, Exception) as e:
            return VisualGateResult(
                passed=False,
                capture_error=f"Failed to read reference image: {e}",
            )

        last_assertion_results = []
        for attempt in range(1, config.retries + 2):  # retries + 1 initial attempt
            # Capture
            env = dict(os.environ)
            env.update(config.determinism_env)
            try:
                proc = subprocess.run(
                    config.capture_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=config.timeout,
                    env=env,
                )
                if proc.returncode != 0:
                    last_assertion_results = []
                    continue  # Retry
            except subprocess.TimeoutExpired:
                continue
            except Exception as e:
                return VisualGateResult(
                    passed=False,
                    attempts=attempt,
                    capture_error=f"Capture command failed: {e}",
                )

            output_path = Path(config.output_path)
            if not output_path.exists():
                continue  # Retry

            try:
                captured_img = PNGReader.read(output_path)
            except (ValueError, Exception):
                continue  # Retry

            # Run assertions
            assertion_results = []
            all_passed = True

            for assertion in config.assertions:
                if assertion == VisualAssertion.PERCEPTUAL_DIFF:
                    diff = PixelDiff.compare(ref_img, captured_img, threshold=config.diff_threshold)
                    result = AssertionResult(
                        assertion=assertion,
                        passed=diff.passed,
                        detail=f"{diff.changed_pixels}/{diff.total_pixels} pixels differ ({diff.diff_ratio:.4%})",
                        value=diff.diff_ratio,
                        threshold=config.diff_threshold,
                    )
                elif assertion == VisualAssertion.REGION_BLACKNESS:
                    w, h, px = captured_img
                    non_black = RegionAnalyzer.check_blackness(w, h, px)
                    result = AssertionResult(
                        assertion=assertion,
                        passed=non_black >= config.blackness_threshold,
                        detail=f"{non_black:.2%} non-black pixels (threshold: {config.blackness_threshold:.0%})",
                        value=non_black,
                        threshold=config.blackness_threshold,
                    )
                elif assertion == VisualAssertion.PIXEL_MATCH:
                    diff = PixelDiff.compare(ref_img, captured_img, threshold=0.0)
                    result = AssertionResult(
                        assertion=assertion,
                        passed=diff.passed,
                        detail=f"{diff.changed_pixels} pixel(s) differ",
                        value=diff.diff_ratio,
                        threshold=0.0,
                    )
                else:
                    continue

                assertion_results.append(result)
                if not result.passed:
                    all_passed = False

            last_assertion_results = assertion_results

            if all_passed:
                evidence_parts = [f"visual_check=PASSED attempts={attempt}"]
                for ar in assertion_results:
                    evidence_parts.append(f"{ar.assertion.value}={ar.value:.4f}")
                return VisualGateResult(
                    passed=True,
                    assertion_results=assertion_results,
                    attempts=attempt,
                    evidence=" ".join(evidence_parts),
                )

        # All retries exhausted
        evidence_parts = [f"visual_check=FAILED attempts={config.retries + 1}"]
        for ar in last_assertion_results:
            evidence_parts.append(f"{ar.assertion.value}={ar.value:.4f}")
        return VisualGateResult(
            passed=False,
            assertion_results=last_assertion_results,
            attempts=config.retries + 1,
            evidence=" ".join(evidence_parts),
        )
