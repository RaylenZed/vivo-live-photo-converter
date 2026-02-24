# vivo-live-photo-converter

**English** | [中文](./README.md)

Convert Vivo (Android) Motion Photos to Apple Live Photos — preserving GPS, lens metadata, and full resolution.

---

## Background

When exporting Vivo Motion Photos, they appear as separate `IMG_XXX.jpg` + `IMG_XXX.mp4` pairs. Importing them directly into Apple Photos breaks the Live Photo pairing and strips metadata.

This tool preprocesses the pairs so Apple Photos recognizes them as native Live Photos on import. It also copies any standalone photos or videos (without a matching counterpart) to the output folder, so everything can be imported in one go.

## How It Works

| Step | Action | Why |
|------|--------|-----|
| 1 | Copy JPEG (unchanged) | Preserve all original EXIF: GPS, lens, timestamp |
| 2 | Transcode MP4 → H.264 MOV | Photos.app requires H.264; Vivo records HEVC |
| 3 | Write `ContentIdentifier` via CoreGraphics + AVFoundation | ExifTool cannot create Apple MakerNote on non-Apple JPEGs; macOS native APIs must be used |
| 4 | Align MOV `CreationDate` with JPEG capture time | Correct date display in Photos.app |

**Key insight:** Apple Photos pairs Live Photo files by matching `kCGImagePropertyMakerAppleDictionary["17"]` in the JPEG (Apple MakerNote, not XMP) with `com.apple.quicktime.content.identifier` in the MOV QuickTime Keys atom.

## Requirements

- macOS (required for CoreGraphics/AVFoundation)
- Python 3.9+
- [ffmpeg](https://ffmpeg.org/) — video transcoding
- [exiftool](https://exiftool.org/) — EXIF reading
- [makelive](https://github.com/RhetTbull/makelive) — Apple MakerNote + QuickTime Keys injection

## Installation

```bash
# One-time setup
brew install ffmpeg exiftool
pip install makelive
```

## Usage

```bash
python3 convert.py /path/to/vivo/photos/
```

**Tip:** In Terminal, type `python3 convert.py ` then drag your photo folder into the window — the path fills in automatically.

The script handles all files in the folder:

- **Matched JPG+MP4 pairs** → converted to Live Photos, output as `Live_XXX.jpg` + `Live_XXX.mov`
- **Standalone JPG or MP4** (no matching counterpart) → copied as-is for easy import

```
your_folder/
├── IMG_001.jpg  ←─ Live Photo pair
├── IMG_001.mp4  ←─
├── IMG_002.jpg  ←─ standalone photo
├── VID_003.mp4  ←─ standalone video
└── LivePhoto_Export/
    ├── Live_IMG_001.jpg   ← Live Photo (UUID injected)
    ├── Live_IMG_001.mov   ← Live Photo (UUID injected)
    ├── IMG_002.jpg        ← regular photo (copied)
    └── VID_003.mp4        ← regular video (copied)
```

Sample output:

```
找到 4 对实况照片，3 个单独文件
Found 4 Live Photo pair(s), 3 unpaired file(s)
输出目录 / Output → .../LivePhoto_Export
并行线程 / Workers : 4

  IMG_20260221_181955
    时间 / Time : 2026-02-21T18:19:55+08:00
    UUID : A3B65AD7-275C-48DD-9C58-066EF631E978
    [完成 / OK] → Live_IMG_20260221_181955.{jpg,mov}
...
复制单独文件 / Copying unpaired files (3)...
  IMG_20260221_183000.jpg  →  已复制 / copied
──────────────────────────────────────────────────
完成 / Done: 4/4 对转换成功 / pair(s) converted
  + 3 个单独文件已复制 / unpaired file(s) copied
```

## Import to Apple Photos

1. Open **Photos.app** → **File → Import**
2. Navigate to the `LivePhoto_Export` folder
3. Press **⌘A** to select all files
4. Click **Import** — Live Photos will appear with the **LIVE** badge

## Notes

- Original files are never modified
- Multi-threaded: automatically uses half of available CPU cores (up to 4 workers) for faster processing
- Batch processing: handles any number of pairs in one run
- GPS, lens model, and all other EXIF metadata are fully preserved from the original JPEG

## License

MIT
