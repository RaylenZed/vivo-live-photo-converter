#!/usr/bin/env python3
"""
vivo-live-photo-converter
将 Vivo 动态照片转换为 Apple 实况照片 | Convert Vivo Motion Photos to Apple Live Photos

用法 / Usage:
    python3 convert.py <照片文件夹 / photo_directory>

依赖 / Dependencies (一次性安装 / one-time setup):
    brew install ffmpeg exiftool
    pip install makelive

两阶段处理 / Two-phase processing:
    阶段一（并行）：FFmpeg 将 MP4 转码为 H.264 MOV        — CPU 密集，线程安全
    Phase 1 (parallel):  FFmpeg transcodes MP4 → H.264 MOV   — CPU-bound, thread-safe
    阶段二（串行）：makelive 注入 ContentIdentifier           — AVFoundation 非线程安全
    Phase 2 (serial):    makelive injects ContentIdentifier   — AVFoundation not thread-safe
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# 转码并行数：CPU 核数的一半，最多 4 个 / Transcode workers: half of CPU cores, max 4
TRANSCODE_WORKERS = max(1, min((os.cpu_count() or 2) // 2, 4))

_print_lock = threading.Lock()


def log(text: str):
    with _print_lock:
        print(text)


# ─────────────────────────────── 依赖检查 / Dependency check ─────────────────

def check_dependencies():
    missing = [t for t in ("ffmpeg", "exiftool")
               if subprocess.run(["which", t], capture_output=True).returncode != 0]
    if missing:
        print(f"缺少工具 / Missing tools: {' '.join(missing)}")
        print(f"  brew install {' '.join(missing)}")
        sys.exit(1)
    try:
        import makelive  # noqa: F401
    except ImportError:
        print("缺少 Python 包 / Missing Python package: makelive")
        print("  pip install makelive")
        sys.exit(1)


# ─────────────────────────────── 扫描目录 / Scan directory ───────────────────

def scan_directory(input_dir: Path):
    """
    返回 / Returns:
      pairs    — 同名 JPG+MP4 文件对 / (jpg, mp4) pairs with matching stems
      unpaired — 无对应文件的单独 JPG 或 MP4 / lone JPG or MP4 files
    """
    jpg_map: dict[str, Path] = {}
    mp4_map: dict[str, Path] = {}

    for f in input_dir.iterdir():
        if f.suffix.lower() == ".jpg":
            jpg_map[f.stem] = f
        elif f.suffix.lower() == ".mp4":
            mp4_map[f.stem] = f

    paired_stems: set[str] = set()
    pairs: list[tuple[Path, Path]] = []
    for stem, jpg in jpg_map.items():
        if stem in mp4_map:
            pairs.append((jpg, mp4_map[stem]))
            paired_stems.add(stem)

    unpaired: list[Path] = (
        [f for stem, f in jpg_map.items() if stem not in paired_stems] +
        [f for stem, f in mp4_map.items() if stem not in paired_stems]
    )

    return (
        sorted(pairs, key=lambda p: p[0].stem),
        sorted(unpaired, key=lambda f: f.name),
    )


# ─────────────────────────────── 读取 EXIF / Read EXIF ───────────────────────

def get_capture_datetime(jpg: Path) -> str:
    r = subprocess.run(
        ["exiftool", "-j", "-DateTimeOriginal", "-OffsetTimeOriginal", str(jpg)],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        try:
            data = json.loads(r.stdout)[0]
            dt_raw = data.get("DateTimeOriginal", "")
            tz = data.get("OffsetTimeOriginal", "")
            if dt_raw:
                dt_iso = dt_raw.replace(":", "-", 2).replace(" ", "T")
                return dt_iso + tz if tz else dt_iso
        except (json.JSONDecodeError, IndexError, KeyError):
            pass
    from datetime import datetime
    return datetime.fromtimestamp(os.path.getmtime(jpg)).strftime("%Y-%m-%dT%H:%M:%S")


# ─────────────────────────────── 阶段一：转码 / Phase 1: Transcode ───────────

def transcode_to_h264_mov(src: Path, dst: Path) -> bool:
    """
    MP4 (HEVC) → H.264 MOV（线程安全 / thread-safe）
    Photos.app 仅支持 H.264 作为实况照片视频组件
    Photos.app requires H.264 for Live Photo video components.
    """
    r = subprocess.run(
        [
            "ffmpeg", "-i", str(src),
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-y", "-loglevel", "error",
            str(dst),
        ],
        capture_output=True,
    )
    if r.returncode != 0:
        log(f"    [FFmpeg 错误 / error] {r.stderr.decode(errors='replace')[:300]}")
    return r.returncode == 0


def prepare_pair(jpg: Path, mp4: Path, output_dir: Path):
    """
    阶段一：复制 JPEG + 转码视频（并行执行）
    Phase 1: copy JPEG + transcode video (runs in parallel)
    Returns (out_jpg, out_mov, capture_dt, stem) on success, None on failure.
    """
    stem = jpg.stem
    capture_dt = get_capture_datetime(jpg)
    out_jpg = output_dir / f"Live_{stem}.jpg"
    out_mov = output_dir / f"Live_{stem}.mov"

    shutil.copy2(jpg, out_jpg)

    if not transcode_to_h264_mov(mp4, out_mov):
        log(f"  {stem}\n    [失败 / FAIL] 视频转码 / video transcode\n")
        return None

    log(f"  {stem}  →  转码完成 / transcoded")
    return (out_jpg, out_mov, capture_dt, stem)


# ─────────────────────────────── 阶段二：注入 / Phase 2: Inject ──────────────

def write_live_photo_metadata(jpg: Path, mov: Path) -> str | None:
    """
    通过 macOS CoreGraphics + AVFoundation 写入 ContentIdentifier（串行执行）
    Use macOS native APIs — must run serially, AVFoundation is not thread-safe here.
    """
    from makelive import make_live_photo
    try:
        return make_live_photo(str(jpg), str(mov))
    except Exception as e:
        log(f"    [makelive 错误 / error] {e}")
        return None


def set_mov_creation_date(mov: Path, creation_date: str) -> bool:
    r = subprocess.run(
        ["exiftool", f"-Keys:CreationDate={creation_date}", "-overwrite_original", str(mov)],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def finalize_pair(out_jpg: Path, out_mov: Path, capture_dt: str, stem: str) -> bool:
    """
    阶段二：注入 ContentIdentifier（串行执行，避免 AVFoundation 并发问题）
    Phase 2: inject ContentIdentifier (serial — avoids AVFoundation concurrency issues)
    """
    asset_id = write_live_photo_metadata(out_jpg, out_mov)
    if not asset_id:
        log(f"  {stem}\n    [失败 / FAIL] 元数据注入 / metadata injection\n")
        return False

    set_mov_creation_date(out_mov, capture_dt)
    log(f"  {stem}\n    UUID : {asset_id}\n    [完成 / OK] → Live_{stem}.{{jpg,mov}}\n")
    return True


# ─────────────────────────────── 复制单独文件 / Copy unpaired files ──────────

def copy_unpaired(files: list[Path], output_dir: Path):
    if not files:
        return
    log(f"复制单独文件 / Copying unpaired files ({len(files)})...")
    for f in files:
        shutil.copy2(f, output_dir / f.name)
        log(f"  {f.name}  →  已复制 / copied")
    log("")


# ─────────────────────────────── 入口 / Entry point ──────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    check_dependencies()

    input_dir = Path(sys.argv[1]).resolve()
    if not input_dir.is_dir():
        print(f"错误 / Error: 不是目录 / not a directory: {input_dir}")
        sys.exit(1)

    output_dir = input_dir / "LivePhoto_Export"
    output_dir.mkdir(exist_ok=True)

    pairs, unpaired = scan_directory(input_dir)

    if not pairs and not unpaired:
        print("未找到照片 / No photos found.")
        sys.exit(0)

    print(f"找到 {len(pairs)} 对实况照片，{len(unpaired)} 个单独文件")
    print(f"Found {len(pairs)} Live Photo pair(s), {len(unpaired)} unpaired file(s)")
    print(f"输出目录 / Output → {output_dir}")
    print(f"转码线程 / Transcode workers : {TRANSCODE_WORKERS}\n")

    # ── 阶段一（并行）：转码 / Phase 1 (parallel): transcode ──────────────────
    print("阶段一 / Phase 1: 转码 / Transcoding...\n")
    prepared = []
    with ThreadPoolExecutor(max_workers=TRANSCODE_WORKERS) as executor:
        futures = {
            executor.submit(prepare_pair, jpg, mp4, output_dir): jpg.stem
            for jpg, mp4 in pairs
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                prepared.append(result)

    # ── 阶段二（串行）：注入元数据 / Phase 2 (serial): inject metadata ─────────
    print(f"\n阶段二 / Phase 2: 注入元数据 / Injecting metadata ({len(prepared)} 个 / files)...\n")
    ok = 0
    for item in sorted(prepared, key=lambda x: x[3]):  # sort by stem for tidy output
        out_jpg, out_mov, capture_dt, stem = item
        if finalize_pair(out_jpg, out_mov, capture_dt, stem):
            ok += 1

    # ── 复制单独文件 / Copy unpaired files ──────────────────────────────────
    copy_unpaired(unpaired, output_dir)

    print("─" * 50)
    print(f"完成 / Done: {ok}/{len(pairs)} 对转换成功 / pair(s) converted")
    if len(pairs) - ok > 0:
        print(f"  ⚠ {len(pairs) - ok} 对失败 / pair(s) failed")
    if unpaired:
        print(f"  + {len(unpaired)} 个单独文件已复制 / unpaired file(s) copied")

    if ok + len(unpaired) > 0:
        print("""
下一步 / Next steps:
  1. 打开照片 App / Open Photos.app
  2. 文件 → 导入 / File → Import
  3. 选择 LivePhoto_Export 文件夹 / Select LivePhoto_Export folder
  4. ⌘A 全选后点导入 / Select all (⌘A) then Import""")


if __name__ == "__main__":
    main()
