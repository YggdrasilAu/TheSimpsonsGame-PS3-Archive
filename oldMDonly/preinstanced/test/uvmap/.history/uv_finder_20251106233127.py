# SPDX-License-Identifier: MIT
# A 'dry run' script to find the correct UV offset in Simpsons Game files
# by cross-referencing with a correct .obj file.

import struct
import re
import sys
import os
import io

# --- Configuration ---

# Regex to find mesh chunks (same as your script)
MESH_REGEX = re.compile(b"\x33\xEA\x00\x00....\x2D\x00\x02\x1C", re.DOTALL)

# Precision for matching floats (XYZ and UV)
# .obj files can have rounding. 5 or 6 is usually safe.
ROUND_PRECISION = 5

# --- Utility Functions ---

def print_c(text, color="green"):
    """Prints text in color."""
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

def parse_obj(obj_filepath: str) -> dict[tuple, tuple]:
    """
    Parses a .obj file and builds a map of { (x,y,z) : (u,v) }
    This is our "ground truth" or "Rosetta Stone".
    """
    print_c(f"\nParsing Rosetta Stone: {obj_filepath}", "blue")
    v_list = [(0.0, 0.0, 0.0)]  # 1-indexed, add a dummy
    vt_list = [(0.0, 0.0)]   # 1-indexed, add a dummy
    xyz_to_uv_map = {}
    
    faces_processed = 0
    vertices_mapped = 0
    
    try:
        with open(obj_filepath, 'r') as f:
            for line in f:
                if line.startswith('v '):
                    parts = line.split()
                    v_list.append(tuple(float(p) for p in parts[1:4]))
                elif line.startswith('vt '):
                    parts = line.split()
                    vt_list.append(tuple(float(p) for p in parts[1:3]))
                elif line.startswith('f '):
                    faces_processed += 1
                    parts = line.split()[1:]
                    for v_group in parts:
                        indices = v_group.split('/')
                        v_idx = int(indices[0])
                        vt_idx = int(indices[1])
                        
                        # Get coords from our lists
                        xyz = v_list[v_idx]
                        uv = vt_list[vt_idx]
                        
                        # Create a key by rounding the XYZ
                        xyz_key = (
                            round(xyz[0], ROUND_PRECISION),
                            round(xyz[1], ROUND_PRECISION),
                            round(xyz[2], ROUND_PRECISION)
                        )
                        
                        # Create the value by rounding the UV
                        uv_value = (
                            round(uv[0], ROUND_PRECISION),
                            round(uv[1], ROUND_PRECISION)
                        )
                        
                        if xyz_key not in xyz_to_uv_map:
                            xyz_to_uv_map[xyz_key] = uv_value
                            vertices_mapped += 1

    except FileNotFoundError:
        print_c(f"[Error] .obj file not found: {obj_filepath}", "red")
        return {}
    except Exception as e:
        print_c(f"[Error] Failed to parse .obj file: {e}", "red")
        return {}
        
    print_c(f"Parsed {len(v_list)-1} vertices and {len(vt_list)-1} UVs.")
    print_c(f"Mapped {vertices_mapped} unique vertices from {faces_processed} faces.")
    return xyz_to_uv_map

def find_uv_offsets(target_filepath: str, xyz_map: dict):
    """
    Parses the target .preinstanced file and brute-forces UV offsets.
    """
    print_c(f"\nAnalyzing Target File: {target_filepath}", "blue")
    
    if not xyz_map:
        print_c("[Error] XYZ map is empty. Cannot proceed.", "red")
        return

    try:
        with open(target_filepath, "rb") as f:
            file_data = f.read()
    except FileNotFoundError:
        print_c(f"[Error] Target file not found: {target_filepath}", "red")
        return

    data_io = io.BytesIO(file_data)
    
    # Set to store unique successful hits
    # (offset, stride, is_flipped)
    found_offsets = set()
    total_matches = 0
    total_vertices_scanned = 0

    # This is the exact mesh-finding logic from your Blender script
    for mesh_match in MESH_REGEX.finditer(file_data):
        mesh_chunk_off = mesh_match.start()
        data_io.seek(mesh_match.end() + 4)
        
        try:
            FaceDataOff = int.from_bytes(data_io.read(4), byteorder='little')
            MeshDataSize = int.from_bytes(data_io.read(4), byteorder='little')
            MeshChunkStart = data_io.tell()
            data_io.seek(0x14, 1)
            mDataTableCount = int.from_bytes(data_io.read(4), byteorder='big')
            mDataSubCount = int.from_bytes(data_io.read(4), byteorder='big')

            print(f"\nFound Mesh Chunk @ {mesh_chunk_off:08X} (Sub-meshes: {mDataSubCount})")

            for i in range(mDataTableCount):
                data_io.seek(4, 1)
                data_io.read(4)

            mDataSubStart = data_io.tell()

            for i in range(mDataSubCount):
                data_io.seek(mDataSubStart + i * 0xC + 8)
                offset = int.from_bytes(data_io.read(4), byteorder='big')
                data_io.seek(offset + MeshChunkStart + 0xC)
                VertCountDataOff = int.from_bytes(data_io.read(4), byteorder='big') + MeshChunkStart
                data_io.seek(VertCountDataOff)
                VertChunkTotalSize = int.from_bytes(data_io.read(4), byteorder='big')
                VertChunkSize = int.from_bytes(data_io.read(4), byteorder='big')
                
                if VertChunkSize <= 0:
                    print(f"  [MeshPart {i}] Skipping, VertChunkSize <= 0")
                    continue

                VertCount = int(VertChunkTotalSize / VertChunkSize)
                data_io.seek(8, 1)
                VertexStart = int.from_bytes(data_io.read(4), byteorder='big') + FaceDataOff + MeshChunkStart
                
                print(f"  [MeshPart {i}] Verts: {VertCount}, Stride (ChunkSize): {VertChunkSize} bytes (0x{VertChunkSize:X}), Data Start @ {VertexStart:08X}")
                total_vertices_scanned += VertCount

                # --- This is the core analysis loop ---
                for v in range(VertCount):
                    vert_data_start = VertexStart + (v * VertChunkSize)
                    
                    # 1. Read the XYZ (which we assume is at offset 0)
                    if vert_data_start + 12 > len(file_data):
                        break # Not enough data
                    
                    xyz_bytes = file_data[vert_data_start : vert_data_start + 12]
                    x, y, z = struct.unpack('>fff', xyz_bytes)
                    
                    # 2. Find the "Expected UV" from our Rosetta Stone
                    xyz_key = (round(x, ROUND_PRECISION), round(y, ROUND_PRECISION), round(z, ROUND_PRECISION))
                    expected_uv = xyz_map.get(xyz_key)
                    
                    if expected_uv is None:
                        continue # This vertex isn't in our map, skip it
                        
                    # 3. Brute-force! Scan the rest of this vertex chunk
                    # We start *after* the XYZ (12 bytes)
                    # We check every 4 bytes (one float)
                    # We stop when there isn't enough room left for 2 floats (8 bytes)
                    for uv_offset in range(12, VertChunkSize - 7, 4):
                        
                        uv_data_start = vert_data_start + uv_offset
                        
                        potential_uv_bytes = file_data[uv_data_start : uv_data_start + 8]
                        u, v = struct.unpack('>ff', potential_uv_bytes)
                        
                        read_uv = (round(u, ROUND_PRECISION), round(v, ROUND_PRECISION))
                        
                        # --- Check for a match ---
                        if read_uv == expected_uv:
                            hit = (uv_offset, VertChunkSize, False)
                            if hit not in found_offsets:
                                print_c(f"    -> MATCH FOUND! Stride: {VertChunkSize}, Offset: {uv_offset} (0x{uv_offset:X}), Flipped-V: False")
                                found_offsets.add(hit)
                            total_matches += 1
                            break # Found it for this vertex, move to next
                            
                        # --- Check for a match with a flipped V (like your script does) ---
                        read_uv_flipped = (round(u, ROUND_PRECISION), round(1.0 - v, ROUND_PRECISION))
                        if read_uv_flipped == expected_uv:
                            hit = (uv_offset, VertChunkSize, True)
                            if hit not in found_offsets:
                                print_c(f"    -> MATCH FOUND! Stride: {VertChunkSize}, Offset: {uv_offset} (0x{uv_offset:X}), Flipped-V: True")
                                found_offsets.add(hit)
                            total_matches += 1
                            break # Found it
                            
        except Exception as e:
            print_c(f"[Error] Failed during mesh part analysis: {e}", "red")
            continue
            
    # --- Final Report ---
    print_c("\n--- 🏁 Analysis Complete ---", "blue")
    print(f"Scanned {total_vertices_scanned} total vertices.")
    print(f"Found {total_matches} total matching vertex UVs.")
    
    if not found_offsets:
        print_c("No matching UV offsets were found.", "yellow")
        print_c("This could mean:\n  1. The .obj and .preinstanced files are not the same model.\n  2. The XYZ data is not at offset 0.\n  3. The float precision (ROUND_PRECISION) is wrong.", "yellow")
    else:
        print_c(f"Found {len(found_offsets)} unique, successful combinations:", "green")
        for (offset, stride, is_flipped) in sorted(list(found_offsets)):
            print_c(f"  - Stride: {stride} bytes | UV Offset: {offset} bytes (0x{offset:X}) | Flipped-V: {is_flipped}", "green")
        print_c("\nUse the offset/stride/flip combo that appears most often.", "blue")

# --- Main execution ---
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print_c("Usage: python uv_finder.py <correct_reference.obj> <target_game_file.preinstanced>", "red")
        sys.exit(1)
        
    obj_file = sys.argv[1]
    target_file = sys.argv[2]
    
    if not os.path.exists(obj_file):
        print_c(f"Error: File not found: {obj_file}", "red")
        sys.exit(1)
        
    if not os.path.exists(target_file):
        print_c(f"Error: File not found: {target_file}", "red")
        sys.exit(1)

    # 1. Create the ground truth map
    truth_map = parse_obj(obj_file)
    
    # 2. Analyze the target file against the map
    if truth_map:
        find_uv_offsets(target_file, truth_map)