#!/usr/bin/env python3
"""
vivophoto_to_iphone: Convert Vivo Motion Photos to Apple Live Photos

Usage:
    python3 convert.py <input_directory>

Dependencies (one-time setup):
    brew install ffmpeg exiftool
    pip install makelive

What this does:
    For each JPG+MP4 pair with the same filename:
    1. Copies the JPG (preserving all original EXIF metadata)
    2. Transcodes MP4 → H.264 MOV (required codec for Live Photo pairing)
    3. Uses macOS CoreGraphics + AVFoundation (via makelive) to write
       ContentIdentifier into Apple MakerNote (JPEG) and QuickTime Keys (MOV)
    4. Aligns the MOV creation timestamp with the JPG's EXIF capture time
    5. Outputs: LivePhoto_Export/Live_<name>.jpg + Live_<name>.mov

Import to Mac Photos:
    Open Photos → File → Import → select LivePhoto_Export folder
    Select ALL files at once before clicking Import.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


# ─────────────────────────────── Dependency check ────────────────────────────

def check_dependencies():
    missing_brew = []
    for tool in ("ffmpeg", "exiftool"):
        r = subprocess.run(["which", tool], capture_output=True)
        if r.returncode != 0:
            missing_brew.append(tool)
    if missing_brew:
        print("Missing dependencies. Run:")
        print(f"  brew install {' '.join(missing_brew)}")
        sys.exit(1)

    try:
        import makelive  # noqa: F401
    except ImportError:
        print("Missing Python dependency. Run:")
        print("  pip install makelive")
        sys.exit(1)


# ─────────────────────────────── File scanning ───────────────────────────────

def find_pairs(input_dir: Path) -> list[tuple[Path, Path]]:
    """Return sorted list of (jpg, mp4) pairs sharing the same stem."""
    jpg_map: dict[str, Path] = {}
    for f in input_dir.iterdir():
        if f.suffix.lower() == ".jpg":
            jpg_map[f.stem] = f

    pairs = []
    for f in input_dir.iterdir():
        if f.suffix.lower() == ".mp4" and f.stem in jpg_map:
            pairs.append((jpg_map[f.stem], f))

    return sorted(pairs, key=lambda p: p[0].stem)


# ─────────────────────────────── EXIF reading ────────────────────────────────

def get_capture_datetime(jpg: Path) -> str:
    """
    Read DateTimeOriginal + OffsetTimeOriginal from JPEG EXIF.
    Returns an ISO-8601 string like '2026-02-21T18:19:55+08:00'.
    Falls back to file mtime if EXIF is absent.
    """
    r = subprocess.run(
        ["exiftool", "-j", "-DateTimeOriginal", "-OffsetTimeOriginal", str(jpg)],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        try:
            data = json.loads(r.stdout)[0]
            dt_raw = data.get("DateTimeOriginal", "")   # "2026:02:21 18:19:55"
            tz = data.get("OffsetTimeOriginal", "")     # "+08:00" or ""

            if dt_raw:
                dt_iso = dt_raw.replace(":", "-", 2).replace(" ", "T")
                return dt_iso + tz if tz else dt_iso
        except (json.JSONDecodeError, IndexError, KeyError):
            pass

    import os
    from datetime import datetime
    mtime = os.path.getmtime(jpg)
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%S")


# ─────────────────────────────── Video processing ────────────────────────────

def transcode_to_h264_mov(src: Path, dst: Path) -> bool:
    """
    Transcode source video to H.264 MOV.
    Must re-encode (not stream copy) because Vivo records HEVC, and
    Photos.app requires H.264 for Live Photo video components.
    """
    r = subprocess.run(
        [
            "ffmpeg", "-i", str(src),
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "fast",
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y", "-loglevel", "error",
            str(dst),
        ],
        capture_output=True,
    )
    if r.returncode != 0:
        print(f"    [FFmpeg error] {r.stderr.decode(errors='replace')[:300]}")
    return r.returncode == 0


# ─────────────────────────────── Metadata injection ──────────────────────────

def write_live_photo_metadata(jpg: Path, mov: Path) -> str | None:
    """
    Write ContentIdentifier to both JPEG and MOV using macOS native APIs:
      - JPEG: CoreGraphics writes to Apple MakerNote (kCGImagePropertyMakerAppleDictionary["17"])
              This is what Photos.app actually reads for Live Photo pairing.
      - MOV:  AVFoundation writes to QuickTime Keys atom
              (com.apple.quicktime.content.identifier)

    Returns the asset UUID on success, None on failure.
    ExifTool cannot do this for non-Apple JPEGs; makelive uses the correct native APIs.
    """
    from makelive import make_live_photo
    try:
        asset_id = make_live_photo(str(jpg), str(mov))
        return asset_id
    except Exception as e:
        print(f"    [makelive error] {e}")
        return None


def set_mov_creation_date(mov: Path, creation_date: str) -> bool:
    """Write creation date to MOV QuickTime Keys (applied after makelive export)."""
    r = subprocess.run(
        [
            "exiftool",
            f"-Keys:CreationDate={creation_date}",
            "-overwrite_original",
            str(mov),
        ],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"    [ExifTool date error] {r.stderr.strip()[:200]}")
    return r.returncode == 0


# ─────────────────────────────── Per-pair pipeline ───────────────────────────

def process_pair(jpg: Path, mp4: Path, output_dir: Path) -> bool:
    stem = jpg.stem
    capture_dt = get_capture_datetime(jpg)

    out_jpg = output_dir / f"Live_{stem}.jpg"
    out_mov = output_dir / f"Live_{stem}.mov"

    print(f"  {stem}")
    print(f"    Time : {capture_dt}")

    # Step 1: Copy JPEG (preserves all original EXIF: GPS, lens, etc.)
    shutil.copy2(jpg, out_jpg)

    # Step 2: Transcode MP4 → H.264 MOV
    if not transcode_to_h264_mov(mp4, out_mov):
        print("    [FAIL] video transcode")
        return False

    # Step 3: Write ContentIdentifier via macOS CoreGraphics + AVFoundation
    #         (only method that creates proper Apple MakerNote in non-Apple JPEG)
    asset_id = write_live_photo_metadata(out_jpg, out_mov)
    if not asset_id:
        print("    [FAIL] ContentIdentifier injection")
        return False

    print(f"    UUID : {asset_id}")

    # Step 4: Align MOV creation date with JPEG capture time
    set_mov_creation_date(out_mov, capture_dt)

    print(f"    [OK]  → Live_{stem}.{{jpg,mov}}")
    return True


# ─────────────────────────────── Entry point ─────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    check_dependencies()

    input_dir = Path(sys.argv[1]).resolve()
    if not input_dir.is_dir():
        print(f"Error: not a directory: {input_dir}")
        sys.exit(1)

    output_dir = input_dir / "LivePhoto_Export"
    output_dir.mkdir(exist_ok=True)

    pairs = find_pairs(input_dir)
    if not pairs:
        print("No JPG+MP4 pairs found.")
        sys.exit(0)

    print(f"Found {len(pairs)} pair(s)")
    print(f"Output → {output_dir}\n")

    ok = 0
    for jpg, mp4 in pairs:
        if process_pair(jpg, mp4, output_dir):
            ok += 1
        print()

    print(f"{'─'*50}")
    print(f"Done: {ok}/{len(pairs)} converted.")

    if ok > 0:
        print(f"\nNext steps:")
        print(f"  1. Open Mac Photos.app")
        print(f"  2. File → Import")
        print(f"  3. Select the LivePhoto_Export folder")
        print(f"  4. Select ALL files (⌘A) then click Import")
        print(f"     (both files must be imported together for pairing)")


if __name__ == "__main__":
    main()
