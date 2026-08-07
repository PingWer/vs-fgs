import inspect
import os
import shutil
import subprocess
import vapoursynth as vs
from typing import Any
from pathlib import Path
from .core import apply_fgs

core = vs.core


def load_av1fgs_video(
    video_path: str,
    fast: bool = False,
    show_progress: bool = True,
    grav_path: str | None = None,
    simd: str | int = "auto",
    **kwargs: Any,
) -> vs.VideoNode:
    """
    Loads an AV1 video and automatically extracts and applies its Film Grain Synthesis (FGS) data.

    This uses native VapourSynth source filters for neutral and optimal initialization:
    - BestSource (`core.bs.VideoSource`) by default.
    - FFMS2 (`core.ffms2.Source`) if `fast=True`.
    Index files are saved alongside the video.

    The FGS table is extracted using `grav1synth` (which must be in PATH or provided via `grav_path`).
    The extracted FGS table is saved alongside the video with a `.tbl` extension so it can be reused
    on subsequent loads without re-extracting.

    If the video contains no FGS data, a message is printed, and the original video is returned.

    Args:
        video_path: Path to the AV1 video file.
        fast: If True, uses FFMS2 instead of BestSource for decoding. Default: False.
        show_progress: If True, displays a progress bar during indexing (only supported by BestSource). Default: True.
        simd: SIMD instruction set to use ('auto', 'avx512', 'avx2', 'sse41', 'sse3', 'sse2', 'none'/'c', or an integer bitmask). Default: 'auto'.
        grav_path: Path to the `grav1synth` executable. If None, it looks in PATH, CWD, or next to the calling .vpy script.
        **kwargs: Additional arguments to pass to the source indexer (BestSource or FFMS2).

    Returns:
        vs.VideoNode: The loaded video clip, with FGS applied if present in the source file.
    """
    video_p = Path(video_path).resolve()
    if not video_p.is_file():
        raise FileNotFoundError(f"vsfgs: Video file not found: {video_path}")

    idx_kwargs = kwargs

    if fast:
        if not hasattr(core, "ffms2") or not hasattr(core.ffms2, "Source"):
            raise RuntimeError(
                "vsfgs: FFMS2 plugin is required when fast=True but it is not loaded."
            )
        clip = core.ffms2.Source(source=str(video_p), **idx_kwargs)
    else:
        if not hasattr(core, "bs") or not hasattr(core.bs, "VideoSource"):
            raise RuntimeError(
                "vsfgs: BestSource plugin (bs.VideoSource) is required when fast=False but it is not loaded."
            )

        if "cachepath" not in idx_kwargs:
            idx_kwargs["cachepath"] = str(video_p.resolve())
            if "cachemode" not in idx_kwargs:
                idx_kwargs["cachemode"] = 3

        if show_progress:
            if "showprogress" not in idx_kwargs:
                idx_kwargs["showprogress"] = 1

            import logging
            import re
            import sys
            from contextlib import contextmanager

            @contextmanager
            def bs_progress_bar():
                class ProgressHandler(logging.Handler):
                    def __init__(self):
                        super().__init__()
                        self.progress_re = re.compile(r"progress\s+(\d+(?:\.\d+)?)%")
                        self.last_pct = -1

                    def emit(self, record):
                        m = self.progress_re.search(record.getMessage())
                        if m:
                            pct = float(m.group(1))
                            if int(pct) > self.last_pct:
                                self.last_pct = int(pct)
                                sys.stdout.write(f"\rIndexing BestSource: {pct:.1f}%")
                                sys.stdout.flush()

                logger = logging.getLogger("vapoursynth")
                old_level = logger.level
                logger.setLevel(logging.INFO)
                handler = ProgressHandler()
                logger.addHandler(handler)
                try:
                    yield
                    sys.stdout.write("\rIndexing BestSource: 100.0%\n")
                    sys.stdout.flush()
                finally:
                    logger.removeHandler(handler)
                    logger.setLevel(old_level)

            with bs_progress_bar():
                clip = core.bs.VideoSource(source=str(video_p), **idx_kwargs)
        else:
            clip = core.bs.VideoSource(source=str(video_p), **idx_kwargs)

    tbl_path = video_p.with_suffix(video_p.suffix + ".tbl")

    if not tbl_path.is_file():
        exe = grav_path
        if exe is None:
            exe = shutil.which("grav1synth")

            if exe is None:
                exe_name = "grav1synth.exe" if sys.platform == "win32" else "grav1synth"
                try:
                    for frame_info in inspect.stack():
                        caller_file = frame_info.filename
                        if caller_file and not caller_file.endswith(
                            os.path.basename(__file__)
                        ):
                            caller_dir = os.path.dirname(os.path.abspath(caller_file))
                            cand = os.path.join(caller_dir, exe_name)
                            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                                exe = cand
                                break
                except Exception:
                    pass

            if exe is None:
                cand = os.path.join(os.getcwd(), exe_name)
                if os.path.isfile(cand) and os.access(cand, os.X_OK):
                    exe = cand

            if exe is None:
                cand = os.path.join(os.path.dirname(str(video_p)), exe_name)
                if os.path.isfile(cand) and os.access(cand, os.X_OK):
                    exe = cand

        if exe is None:
            print(
                "vsfgs [INFO]: grav1synth not found in PATH. Returning pristine video without applying FGS."
            )
            return clip

        cmd = [exe, "inspect", "-o", str(tbl_path), "-y", str(video_p)]
        try:
            kwargs_subprocess = {}
            if os.name == "nt":
                kwargs_subprocess["creationflags"] = subprocess.CREATE_NO_WINDOW

            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                **kwargs_subprocess,
            )

            if res.returncode != 0:
                output_lower = res.stdout.lower()
                if any(
                    x in output_lower
                    for x in [
                        "no film grain",
                        "no grain",
                        "not found",
                        "does not contain",
                        "no fgs",
                    ]
                ):
                    print(
                        "vsfgs [INFO]: No FGS found in video. Returning original clip."
                    )
                else:
                    print(
                        f"vsfgs [WARNING]: grav1synth inspect failed (exit {res.returncode}). Returning original clip.\nOutput: {res.stdout}"
                    )

                if tbl_path.exists():
                    tbl_path.unlink(missing_ok=True)
                return clip

            if not tbl_path.is_file() or tbl_path.stat().st_size == 0:
                print(
                    "vsfgs [INFO]: grav1synth ran successfully but extracted no grain data. Returning original clip."
                )
                return clip

        except Exception as e:
            print(
                f"vsfgs [WARNING]: Failed to run grav1synth: {e}. Returning original clip."
            )
            return clip

    return apply_fgs(
        clip,
        str(tbl_path),
        simd=simd,
    )
