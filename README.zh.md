# vivo-live-photo-converter

[English](./README.md) | **中文**

将 Vivo（安卓）动态照片转换为 Apple 实况照片，完整保留 GPS、镜头等 EXIF 元数据。

---

## 背景

用 Vivo 手机拍摄的动态照片导出后，会变成同名的 `IMG_XXX.jpg` + `IMG_XXX.mp4` 文件对。直接拖入 Mac 照片 App，不仅实况效果丢失，GPS、镜头等 EXIF 元数据也可能缺失。

本工具将这些文件对预处理成 Apple 照片 App 能原生识别的实况照片格式。

## 原理

| 步骤 | 操作 | 原因 |
|------|------|------|
| 1 | 原样复制 JPEG | 完整保留 GPS、镜头、时间等所有 EXIF |
| 2 | MP4 转码为 H.264 MOV | Photos.app 只识别 H.264；Vivo 录制的是 HEVC |
| 3 | 通过 CoreGraphics + AVFoundation 写入 `ContentIdentifier` | ExifTool 无法为非 Apple JPEG 创建 MakerNote；必须用 macOS 原生 API |
| 4 | 将 MOV 创建时间对齐至 JPEG 拍摄时间 | 照片库中显示正确日期 |

**核心发现：** Apple 照片 App 通过匹配 JPEG 的 Apple MakerNote（`kCGImagePropertyMakerAppleDictionary["17"]`，而非 XMP）与 MOV 的 QuickTime Keys atom（`com.apple.quicktime.content.identifier`）来配对实况照片。ExifTool 写入 XMP 的方式对 Photos.app 无效。

## 环境要求

- macOS（依赖 CoreGraphics / AVFoundation）
- Python 3.9+
- [ffmpeg](https://ffmpeg.org/) — 视频转码
- [exiftool](https://exiftool.org/) — 读取 EXIF
- [makelive](https://github.com/RhetTbull/makelive) — 写入 Apple MakerNote 和 QuickTime Keys

## 安装（一次性）

```bash
brew install ffmpeg exiftool
pip install makelive
```

## 使用方法

```bash
python3 convert.py /你的vivo照片文件夹/
```

**小技巧：** 在终端输入 `python3 convert.py `（末尾加空格），然后把文件夹直接拖进终端窗口，路径会自动填入。

脚本会自动扫描文件夹中同名的 JPG+MP4 对，处理结果输出到 `LivePhoto_Export/` 子文件夹：

```
你的文件夹/
├── IMG_20260221_181955.jpg
├── IMG_20260221_181955.mp4
├── ...
└── LivePhoto_Export/
    ├── Live_IMG_20260221_181955.jpg   ← 可直接导入 Apple 照片
    ├── Live_IMG_20260221_181955.mov
    └── ...
```

## 导入 Apple 照片 App

1. 打开**照片 App** → **文件 → 导入**
2. 进入 `LivePhoto_Export` 文件夹
3. 按 **⌘A** 全选所有文件
4. 点击**导入** — 配对成功的照片会显示**「实况」**标志

## 注意事项

- 原始文件不会被修改
- 无对应 MP4 的 JPG 会自动跳过
- 支持批量处理，一次可转换任意数量的文件对
- JPEG 中的 GPS、镜头型号等所有 EXIF 元数据完整保留

## License

MIT
