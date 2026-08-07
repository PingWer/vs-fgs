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
