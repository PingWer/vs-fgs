import ctypes
import typing
import struct
import vapoursynth as vs

core = vs.core


class Dav1dFilmGrainData(ctypes.Structure):
    _fields_ = [
        ("seed", ctypes.c_uint),
        ("num_y_points", ctypes.c_int),
        ("y_points", (ctypes.c_uint8 * 2) * 14),
        ("chroma_scaling_from_luma", ctypes.c_int),
        ("num_uv_points", ctypes.c_int * 2),
        ("uv_points", ((ctypes.c_uint8 * 2) * 10) * 2),
        ("scaling_shift", ctypes.c_int),
        ("ar_coeff_lag", ctypes.c_int),
        ("ar_coeffs_y", ctypes.c_int8 * 24),
        ("ar_coeffs_uv", (ctypes.c_int8 * 28) * 2),
        ("ar_coeff_shift", ctypes.c_uint64),
        ("grain_scale_shift", ctypes.c_int),
        ("uv_mult", ctypes.c_int * 2),
        ("uv_luma_mult", ctypes.c_int * 2),
        ("uv_offset", ctypes.c_int * 2),
        ("overlap_flag", ctypes.c_int),
        ("clip_to_restricted_range", ctypes.c_int),
    ]


def _parse_binary_fgs(fgs_file_path: str, target_num_frames: int) -> bytes:
    records = []
    with open(fgs_file_path, "rb") as f:
        while True:
            apply_grain_bytes = f.read(4)
            if not apply_grain_bytes or len(apply_grain_bytes) < 4:
                break

            data = Dav1dFilmGrainData()
            _ = struct.unpack("<i", apply_grain_bytes)[0]
            data.seed = struct.unpack("<H", f.read(2))[0]
            _update_parameters = struct.unpack("<i", f.read(4))[0]

            data.num_y_points = struct.unpack("<i", f.read(4))[0]
            if data.num_y_points > 0:
                for j in range(data.num_y_points):
                    val, scaling = struct.unpack("<ii", f.read(8))
                    if j < 14:
                        data.y_points[j][0] = val
                        data.y_points[j][1] = scaling

            data.num_uv_points[0] = struct.unpack("<i", f.read(4))[0]
            if data.num_uv_points[0] > 0:
                for j in range(data.num_uv_points[0]):
                    val, scaling = struct.unpack("<ii", f.read(8))
                    if j < 10:
                        data.uv_points[0][j][0] = val
                        data.uv_points[0][j][1] = scaling

            data.num_uv_points[1] = struct.unpack("<i", f.read(4))[0]
            if data.num_uv_points[1] > 0:
                for j in range(data.num_uv_points[1]):
                    val, scaling = struct.unpack("<ii", f.read(8))
                    if j < 10:
                        data.uv_points[1][j][0] = val
                        data.uv_points[1][j][1] = scaling

            data.scaling_shift = struct.unpack("<i", f.read(4))[0]
            data.ar_coeff_lag = struct.unpack("<i", f.read(4))[0]

            if data.num_y_points > 0:
                y_ar = struct.unpack("<24i", f.read(96))
                for j in range(24):
                    data.ar_coeffs_y[j] = y_ar[j]

            if data.num_uv_points[0] > 0:
                cb_ar = struct.unpack("<25i", f.read(100))
                for j in range(25):
                    data.ar_coeffs_uv[0][j] = cb_ar[j]

            if data.num_uv_points[1] > 0:
                cr_ar = struct.unpack("<25i", f.read(100))
                for j in range(25):
                    data.ar_coeffs_uv[1][j] = cr_ar[j]

            data.ar_coeff_shift = struct.unpack("<i", f.read(4))[0]
            data.grain_scale_shift = struct.unpack("<i", f.read(4))[0]

            if data.num_uv_points[0] > 0:
                data.uv_mult[0], data.uv_luma_mult[0], data.uv_offset[0] = (
                    struct.unpack("<iii", f.read(12))
                )
                data.uv_mult[0] -= 128
                data.uv_luma_mult[0] -= 128
                data.uv_offset[0] -= 256

            if data.num_uv_points[1] > 0:
                data.uv_mult[1], data.uv_luma_mult[1], data.uv_offset[1] = (
                    struct.unpack("<iii", f.read(12))
                )
                data.uv_mult[1] -= 128
                data.uv_luma_mult[1] -= 128
                data.uv_offset[1] -= 256

            data.overlap_flag = struct.unpack("<i", f.read(4))[0]
            data.clip_to_restricted_range = struct.unpack("<i", f.read(4))[0]

            records.append(bytes(data))

    if not records:
        raise ValueError("vsfgs: binary FGS file is empty or malformed.")

    fgs_structs_bytes = bytearray()
    for n in range(target_num_frames):
        if n < len(records):
            fgs_structs_bytes.extend(records[n])
        else:
            fgs_structs_bytes.extend(records[-1])

    return bytes(fgs_structs_bytes)


def apply_fgs(
    clip: vs.VideoNode,
    fgs_file_path: str,
    ignore_chroma: bool = False,
    static: bool = False,
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
        blocks = []
        current_block = None
        bare_lines = []

        with open(fgs_file_path, "r") as f:
            for line in f:
                parts = line.strip().split()
                if not parts:
                    continue

                if parts[0] == "E":
                    start_t = int(parts[1])
                    end_t = int(parts[2])
                    if start_t == 0 and end_t == 0:
                        end_t = float("inf")

                    current_block = {
                        "lines": [parts],
                        "start_time": start_t,
                        "end_time": end_t,
                    }
                    blocks.append(current_block)
                elif current_block is not None:
                    current_block["lines"].append(parts)
                elif parts[0] not in ("filmgrn1",):
                    bare_lines.append(parts)

        if not blocks:
            blocks.append(
                {"lines": bare_lines, "start_time": 0, "end_time": float("inf")}
            )

        parsed_blocks = []
        required_tokens = {"p", "sY", "sCb", "sCr", "cY", "cCb", "cCr"}

        for b_idx, b in enumerate(blocks):
            data = Dav1dFilmGrainData()
            found_tokens = set()

            try:
                for parts in b["lines"]:
                    token = parts[0]
                    found_tokens.add(token)
                    if token == "E":
                        data.seed = int(parts[4])
                    elif token == "p":
                        data.ar_coeff_lag = int(parts[1])
                        data.ar_coeff_shift = int(parts[2])
                        data.grain_scale_shift = int(parts[3])
                        data.scaling_shift = int(parts[4])
                        data.chroma_scaling_from_luma = int(parts[5])
                        data.overlap_flag = int(parts[6])
                        data.uv_mult[0] = int(parts[7]) - 128
                        data.uv_luma_mult[0] = int(parts[8]) - 128
                        data.uv_offset[0] = int(parts[9]) - 256
                        data.uv_mult[1] = int(parts[10]) - 128
                        data.uv_luma_mult[1] = int(parts[11]) - 128
                        data.uv_offset[1] = int(parts[12]) - 256
                    elif token == "sY":
                        data.num_y_points = int(parts[1])
                        for i in range(data.num_y_points):
                            data.y_points[i][0] = int(parts[2 + i * 2])
                            data.y_points[i][1] = int(parts[3 + i * 2])
                    elif token == "sCb":
                        data.num_uv_points[0] = int(parts[1])
                        for i in range(data.num_uv_points[0]):
                            data.uv_points[0][i][0] = int(parts[2 + i * 2])
                            data.uv_points[0][i][1] = int(parts[3 + i * 2])
                    elif token == "sCr":
                        data.num_uv_points[1] = int(parts[1])
                        for i in range(data.num_uv_points[1]):
                            data.uv_points[1][i][0] = int(parts[2 + i * 2])
                            data.uv_points[1][i][1] = int(parts[3 + i * 2])
                    elif token == "cY":
                        for i in range(len(parts) - 1):
                            data.ar_coeffs_y[i] = int(parts[1 + i])
                    elif token == "cCb":
                        for i in range(len(parts) - 1):
                            data.ar_coeffs_uv[0][i] = int(parts[1 + i])
                    elif token == "cCr":
                        for i in range(len(parts) - 1):
                            data.ar_coeffs_uv[1][i] = int(parts[1 + i])
            except (IndexError, ValueError) as e:
                raise ValueError(
                    f"vsfgs: malformed parameters in FGS file at Event {b_idx + 1}, line: {' '.join(parts)}"
                ) from e

            missing_tokens = required_tokens - found_tokens
            if missing_tokens:
                raise ValueError(
                    f"vsfgs: missing required FGS fields {missing_tokens} in Event {b_idx + 1}"
                )

            data.clip_to_restricted_range = (
                1  # Could be exposed in the signature in the future
            )

            parsed_blocks.append(
                {
                    "data_bytes": bytes(data),
                    "start_time": b["start_time"],
                    "end_time": b["end_time"],
                }
            )

        fps_num = clip.fps.numerator
        fps_den = clip.fps.denominator
        if fps_num == 0:
            raise ValueError(
                "vs_fgs requires a constant framerate clip for dynamic FGS parsing. Please set clip fps."
            )

        timebase_scale = 10000000.0
        fgs_structs_bytes = bytearray()
        zero_data = bytes(Dav1dFilmGrainData())

        import bisect

        start_times = [b["start_time"] for b in parsed_blocks]

        for n in range(clip.num_frames):
            frame_time_exact = (n * fps_den * timebase_scale) / fps_num
            frame_time = int(round(frame_time_exact))

            # 10% of a frame duration as safety margin for floating point / timestamp drift
            tolerance = ((fps_den * timebase_scale) / fps_num) * 0.1

            if ignore_length and len(parsed_blocks) == 1:
                active_bytes = parsed_blocks[0]["data_bytes"]
            else:
                idx = bisect.bisect_right(start_times, frame_time) - 1
                if (
                    idx >= 0
                    and frame_time <= parsed_blocks[idx]["end_time"] + tolerance
                ):
                    active_bytes = parsed_blocks[idx]["data_bytes"]
                else:
                    active_bytes = zero_data

            fgs_structs_bytes.extend(active_bytes)

        fgs_bytes = bytes(fgs_structs_bytes)

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
        clip, fgs_data=fgs_bytes, dynamic_seed=dynamic_seed, simd_mask=simd_mask
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
