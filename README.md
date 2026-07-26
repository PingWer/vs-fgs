# vs-fgs

A VapourSynth plugin for applying Film Grain Synthesis' table (FGS) using the [dav1d](https://code.videolan.org/videolan/dav1d) decoder.

Since `dav1d` is widely regarded as the best and fastest AV1 decoder available, its FGS engine is fully spec-compliant with **AFGS1** (AOMedia Film Grain Synthesis 1), guaranteeing highly accurate, performant, and standardized grain generation.

`vsfgs` parses standard FGS text files and applies film grain to the input clip natively in **8-bit, 10-bit, or 12-bit YUV**. It also handles automatic dithering if the input bit depth is higher.

## Installation
```bash
pip install vsfgs
```

## Usage

```python
import vapoursynth as vs
import vsfgs

core = vs.core

# 1. Load your video
clip = your_video_loader("source.mkv")

# 2. Apply Film Grain
# - ignore_chroma: If True, grain is only applied to Luma (Chroma is copied).
# - static: If True, uses the seed from the FGS table for all frames (if dynamic FGS, per event). If False, rotates the seed for each frame.
# - simd: Hardware SIMD architecture ('auto', 'avx512', 'avx2', 'sse41', 'sse3', 'sse2', or 'none'/'c' for plain C). Defaults to 'auto'.
clip = vsfgs.apply_fgs(clip, "grain_table.txt", ignore_chroma=False, static=False, simd="auto")

clip.set_output()
```

### Frame Properties

For each processed frame, `vsfgs` outputs the exact seed integer used during synthesis into the VapourSynth frame properties map: **`FGS_Seed`**


## Advanced Customization

`vsfgs` allows for extreme and advanced customization of the film grain pattern. The logic for synthesizing grain relies on a detailed parameter table.
For an advanced visual editor to fine-tune these parameters and for more details on the grain configuration, please refer to the **FGSEditor** wiki:
[https://github.com/PingWer/FGSEditor](https://github.com/PingWer/FGSEditor)

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
meson setup build --buildtype=release
meson compile -C build
```
## License

This project is licensed under the **MIT License**.
