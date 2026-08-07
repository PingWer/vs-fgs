# vs-fgs v0.7.0 Improvements

- Added `load_av1fgs_video` helper function to load AV1 video files and automatically extract/apply embedded FGS tables via `grav1synth`.
- Added dual indexer support for the video loader: `BestSource` (default, `fast=False` for frame accuracy) and `FFMS2` (`fast=True` for faster indexing).
- Added native BestSource terminal progress bar by hooking into VapourSynth's internal logger (no third-party dependencies required).
- Changed BestSource cache path logic (`cachemode=3`) to store `.bsindex` files directly next to the input video file.
- Added native support for binary FGS table files (`.bin`).
- Added support for Igor's alternative seed list (`seed_list=0`) alongside Netflix's seed list (`seed_list=1`).
- Improved high bit-depth handling (>12-bit / Float): grain is applied via 12-bit delta extraction (`MakeDiff`/`MergeDiff`) with `dither_type="none"`, completely eliminating dithering alterations.
- Refactored `vsfgs` into a clean modular Python package (`core.py`, `source.py`, `parser.py`, `__init__.py`) and removed all `vsjetpack`/`vssource` external dependencies.
