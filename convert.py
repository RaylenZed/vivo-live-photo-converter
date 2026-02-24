#!/usr/bin/env python3
"""
vivo-live-photo-converter
将 Vivo 动态照片转换为 Apple 实况照片 | Convert Vivo Motion Photos to Apple Live Photos

用法 / Usage:
    python3 convert.py <照片文件夹 / photo_directory>

依赖 / Dependencies (一次性安装 / one-time setup):
    brew install ffmpeg exiftool
    pip install makelive
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# 并行线程数：CPU 核数的一半，最多 4 个
# Workers: half of CPU cores, max 4
MAX_WORKERS = max(1, min((os.cpu_count() or 2) // 2, 4))

_print_lock = threading.Lock()


def log(text: str):
    """线程安全打印 / Thread-safe print."""
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


# ─────────────────────────────── 视频转码 / Video transcode ──────────────────

def transcode_to_h264_mov(src: Path, dst: Path) -> bool:
    """
    MP4 (HEVC) → H.264 MOV
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


# ─────────────────────────────── 元数据注入 / Metadata injection ──────────────

def write_live_photo_metadata(jpg: Path, mov: Path) -> str | None:
    """
    通过 macOS CoreGraphics + AVFoundation 写入 ContentIdentifier。
    Use macOS native APIs to write ContentIdentifier to Apple MakerNote + QuickTime Keys.
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


# ─────────────────────────────── 单对处理 / Process one pair ─────────────────

def process_pair(jpg: Path, mp4: Path, output_dir: Path) -> bool:
    stem = jpg.stem
    capture_dt = get_capture_datetime(jpg)
    out_jpg = output_dir / f"Live_{stem}.jpg"
    out_mov = output_dir / f"Live_{stem}.mov"

    lines = [f"  {stem}", f"    时间 / Time : {capture_dt}"]

    shutil.copy2(jpg, out_jpg)

    if not transcode_to_h264_mov(mp4, out_mov):
        lines.append("    [失败 / FAIL] 视频转码 / video transcode")
        log('\n'.join(lines) + '\n')
        return False

    asset_id = write_live_photo_metadata(out_jpg, out_mov)
    if not asset_id:
        lines.append("    [失败 / FAIL] 元数据注入 / metadata injection")
        log('\n'.join(lines) + '\n')
        return False

    lines.append(f"    UUID : {asset_id}")
    set_mov_creation_date(out_mov, capture_dt)
    lines.append(f"    [完成 / OK] → Live_{stem}.{{jpg,mov}}")
    log('\n'.join(lines) + '\n')
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
    print(f"并行线程 / Workers : {MAX_WORKERS}\n")

    # ── 并行处理实况照片对 / Process Live Photo pairs in parallel ──
    ok = 0
    if pairs:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(process_pair, jpg, mp4, output_dir): jpg.stem
                for jpg, mp4 in pairs
            }
            for future in as_completed(futures):
                if future.result():
                    ok += 1

    # ── 复制单独文件 / Copy unpaired files ──
    copy_unpaired(unpaired, output_dir)

    print("─" * 50)
    print(f"完成 / Done: {ok}/{len(pairs)} 对转换成功 / pair(s) converted")
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
