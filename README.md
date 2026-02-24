# vivo-live-photo-converter

Convert Vivo (Android) Motion Photos to Apple Live Photos — preserving GPS, lens metadata, and full resolution.

> **Vivo 动态照片 → Apple 实况照片** 转换工具，完整保留 GPS、镜头等 EXIF 元数据。

---

## Background

When exporting Vivo Motion Photos, they appear as separate `IMG_XXX.jpg` + `IMG_XXX.mp4` pairs. Importing them directly into Apple Photos breaks the Live Photo pairing and strips metadata.

This tool preprocesses the pairs so Apple Photos recognizes them as native Live Photos on import.

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

The script scans the folder for `*.jpg` + `*.mp4` pairs with matching filenames and outputs to a `LivePhoto_Export/` subfolder:

```
your_folder/
├── IMG_20260221_181955.jpg
├── IMG_20260221_181955.mp4
├── ...
└── LivePhoto_Export/
    ├── Live_IMG_20260221_181955.jpg   ← ready for Apple Photos
    ├── Live_IMG_20260221_181955.mov
    └── ...
```

## Import to Apple Photos

1. Open **Photos.app** → **File → Import**
2. Navigate to the `LivePhoto_Export` folder
3. Press **⌘A** to select all files
4. Click **Import** — paired files will appear as Live Photos with the **LIVE** badge

## Notes

- Original files are never modified
- Non-Motion Photos (JPG without a matching MP4) are skipped automatically
- Batch processing: handles any number of pairs in one run
- GPS, lens model, and all other EXIF metadata are fully preserved from the original JPEG

## License

MIT
