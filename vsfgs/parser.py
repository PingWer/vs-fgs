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
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            parts = line.split()
            if not parts:
                continue

            tag = parts[0]
            if tag.lower() in ("filmgrn1", "afgs1"):
                continue

            if tag.upper() == "E":
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
            else:
                bare_lines.append(parts)

    if not blocks:
        blocks.append(
            {"lines": bare_lines, "start_time": 0, "end_time": float("inf")}
        )

    parsed_blocks = []

    for b_idx, b in enumerate(blocks):
        data = Dav1dFilmGrainData()
        data.clip_to_restricted_range = 1
        found_tokens = set()
        parts: list[str] = []

        try:
            for parts in b["lines"]:
                tag = parts[0].lower()
                found_tokens.add(tag)

                if tag == "e":
                    if len(parts) > 4:
                        data.seed = int(parts[4])
                elif tag == "p":
                    # p lag shift scale_shift scaling_shift chroma_scaling overlap [cb_mult cb_luma_mult cb_offset cr_mult cr_luma_mult cr_offset]
                    data.ar_coeff_lag = int(parts[1])
                    data.ar_coeff_shift = int(parts[2])
                    data.grain_scale_shift = int(parts[3])
                    data.scaling_shift = int(parts[4])
                    data.chroma_scaling_from_luma = int(parts[5])
                    data.overlap_flag = int(parts[6])
                    if len(parts) >= 13:
                        data.uv_mult[0] = int(parts[7]) - 128
                        data.uv_luma_mult[0] = int(parts[8]) - 128
                        data.uv_offset[0] = int(parts[9]) - 256
                        data.uv_mult[1] = int(parts[10]) - 128
                        data.uv_luma_mult[1] = int(parts[11]) - 128
                        data.uv_offset[1] = int(parts[12]) - 256
                elif tag == "sy":
                    num_pts = int(parts[1])
                    data.num_y_points = min(num_pts, 14)
                    for i in range(data.num_y_points):
                        data.y_points[i][0] = int(parts[2 + i * 2])
                        data.y_points[i][1] = int(parts[3 + i * 2])
                elif tag == "scb":
                    num_pts = int(parts[1])
                    data.num_uv_points[0] = min(num_pts, 10)
                    for i in range(data.num_uv_points[0]):
                        data.uv_points[0][i][0] = int(parts[2 + i * 2])
                        data.uv_points[0][i][1] = int(parts[3 + i * 2])
                elif tag == "scr":
                    num_pts = int(parts[1])
                    data.num_uv_points[1] = min(num_pts, 10)
                    for i in range(data.num_uv_points[1]):
                        data.uv_points[1][i][0] = int(parts[2 + i * 2])
                        data.uv_points[1][i][1] = int(parts[3 + i * 2])
                elif tag == "cy":
                    num_coeffs = min(len(parts) - 1, 24)
                    for i in range(num_coeffs):
                        data.ar_coeffs_y[i] = int(parts[1 + i])
                elif tag == "ccb":
                    num_coeffs = min(len(parts) - 1, 28)
                    for i in range(num_coeffs):
                        data.ar_coeffs_uv[0][i] = int(parts[1 + i])
                elif tag == "ccr":
                    num_coeffs = min(len(parts) - 1, 28)
                    for i in range(num_coeffs):
                        data.ar_coeffs_uv[1][i] = int(parts[1 + i])
        except (IndexError, ValueError) as e:
            line_str = " ".join(parts) if parts else "<empty>"
            raise ValueError(
                f"vsfgs: malformed parameters in FGS file at Event {b_idx + 1}, line: {line_str}"
            ) from e

        if "p" not in found_tokens or "sy" not in found_tokens:
            raise ValueError(
                f"vsfgs: missing required FGS fields ('p' or 'sY') in Event {b_idx + 1}"
            )

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
