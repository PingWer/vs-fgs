# vs-fgs

A VapourSynth plugin for applying Film Grain Synthesis' table (FGS) using the [dav1d](https://code.videolan.org/videolan/dav1d) decoder.

Since `dav1d` is widely regarded as the best and fastest AV1 decoder available, its FGS engine is fully spec-compliant with **AFGS1** (AOMedia Film Grain Synthesis 1), guaranteeing highly accurate, performant, and standardized grain generation.

`vsfgs` parses standard FGS text files and applies film grain to the input clip natively in **8-bit, 10-bit, or 12-bit YUV**.

## Why this plugin

Film Grain Synthesis (FGS) represents a massive step forward in video compression, allowing to model film grain mathematically rather than encoding random noise. 

This plugin was built with two primary goals in mind:
- **Visualizing and Fine-Tuning FGS**: It serves as a "real-time" visualization tool during your encoding pipeline. By rendering the grain dynamically, you can preview, adjust, and perfectly tune your FGS tables in relation to the actual video content (especially when paired with tools like [FGSE](https://github.com/PingWer/FGSEditor)).
- **Grain Baking**: Not all target codecs (e.g. H.264, VP9, HEVC) support FGS playback, and you don't always want to distribute video files with separate grain metadata. `vsfgs` gives you the ability to *bake* the high-quality, standardized AFGS1 grain directly into the video stream before handing it off to your encoder.

Furthermore, this tool is future-proof for processing official AV1 streams (e.g. Netflix) that already have FGS embedded inside them, allowing you to seamlessly extract, visualize, or bake their grain during filtering and re-encoding.

## Installation
```bash
pip install vsfgs
```

### External Dependencies
To use the `load_av1fgs_video` function (which automatically extracts FGS data from a video file), you **must** have [grav1synth](https://github.com/rust-av/grav1synth) installed and available in your system's `PATH`!

## Usage

```python
import vapoursynth as vs
import vsfgs

core = vs.core

# 1. Load an AV1 video and automatically apply its embedded Film Grain
# It will extract the FGS tables using grav1synth and map them perfectly to the decoded clip.
# 
# Indexers used:
# - fast=False (Default): Uses BestSource. Slower indexing, but guarantees perfect frame accuracy (recommended).
# - fast=True: Uses FFMS2. Faster indexing.
clip = vsfgs.load_av1fgs_video("source_av1.mkv", fast=False)

# 2. Manual FGS Application (Optional)
# If you already have your video clip and a separate grain table (.bin or .txt), you can apply it manually:
# - ignore_chroma: If True, grain is only applied to Luma (Chroma is copied).
# - static: If True, uses the seed from the FGS table for all frames (if dynamic FGS, per event). If False, rotates the seed for each frame. Note: for `.bin` files, dynamic_seed is disabled automatically.
# - simd: Hardware SIMD architecture ('auto', 'avx512', 'avx2', 'sse41', 'sse3', 'sse2', or 'none'/'c' for plain C). Defaults to 'auto'.
clip = vsfgs.apply_fgs(clip, "grain_table.bin", ignore_chroma=False, static=False, simd="auto")

clip.set_output()
```

> For detailed parameter types, descriptions, and additional indexer arguments (`idx_kwargs`), check the function docstrings.

### Frame Properties

For each processed frame, `vsfgs` outputs the exact seed integer used during synthesis into the VapourSynth frame properties: **`FGS_Seed`**


## Input Format & Advanced Customization

`vsfgs` supports input grain files in both standard **`.txt` (AFGS1 textual format)** and directly compiled **`.bin` (Binary format)**. It allows for extreme and advanced customization of the film grain synthesis pattern.

For complete details on the required text syntax, binary packing parameters, and an advanced visual editor to create and fine-tune these tables, please refer to the **FGSEditor** wiki:
[https://github.com/PingWer/FGSEditor](https://github.com/PingWer/FGSEditor/wiki)

## Technical & Implementation Notes

### High Bit-Depth & Precision Preservation
The underlying `dav1d` FGS synthesis engine strictly operates on 8-bit, 10-bit, or 12-bit integer YUV clips.
To support higher bit-depths (>12-bit integer or Float formats) without quality loss:
- The input clip is temporarily converted to 12-bit integer using `dither_type="none"`.
- Film grain is synthesized at 12-bit depth.
- The isolated grain pattern (delta) is extracted via `MakeDiff`, scaled back to match the original clip format, and applied onto the untouched original clip using `MergeDiff`.

This approach **completely eliminates quantization and dithering alterations**.

### Indexer & Video Loader Flexibility
The `load_av1fgs_video` function is provided strictly as a **convenience wrapper** to automate video loading and FGS table extraction via `grav1synth`:
- It indexes only the video stream (ignoring audio/subtitles).
- You are **not locked into** using `load_av1fgs_video`. You can freely use any video loader or indexer of your choice (e.g. `lsmas`, `d2vsource`, manual `BestSource`/`ffms2`, etc.) to load your clip, and then call `vsfgs.apply_fgs(clip, fgs_path)` directly with any `.txt` or `.bin` grain table.

## Performance & Compatibility

`vsfgs` uses `dav1d`'s hand-written Assembly instructions (AVX-512, AVX2, SSE3 ...), resulting in extremely high throughput with almost zero overhead.

**Platform Support:**

| OS | Architecture | Supported | Tested |
| :--- | :--- | :---: | :---: |
| **Windows** | x86_64, ARM64 | ✅ | ✅ |
| **Linux** | x86_64, aarch64 | ✅ | ❌ |
| **macOS** | x86_64, Apple Silicon | ✅ | ❌ |

**Benchmark Comparison** *(2,000 frames of real 1080p source via `BestSource`)*:
Tests compared `vsfgs` against `Grainer.GAUSS` (from `vsjetpack`). It also demonstrates the speedup of `dav1d`'s hardware SIMD Assembly optimizations over unvectorized reference C code (`simd='none'`).

| Format | Baseline (BestSource + 16bit conversion) | `vsfgs` (SIMD: Auto / AVX-512) | `vsfgs` (SIMD: None / Plain C) | `Grainer.GAUSS` (`vsjetpack`) |
| --- | --- | --- | --- | --- |
| **YUV420P16** | ~1128 FPS | **~557 FPS** | ~514 FPS | ~347 FPS |
| **YUV422P16** | ~866 FPS | **~434 FPS** | ~425 FPS | ~322 FPS |
| **YUV444P16** | ~649 FPS | **~305 FPS** | ~299 FPS | ~279 FPS |

## Building from Source

To compile the plugin manually, you must have a working C++ toolchain and Meson setup. The plugin depends on `dav1d`, which will be built automatically as a Meson subproject.

### Prerequisites

- **Python 3.13+** (or newer)
- **C++ Compiler**: GCC/Clang (Linux/macOS) or MSVC (Windows)
- **Meson & Ninja**: Build system (`pip install meson ninja`)
- **nasm**: Highly recommended for x86/x64 systems to enable `dav1d` assembly optimizations (drastically improves grain synthesis performance).
  - *Windows*: `choco install nasm`
  - *Linux*: `sudo apt-get install nasm` or `sudo dnf install nasm`
  - *macOS*: `brew install nasm`

### Build Steps

1. Clone the repository recursively to fetch the `dav1d` submodule:
   ```bash
   git clone --recursive https://github.com/PingWer/vs-fgs.git
   cd vs-fgs
   ```

2. Build and install the plugin directly into your active Python environment:
   ```bash
   pip install .
   ```

### Standalone Build (Without Python Installation)

If you only want to compile the VapourSynth plugin binary (DLL/SO/DYLIB) without installing it via pip, you can use Meson directly:

```bash
meson setup build --buildtype=release --vsenv
meson compile -C build
```
## TODO
Any suggestions are welcome! But, the plugin is basically feature complete.

## Community & Support

For questions, feedback, or troubleshooting, feel free to join and reach out on the **AV1 Weeb edition** [Discord server](https://discord.gg/NbwnwhcgUq)

## License

This project is licensed under the **MIT License**.

### Third-Party Licenses

This project includes and statically links code from **[dav1d](https://code.videolan.org/videolan/dav1d)** (located in `subprojects/dav1d`), which is licensed under the **BSD 2-Clause License**:

```text
Copyright © 2018-2025, VideoLAN and dav1d authors. All rights reserved.
Licensed under the BSD 2-Clause License.
```
