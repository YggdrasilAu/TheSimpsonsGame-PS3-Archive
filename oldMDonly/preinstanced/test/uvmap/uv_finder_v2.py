# SPDX-License-Identifier: MIT
# uv_finder_v2.py
# Extract and validate UVs from a Simpsons Game .preinstanced file by
# cross-referencing with a correct .obj (Rosetta Stone). Improves matching by
# allowing multiple UVs per XYZ (handles UV seams) and outputs extracted UV CSV.

import struct
import re
import sys
import os
import io
from collections import defaultdict, Counter

# --- Configuration ---
MESH_REGEX = re.compile(b"\x33\xEA\x00\x00....\x2D\x00\x02\x1C", re.DOTALL)
ROUND_PRECISION = 5  # rounding for comparisons

# --- Helpers ---

def print_c(text, color="green"):
    colors = {
        "green": "\033[92m",
        "yellow": "\033[93m",
        "red": "\033[91m",
        "blue": "\033[94m",
        "reset": "\033[0m",
    }
    start = colors.get(color, colors["green"])
    end = colors["reset"]
    print(f"{start}{text}{end}")

# --- OBJ Parsing (more robust) ---

def parse_obj_multi(obj_filepath):
    """
    Parse .obj and build:
      - v_list (1-indexed)
      - vt_list (1-indexed)
      - pos_to_uvs: dict[(x,y,z_rounded)] -> set of (u,v_rounded) that occur on faces
    Using sets allows multiple UVs per XYZ (seams), improving match rates.
    """
    print_c(f"\nParsing Rosetta Stone: {obj_filepath}", "blue")
    v_list = [(0.0, 0.0, 0.0)]
    vt_list = [(0.0, 0.0)]
    pos_to_uvs = defaultdict(set)

    faces = 0
    try:
        with open(obj_filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if not line:
                    continue
                if line.startswith('v '):
                    parts = line.split()
                    if len(parts) >= 4:
                        v_list.append((float(parts[1]), float(parts[2]), float(parts[3])))
                elif line.startswith('vt '):
                    parts = line.split()
                    if len(parts) >= 3:
                        vt_list.append((float(parts[1]), float(parts[2])))
                elif line.startswith('f '):
                    faces += 1
                    parts = line.split()[1:]
                    for grp in parts:
                        # Accept formats v/vt[/vn] or v//vn
                        items = grp.split('/')
                        if not items or not items[0]:
                            continue
                        try:
                            v_idx = int(items[0])
                        except ValueError:
                            continue
                        vt_idx = None
                        if len(items) >= 2 and items[1] != '':
                            try:
                                vt_idx = int(items[1])
                            except ValueError:
                                vt_idx = None
                        if vt_idx is None:
                            continue
                        if not (0 < v_idx < len(v_list)):
                            continue
                        if not (0 < vt_idx < len(vt_list)):
                            continue
                        x, y, z = v_list[v_idx]
                        u, v = vt_list[vt_idx]
                        pos_key = (round(x, ROUND_PRECISION), round(y, ROUND_PRECISION), round(z, ROUND_PRECISION))
                        uv_val = (round(u, ROUND_PRECISION), round(v, ROUND_PRECISION))
                        pos_to_uvs[pos_key].add(uv_val)
    except FileNotFoundError:
        print_c(f"[Error] .obj file not found: {obj_filepath}", "red")
        return v_list, vt_list, {}
    except Exception as e:
        print_c(f"[Error] Failed to parse .obj: {e}", "red")
        return v_list, vt_list, {}

    print_c(f"Parsed {len(v_list)-1} positions and {len(vt_list)-1} UVs.")
    print_c(f"Collected UVs for {len(pos_to_uvs)} unique positions from {faces} faces.")
    return v_list, vt_list, pos_to_uvs

# --- Core Analysis ---

def analyze_preinstanced(pre_path, pos_to_uvs, csv_out=None):
    print_c(f"\nAnalyzing Target File: {pre_path}", "blue")
    if not pos_to_uvs:
        print_c("[Error] OBJ mapping is empty. Cannot proceed.", "red")
        return

    try:
        with open(pre_path, 'rb') as f:
            data = f.read()
    except FileNotFoundError:
        print_c(f"[Error] Target file not found: {pre_path}", "red")
        return

    bio = io.BytesIO(data)

    grand_total_verts = 0
    best_results = []  # per submesh best (stride, offset, flipped, matches, total)
    global_offset_hits = Counter()  # track which offsets win across submeshes

    for m in MESH_REGEX.finditer(data):
        mesh_chunk_off = m.start()
        bio.seek(m.end() + 4)
        try:
            FaceDataOff = int.from_bytes(bio.read(4), 'little')
            MeshDataSize = int.from_bytes(bio.read(4), 'little')
            MeshChunkStart = bio.tell()
            bio.seek(0x14, 1)
            tbl_count = int.from_bytes(bio.read(4), 'big')
            sub_count = int.from_bytes(bio.read(4), 'big')
            print(f"\nFound Mesh Chunk @ {mesh_chunk_off:08X} (Sub-meshes: {sub_count})")

            for _ in range(tbl_count):
                bio.seek(4, 1)
                bio.read(4)
            sub_table = bio.tell()

            for i in range(sub_count):
                bio.seek(sub_table + i * 0xC + 8)
                offset = int.from_bytes(bio.read(4), 'big')
                bio.seek(offset + MeshChunkStart + 0xC)
                vc_off = int.from_bytes(bio.read(4), 'big') + MeshChunkStart
                bio.seek(vc_off)
                total_size = int.from_bytes(bio.read(4), 'big')
                stride = int.from_bytes(bio.read(4), 'big')
                if stride <= 0:
                    print(f"  [MeshPart {i}] Skipping, invalid stride: {stride}")
                    continue
                count = total_size // stride if stride else 0
                bio.seek(8, 1)
                v_start = int.from_bytes(bio.read(4), 'big') + FaceDataOff + MeshChunkStart

                print(f"  [MeshPart {i}] Verts: {count}, Stride: {stride} (0x{stride:X}), Data @ {v_start:08X}")
                grand_total_verts += count

                # Try every 4-byte aligned offset after XYZ, ensure 8 bytes fit
                offset_candidates = list(range(12, stride - 7, 4))
                best = None  # (matches, offset, flipped)

                # Optionally store per-vertex best uv for CSV (filled later after best known)
                # First pass: score candidates
                for off in offset_candidates:
                    m_raw = 0
                    m_flip = 0
                    for v in range(count):
                        s = v_start + v * stride
                        if s + 12 > len(data):
                            break
                        x, y, z = struct.unpack('>fff', data[s:s+12])
                        key = (round(x, ROUND_PRECISION), round(y, ROUND_PRECISION), round(z, ROUND_PRECISION))
                        uv_set = pos_to_uvs.get(key)
                        if not uv_set:
                            continue
                        u, vv = struct.unpack('>ff', data[s+off:s+off+8])
                        uv_raw = (round(u, ROUND_PRECISION), round(vv, ROUND_PRECISION))
                        uv_flip = (uv_raw[0], round(1.0 - (vv), ROUND_PRECISION))
                        if uv_raw in uv_set:
                            m_raw += 1
                        if uv_flip in uv_set:
                            m_flip += 1
                    # update best
                    cand = (m_raw, off, False) if m_raw >= m_flip else (m_flip, off, True)
                    if best is None or cand[0] > best[0]:
                        best = cand

                if best is None:
                    print_c(f"    [MeshPart {i}] No candidate offsets matched any vertices.", "yellow")
                    continue

                best_matches, best_off, best_flip = best
                global_offset_hits[(stride, best_off, best_flip)] += 1
                print_c(f"    -> Best: Offset 0x{best_off:X} ({best_off}), Flipped-V: {best_flip}, Matches: {best_matches}/{count}")
                best_results.append((i, stride, best_off, best_flip, best_matches, count, v_start))

        except Exception as e:
            print_c(f"  [MeshChunk @ {mesh_chunk_off:08X}] Error while analyzing sub-meshes: {e}", "yellow")
            continue

    # Summary of best offsets across submeshes
    if not best_results:
        print_c("\nNo successful matches across any mesh parts.", "red")
        return

    print_c("\n--- Summary of Best Offsets per Sub-mesh ---", "blue")
    for (idx, stride, off, flip, m, c, _) in best_results:
        print(f"  [MeshPart {idx}] Stride {stride:>2} | Offset 0x{off:X} | Flip {flip} | {m}/{c} matches")

    common = global_offset_hits.most_common(1)[0]
    (g_stride, g_off, g_flip), g_hits = common
    print_c(f"\nMost common winning combo: Stride={g_stride}, Offset=0x{g_off:X}, Flip={g_flip} (won {g_hits} sub-meshes)")

    # Extract UVs for the most common combo and (optionally) write CSV
    extracted = []  # list of (meshpart, index_in_part, x,y,z,u,v)
    total_extracted = 0
    for (idx, stride, off, flip, m, c, v_start) in best_results:
        if (stride, off, flip) != (g_stride, g_off, g_flip):
            continue
        for v in range(c):
            s = v_start + v * stride
            if s + 12 > len(data) or s + off + 8 > len(data):
                break
            x, y, z = struct.unpack('>fff', data[s:s+12])
            u, vv = struct.unpack('>ff', data[s+off:s+off+8])
            if flip:
                vv = 1.0 - vv
            extracted.append((idx, v, x, y, z, u, vv))
            total_extracted += 1

    print_c(f"\nExtracted {total_extracted} UVs using (Stride={g_stride}, Offset=0x{g_off:X}, Flip={g_flip}).")

    if csv_out and extracted:
        try:
            with open(csv_out, 'w', encoding='utf-8') as wf:
                wf.write("meshpart,vertex_index,x,y,z,u,v\n")
                for rec in extracted:
                    wf.write(",".join([str(x) for x in rec]) + "\n")
            print_c(f"Wrote extracted UVs to: {csv_out}")
        except Exception as e:
            print_c(f"[Warn] Failed to write CSV: {e}", "yellow")

# --- Main ---
if __name__ == '__main__':
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print_c("Usage: python uv_finder_v2.py <reference.obj> <target.preinstanced> [out.csv]", "red")
        sys.exit(1)

    obj_path = sys.argv[1]
    pre_path = sys.argv[2]
    csv_out = sys.argv[3] if len(sys.argv) == 4 else None

    if not os.path.exists(obj_path):
        print_c(f"Error: File not found: {obj_path}", "red")
        sys.exit(1)
    if not os.path.exists(pre_path):
        print_c(f"Error: File not found: {pre_path}", "red")
        sys.exit(1)

    _, _, pos_to_uvs = parse_obj_multi(obj_path)
    if pos_to_uvs:
        analyze_preinstanced(pre_path, pos_to_uvs, csv_out)
