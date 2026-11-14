import bisect
import ctypes
import struct

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
            apply_grain = struct.unpack("<i", apply_grain_bytes)[0]
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

            if apply_grain == 0:
                data.num_y_points = 0
                data.num_uv_points[0] = 0
                data.num_uv_points[1] = 0
                data.chroma_scaling_from_luma = 0

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


def _create_default_film_grain_data(seed: int = 7391) -> Dav1dFilmGrainData:
    data = Dav1dFilmGrainData()
    data.seed = seed
    data.clip_to_restricted_range = 1
    data.ar_coeff_lag = 3
    data.ar_coeff_shift = 8
    data.grain_scale_shift = 0
    data.scaling_shift = 8
    data.chroma_scaling_from_luma = 0
    data.overlap_flag = 1
    data.uv_mult[0] = 0
    data.uv_luma_mult[0] = 0
    data.uv_offset[0] = 0
    data.uv_mult[1] = 0
    data.uv_luma_mult[1] = 0
    data.uv_offset[1] = 0
    data.num_y_points = 0
    data.num_uv_points[0] = 0
    data.num_uv_points[1] = 0
    return data


def _extract_scaling_points(
    raw_coords: list[str], max_pts: int
) -> list[tuple[int, int]]:
    pairs = []
    for i in range(0, len(raw_coords) - 1, 2):
        try:
            vx = int(raw_coords[i])
            vy = int(raw_coords[i + 1])
            pairs.append((vx, vy))
        except ValueError:
            continue
    if not pairs:
        return []
    if pairs != sorted(pairs, key=lambda pt: pt[0]):
        pairs.sort(key=lambda pt: pt[0])
    deduped = []
    seen = set()
    for x, y in pairs:
        if x not in seen:
            seen.add(x)
            deduped.append((max(0, min(255, x)), max(0, min(255, y))))
    return deduped[:max_pts]


def _parse_text_fgs(
    fgs_file_path: str,
    target_num_frames: int,
    fps_num: int,
    fps_den: int,
    ignore_length: bool = False,
) -> bytes:
    blocks = []
    current_block = None
    bare_lines = []

    with open(fgs_file_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            clean = line.split("#", 1)[0].split("//", 1)[0].strip()
            if not clean:
                continue

            parts = clean.split()
            if not parts:
                continue

            tag = parts[0].lower()
            if tag in ("filmgrn1", "afgs1") or (
                tag.startswith("filmgrn") and tag[7:].isdigit()
            ):
                continue

            if tag == "e":
                try:
                    start_t = int(parts[1]) if len(parts) > 1 else 0
                    end_t = int(parts[2]) if len(parts) > 2 else start_t + 10000000
                except ValueError:
                    start_t, end_t = 0, 10000000

                if start_t == 0 and end_t == 0:
                    end_t = float("inf")

                apply_grain = 1
                seed = 7391
                update_params = 1

                if len(parts) > 3:
                    try:
                        apply_grain = int(parts[3])
                    except ValueError:
                        apply_grain = 1
                if len(parts) > 4:
                    try:
                        seed = int(parts[4])
                    except ValueError:
                        seed = 7391
                if len(parts) > 5:
                    try:
                        update_params = int(parts[5])
                    except ValueError:
                        update_params = 1

                current_block = {
                    "start_time": start_t,
                    "end_time": end_t,
                    "apply_grain": apply_grain,
                    "seed": seed,
                    "update_params": update_params,
                    "lines": [],
                }
                blocks.append(current_block)
            elif current_block is not None:
                current_block["lines"].append(parts)
            else:
                bare_lines.append(parts)

    if not blocks:
        blocks.append(
            {
                "lines": bare_lines,
                "start_time": 0,
                "end_time": float("inf"),
                "apply_grain": 1,
                "seed": 7391,
                "update_params": 1,
            }
        )

    parsed_blocks = []
    prev_data = None

    for b_idx, b in enumerate(blocks):
        update_params = b["update_params"]
        apply_grain = b["apply_grain"]
        seed = b["seed"]

        if update_params == 0 and prev_data is not None:
            data = Dav1dFilmGrainData.from_buffer_copy(prev_data)
            data.seed = seed
        else:
            data = _create_default_film_grain_data(seed=seed)

        parts: list[str] = []
        try:
            for parts in b["lines"]:
                tag = parts[0].lower()

                if tag == "p":
                    # p lag shift scale_shift scaling_shift chroma_scaling overlap [cb_mult cb_luma_mult cb_offset cr_mult cr_luma_mult cr_offset]
                    if len(parts) > 1:
                        data.ar_coeff_lag = int(parts[1])
                    if len(parts) > 2:
                        data.ar_coeff_shift = int(parts[2])
                    if len(parts) > 3:
                        data.grain_scale_shift = int(parts[3])
                    if len(parts) > 4:
                        data.scaling_shift = int(parts[4])
                    if len(parts) > 5:
                        data.chroma_scaling_from_luma = int(parts[5])
                    if len(parts) > 6:
                        data.overlap_flag = int(parts[6])
                    if len(parts) >= 13:
                        data.uv_mult[0] = int(parts[7]) - 128
                        data.uv_luma_mult[0] = int(parts[8]) - 128
                        data.uv_offset[0] = int(parts[9]) - 256
                        data.uv_mult[1] = int(parts[10]) - 128
                        data.uv_luma_mult[1] = int(parts[11]) - 128
                        data.uv_offset[1] = int(parts[12]) - 256
                elif tag == "sy":
                    pts = _extract_scaling_points(
                        parts[2:] if len(parts) > 2 else [], 14
                    )
                    data.num_y_points = len(pts)
                    for i, (x, y) in enumerate(pts):
                        data.y_points[i][0] = x
                        data.y_points[i][1] = y
                elif tag == "scb":
                    pts = _extract_scaling_points(
                        parts[2:] if len(parts) > 2 else [], 10
                    )
                    data.num_uv_points[0] = len(pts)
                    for i, (x, y) in enumerate(pts):
                        data.uv_points[0][i][0] = x
                        data.uv_points[0][i][1] = y
                elif tag == "scr":
                    pts = _extract_scaling_points(
                        parts[2:] if len(parts) > 2 else [], 10
                    )
                    data.num_uv_points[1] = len(pts)
                    for i, (x, y) in enumerate(pts):
                        data.uv_points[1][i][0] = x
                        data.uv_points[1][i][1] = y
                elif tag in ("cy", "y"):
                    num_coeffs = min(len(parts) - 1, 24)
                    for i in range(num_coeffs):
                        data.ar_coeffs_y[i] = max(-128, min(127, int(parts[1 + i])))
                elif tag in ("ccb", "cb"):
                    num_coeffs = min(len(parts) - 1, 28)
                    for i in range(num_coeffs):
                        data.ar_coeffs_uv[0][i] = max(-128, min(127, int(parts[1 + i])))
                elif tag in ("ccr", "cr"):
                    num_coeffs = min(len(parts) - 1, 28)
                    for i in range(num_coeffs):
                        data.ar_coeffs_uv[1][i] = max(-128, min(127, int(parts[1 + i])))
        except (IndexError, ValueError) as e:
            line_str = " ".join(parts) if parts else "<empty>"
            raise ValueError(
                f"vsfgs: malformed parameters in FGS file at Event {b_idx + 1}, line: {line_str}"
            ) from e

        if data.chroma_scaling_from_luma:
            data.num_uv_points[0] = 0
            data.num_uv_points[1] = 0

        # Preserve the valid parameter model before zeroing for apply_grain == 0
        if update_params != 0 or prev_data is None:
            prev_data = Dav1dFilmGrainData.from_buffer_copy(data)

        if apply_grain == 0:
            data.num_y_points = 0
            data.num_uv_points[0] = 0
            data.num_uv_points[1] = 0
            data.chroma_scaling_from_luma = 0

        parsed_blocks.append(
            {
                "data_bytes": bytes(data),
                "start_time": b["start_time"],
                "end_time": b["end_time"],
            }
        )

    if fps_num == 0:
        raise ValueError(
            "vsfgs: requires a constant framerate clip for dynamic FGS parsing. Please set clip fps."
        )

    timebase_scale = 10000000.0
    fgs_structs_bytes = bytearray()
    zero_data = bytes(Dav1dFilmGrainData())

    start_times = [b["start_time"] for b in parsed_blocks]

    for n in range(target_num_frames):
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

    return bytes(fgs_structs_bytes)
