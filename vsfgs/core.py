import typing
import vapoursynth as vs
from .parser import _parse_binary_fgs, _parse_text_fgs

core = vs.core

def apply_fgs(
    clip: vs.VideoNode,
    fgs_file_path: str,
    ignore_chroma: bool = False,
    static: bool = False,
    seed_list: int = 0,
    simd: str | int = "auto",
    temporal_average: float | tuple[float, int] | None = None,
    temporal_avg_func: typing.Callable[[vs.VideoNode], vs.VideoNode] | None = None,
    ignore_length: bool = False,
) -> vs.VideoNode:
    """
    Applies Film Grain Synthesis (FGS) to a video clip using dav1d's FGS engine implementation.

    This function parses a standard FGS text file format and applies the film grain to the input clip.

    The FGS engine strictly operates on 8-bit, 10-bit, or 12-bit YUV data (4:2:0, 4:2:2, or 4:4:4).
    If the input clip has an unsupported bit depth or is float, it will be temporarily converted to 12-bit (without dithering).
    For high bit depth clips (> 12-bit integer or float), the generated grain is isolated via `MakeDiff` and applied back to the pristine original clip using `MergeDiff`. This guarantees that the original video's precision is perfectly preserved.

    Args:
        clip: The input VapourSynth clip.
        fgs_file_path: The path to the text file containing the FGS parameters.
        ignore_chroma: If True, grain is only applied to Luma (Chroma is copied). Default: False.
        static: If True, the seed from the FGS table is used for all frames. If False, the seed rotates using a curated list for each frame. Default: False.
        simd: SIMD instruction set to use ('auto', 'avx512', 'avx2', 'sse41', 'sse3', 'sse2', 'none'/'c', or an integer bitmask). Default: 'auto'.
        temporal_average: Temporal grain smoothing weight or (weight, radius). Extracts the grain and blends it with a temporally averaged version of itself. Default: None.
        temporal_avg_func: Custom function to use for temporal averaging instead of the default `core.std.AverageFrames`. Default: None.
        ignore_length: If True and there is only a single FGS event, ignores its length and applies it to the entire video. Default: False.

    Returns:
        vs.VideoNode: The clip with film grain applied (always returned in the same bit depth as the input).
    """
    if not hasattr(core, "fgs") or not hasattr(core.fgs, "FGS"):
        raise RuntimeError("vs_fgs plugin is not loaded correctly")

    if clip.format.color_family != vs.YUV:
        raise ValueError(
            "vsfgs: only YUV color family is supported. Please convert your clip to YUV first."
        )

    original_clip = clip
    original_format = clip.format

    if (
        original_format.bits_per_sample not in (8, 10, 12)
        or original_format.sample_type != vs.INTEGER
    ):
        target_bits = 12
        target_fmt = original_format.replace(
            bits_per_sample=target_bits, sample_type=vs.INTEGER
        ).id

        if (
            original_format.bits_per_sample > 12
            or original_format.sample_type == vs.FLOAT
        ):
            clip = clip.resize.Bicubic(format=target_fmt, dither_type="none")
        else:
            clip = clip.resize.Bicubic(format=target_fmt, dither_type="none")

    if fgs_file_path.lower().endswith(".bin"):
        fgs_bytes = _parse_binary_fgs(fgs_file_path, clip.num_frames)
    else:
        fgs_bytes = _parse_text_fgs(
            fgs_file_path,
            clip.num_frames,
            clip.fps.numerator,
            clip.fps.denominator,
            ignore_length=ignore_length,
        )

    # For binary FGS files, seeds and parameters are pre-baked per-frame.
    is_binary = fgs_file_path.lower().endswith(".bin")
    dynamic_seed = 0 if (static or is_binary) else 1

    simd_mask = -1
    if isinstance(simd, str):
        s = simd.strip().lower()
        if s == "auto":
            simd_mask = -1
        elif s in ("none", "c"):
            simd_mask = 0
        elif s == "sse2":
            simd_mask = 1 << 0
        elif s in ("ssse3", "sse3"):
            simd_mask = (1 << 0) | (1 << 1)
        elif s in ("sse4.1", "sse41", "sse4"):
            simd_mask = (1 << 0) | (1 << 1) | (1 << 2)
        elif s in ("avx2", "avx"):
            simd_mask = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3)
        elif s in ("avx512", "avx-512", "avx512icl"):
            simd_mask = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)
        else:
            raise ValueError(
                f"vsfgs: invalid simd architecture '{simd}'. Supported values: 'auto', 'none', 'sse2', 'sse3', 'sse41', 'avx2', 'avx512'."
            )
    elif isinstance(simd, int):
        simd_mask = simd
    else:
        raise TypeError("vsfgs: simd parameter must be a string or an integer bitmask.")

    fgs_clip = core.fgs.FGS(
        clip, fgs_data=fgs_bytes, dynamic_seed=dynamic_seed, simd_mask=simd_mask, seed_list=seed_list
    )
    base_fgs_clip = fgs_clip

    temp_weight, temp_radius = 0.0, 0
    if temporal_average is not None:
        if isinstance(temporal_average, (float, int)):
            temp_weight = float(temporal_average)
            temp_radius = 1 if temp_weight > 0.0 else 0
        elif isinstance(temporal_average, tuple):
            temp_weight = float(temporal_average[0])
            temp_radius = int(temporal_average[1])

    needs_diff = (
        temp_weight > 0.0 and (temp_radius > 0 or temporal_avg_func is not None)
    ) or (
        original_format.id != clip.format.id
        and (
            original_format.bits_per_sample > 12
            or original_format.sample_type == vs.FLOAT
        )
    )

    if needs_diff:
        grain_diff = core.std.MakeDiff(clipa=fgs_clip, clipb=clip)

        if temp_weight > 0.0 and (temp_radius > 0 or temporal_avg_func is not None):
            if temporal_avg_func is not None:
                avg_grain = temporal_avg_func(grain_diff)
            else:
                avg_grain = core.std.AverageFrames(
                    grain_diff, weights=[1.0] * (temp_radius * 2 + 1)
                )
            grain_diff = core.std.Merge(grain_diff, avg_grain, weight=temp_weight)

        if original_format.id != clip.format.id:
            grain_diff = grain_diff.resize.Bicubic(
                format=original_format.id, dither_type="none"
            )

        fgs_clip = core.std.MergeDiff(clipa=original_clip, clipb=grain_diff)
    else:
        if original_format.id != clip.format.id:
            fgs_clip = fgs_clip.resize.Bicubic(
                format=original_format.id, dither_type="none"
            )

    if ignore_chroma:
        fgs_clip = core.std.ShufflePlanes(
            clips=[fgs_clip, original_clip, original_clip],
            planes=[0, 1, 2],
            colorfamily=vs.YUV,
        )
    return core.std.CopyFrameProps(
        clip=fgs_clip, prop_src=base_fgs_clip, props=["FGS_Seed"]
    )
