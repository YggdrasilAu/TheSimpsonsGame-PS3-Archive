import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import struct
import io
import os

# ==============================================================================
# 1. Refpack Decompression Logic
# ==============================================================================
class Refpack:
    @staticmethod
    def decompress(data_bytes):
        if not data_bytes:
            return b""

        stream = io.BytesIO(data_bytes)

        # Read Header
        dummy = stream.read(2)
        if len(dummy) < 2:
            # If the stream is too short, just return raw data or empty
            raise ValueError("Stream too short for Refpack header")

        header = (dummy[0] << 8) | dummy[1]

        # Signature check: 0x10FB masked by 0x1FFF
        # 0x52AB is a common error signature when reading aligned offsets incorrectly
        if (header & 0x1FFF) != 0x10FB:
            raise ValueError(f"Invalid Refpack Signature: {hex(header)} (Expected 0x10FB)")

        is_long = (header & 0x8000) != 0
        is_doubled = (header & 0x0100) != 0

        if is_doubled:
            # In some EA games, this means 'double compression', rarely used in STR
            raise ValueError("Double compression (isDoubled) not supported.")

        # Read Uncompressed Size
        if is_long:
            dummy = stream.read(4)
            if len(dummy) < 4: raise ValueError("EOF reading size (Long)")
            uncompressed_size = (dummy[0] << 24) | (dummy[1] << 16) | (dummy[2] << 8) | dummy[3]
        else:
            dummy = stream.read(3)
            if len(dummy) < 3: raise ValueError("EOF reading size (Short)")
            uncompressed_size = (dummy[0] << 16) | (dummy[1] << 8) | dummy[2]

        output = bytearray()

        while True:
            prefix_byte = stream.read(1)
            if not prefix_byte: break
            prefix = prefix_byte[0]

            plain_size = 0
            copy_size = 0
            copy_offset = 0
            stop = False

            if prefix < 0x80:
                # 0x00 - 0x7F: 2-byte sequence
                dummy = stream.read(1)
                if len(dummy) < 1: break
                d0 = dummy[0]

                plain_size = prefix & 0x03
                copy_size = ((prefix & 0x1C) >> 2) + 3
                copy_offset = ((prefix & 0x60) << 3) | d0
                copy_offset += 1

            elif prefix < 0xC0:
                # 0x80 - 0xBF: 3-byte sequence
                dummy = stream.read(2)
                if len(dummy) < 2: break
                d0, d1 = dummy[0], dummy[1]

                plain_size = (d0 >> 6) & 0x03
                copy_size = (prefix & 0x3F) + 4
                copy_offset = ((d0 & 0x3F) << 8) | d1
                copy_offset += 1

            elif prefix < 0xE0:
                # 0xC0 - 0xDF: 4-byte sequence
                dummy = stream.read(3)
                if len(dummy) < 3: break
                d0, d1, d2 = dummy[0], dummy[1], dummy[2]

                plain_size = prefix & 0x03
                copy_size = ((prefix & 0x0C) << 6) | d2
                copy_size += 5
                copy_offset = (((prefix & 0x10) << 4) | d0) << 8 | d1
                copy_offset += 1

            elif prefix < 0xFC:
                # 0xE0 - 0xFB: Plain data only
                plain_size = ((prefix & 0x1F) + 1) * 4

            else:
                # 0xFC - 0xFF: Stop / Plain data (0-3 bytes)
                plain_size = prefix & 0x03
                stop = True

            # Copy Plain Data
            if plain_size > 0:
                data = stream.read(plain_size)
                output.extend(data)

            # Copy from History
            if copy_size > 0:
                current_len = len(output)
                start_index = current_len - copy_offset
                if start_index < 0: start_index = 0

                for i in range(copy_size):
                    if start_index + i < len(output):
                        val = output[start_index + i]
                        output.append(val)
                    else:
                        output.append(0)

            if stop:
                break

        return bytes(output)

# ==============================================================================
# 2. STR File Parsing Logic (Corrected Offsets)
# ==============================================================================

class BinaryReader:
    def __init__(self, data):
        self.stream = io.BytesIO(data)
        self.data = data

    def seek(self, offset):
        self.stream.seek(offset)

    def pos(self):
        return self.stream.tell()

    def read_bytes(self, n):
        return self.stream.read(n)

    def read_u8(self):
        b = self.stream.read(1)
        return struct.unpack('>B', b)[0] if len(b) == 1 else 0

    def read_u16(self):
        b = self.stream.read(2)
        return struct.unpack('>H', b)[0] if len(b) == 2 else 0

    def read_i32(self):
        b = self.stream.read(4)
        return struct.unpack('>i', b)[0] if len(b) == 4 else 0

    def read_u32(self):
        b = self.stream.read(4)
        return struct.unpack('>I', b)[0] if len(b) == 4 else 0

    def read_string_at(self, offset_base, relative_ptr):
        old_pos = self.stream.tell()
        target = offset_base + relative_ptr
        if target >= len(self.data) or target < 0:
            return "<Invalid Pointer>"
        self.stream.seek(target)
        chars = []
        while True:
            b = self.stream.read(1)
            if not b or b == b'\x00': break
            chars.append(b.decode('latin-1'))
        self.stream.seek(old_pos)
        return "".join(chars)

    def read_rw_string(self):
        length = self.read_i32()
        if length < 0 or length > 5000: return "<ReadError>"
        s_bytes = self.stream.read(length)
        align_pad = (4 - (length % 4)) % 4
        self.stream.read(align_pad)
        try:
            return s_bytes.decode('utf-8').rstrip('\x00')
        except:
            return s_bytes.decode('latin-1').rstrip('\x00')

    def align(self, alignment):
        pos = self.stream.tell()
        mod = pos % alignment
        if mod != 0:
            self.stream.read(alignment - mod)

class STRSection:
    def __init__(self):
        self.chunks = []
        self.info = {}

class STRFile:
    def __init__(self, filepath):
        self.filepath = filepath
        self.header = {}
        self.stream_info = {}
        self.sections = []

        with open(filepath, 'rb') as f:
            self.raw_data = f.read()

        self.reader = BinaryReader(self.raw_data)
        self.parse()

    def parse(self):
        r = self.reader

        # --- Header ---
        r.seek(0)
        magic = r.read_bytes(4)
        if magic != b'SToc':
            raise ValueError("Invalid File Signature (Expected SToc)")

        self.header['Magic'] = magic.decode()
        self.header['Version'] = r.read_i32()
        self.header['nSections'] = r.read_u8()
        self.header['PlatformID'] = r.read_u8()
        r.read_bytes(2)
        self.header['pStreamFile'] = r.read_i32()
        self.header['pSectionArr'] = r.read_i32()

        # --- Stream Info ---
        if self.header['pStreamFile'] != 0:
            r.seek(self.header['pStreamFile'])
            self.stream_info['GUID'] = r.read_u32()

            name_offset = r.read_i32()
            # Usually relative to pStreamFile base
            fname_addr = self.header['pStreamFile'] + name_offset
            self.stream_info['FileName'] = r.read_string_at(0, fname_addr)

            self.stream_info['nParents'] = r.read_u8()
            self.stream_info['nForceLoad'] = r.read_u8()
            self.stream_info['nSections'] = r.read_u8()
            self.stream_info['Flags'] = r.read_u8()
            r.read_i32()
            self.stream_info['pRelatives'] = r.read_i32()
            self.stream_info['pSectionInfo'] = r.read_i32()

        # --- Section Descriptors ---
        section_defs = []
        if self.header['nSections'] > 0 and self.header['pSectionArr'] > 0:
            r.seek(self.header['pSectionArr'])
            for _ in range(self.header['nSections']):
                s = {}
                s['MemPolicyID'] = r.read_u32()
                s['CompressorID'] = r.read_u32()
                s['DataSize'] = r.read_i32()
                s['AllocSize'] = r.read_i32()
                s['ReadSize'] = r.read_i32()
                s['ReadOffset'] = r.read_i32() # Likely ignored by game
                section_defs.append(s)

        # --- Calculate Data Start Position ---
        # The game engine and BMS script ignore 'ReadOffset' and assume
        # data starts at the next 0x800 boundary after the headers.

        # Calculate end of section array
        # pSectionArr (Start) + (Count * SizeOf(SectionDesc))
        headers_end = self.header['pSectionArr'] + (self.header['nSections'] * 24)

        # Align to 0x800 (2048)
        data_cursor = (headers_end + (0x800 - 1)) & -0x800

        # --- Parse Section Data ---
        r.seek(data_cursor) # Move to calculated start

        for i, s_def in enumerate(section_defs):
            section_obj = STRSection()
            section_obj.info = s_def

            # Read sequentially from the calculated cursor
            # (Ignoring s_def['ReadOffset'] which might be bogus)
            current_read_pos = r.pos()
            raw_section_data = r.read_bytes(s_def['ReadSize'])

            # Update info for debugging
            section_obj.info['ActualOffset'] = hex(current_read_pos)

            # Handle Compression
            if s_def['CompressorID'] == 0xB9F0B9EC: # Refpack
                try:
                    section_data = Refpack.decompress(raw_section_data)
                    section_obj.info['Compression'] = 'Refpack'
                except Exception as e:
                    # Fallback to raw data on error so user can still see hex
                    section_data = raw_section_data
                    section_obj.info['Compression'] = 'Refpack (Failed)'
                    section_obj.info['Error'] = str(e)
            else:
                section_obj.info['Compression'] = 'None'
                section_data = raw_section_data

            # --- Parse Chunks inside Section ---
            chunk_reader = BinaryReader(section_data)

            while chunk_reader.pos() < len(section_data):
                chunk_start = chunk_reader.pos()

                # Minimum chunk size check
                if len(section_data) - chunk_start < 4:
                    break

                chunk_id = chunk_reader.read_u16()
                if chunk_id == 0:
                    break

                chunk_info = {'ID': chunk_id, 'Start': chunk_start, 'Data': None, 'Type': 'Unknown'}

                try:
                    if chunk_id == 0x1607: # Embedded Asset
                        chunk_info['Type'] = 'Embedded Asset'
                        chunk_reader.read_bytes(2)
                        file_size = struct.unpack('<i', chunk_reader.read_bytes(4))[0]
                        chunk_reader.read_bytes(4)

                        asset_start = chunk_reader.pos()
                        header_size = chunk_reader.read_i32()

                        if header_size > 0:
                            chunk_info['FileName'] = chunk_reader.read_rw_string()
                            chunk_reader.read_bytes(16)
                            chunk_info['ResourceType'] = chunk_reader.read_rw_string()
                            chunk_info['FullPath'] = chunk_reader.read_rw_string()

                        chunk_reader.seek(asset_start)
                        chunk_info['Data'] = chunk_reader.read_bytes(file_size)
                        chunk_reader.seek(asset_start + file_size)

                    elif chunk_id == 0x2207: # SimGroup
                        chunk_info['Type'] = 'SimGroup'
                        chunk_reader.read_bytes(2)
                        file_size = struct.unpack('<i', chunk_reader.read_bytes(4))[0]
                        chunk_reader.read_bytes(4)
                        chunk_info['Data'] = chunk_reader.read_bytes(file_size)

                    elif chunk_id == 0x10FB:
                        # This chunk ID is ITSELF the Refpack signature?
                        # Sometimes chunks are just compressed blocks.
                        chunk_info['Type'] = 'Refpack Block'
                        # We can't easily skip without a size header, which pure Refpack doesn't always have.
                        # Assuming it consumes the rest of the section or has a specific structure.
                        # For safety, we stop parsing this section to avoid crash.
                        chunk_info['Data'] = section_data[chunk_start:]
                        chunk_reader.seek(len(section_data))

                    else:
                        chunk_info['Type'] = f"Unknown (0x{chunk_id:X})"
                        # If we don't know the size, we can't advance.
                        # Stop parsing this section.
                        chunk_reader.seek(len(section_data))

                except Exception as e:
                    chunk_info['Type'] += " (Parse Error)"
                    chunk_info['Error'] = str(e)
                    chunk_reader.seek(len(section_data))

                section_obj.chunks.append(chunk_info)

            self.sections.append(section_obj)

            # Align cursor for next section?
            # C# script logic implies sequential read of 'readSize'.
            # If the file has padding between sections, we might need to handle it.
            # But normally STR files pack sections tightly or align them.
            # BMS script does: math BASE_OFF + XSIZE.
            # So sequential is correct.

            # Note: If the file forces 0x800 alignment for EVERY section,
            # we might need to re-align here.
            # C# code: "reader.BaseStream.Position += (section.readSize - section.dataSize);"
            # for uncompressed sections. This implies padding handling?
            # For now, strict sequential read of 'readSize' (which is the compressed/stored size)
            # is the most robust method based on the BMS script.

# ==============================================================================
# 3. GUI Implementation
# ==============================================================================

class STRViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Simpsons Game .STR Viewer (v3 Fixed)")
        self.root.geometry("1000x700")

        self.paned = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        self.tree_frame = ttk.Frame(self.paned)
        self.tree = ttk.Treeview(self.tree_frame)
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        self.scrollbar = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=self.scrollbar.set)

        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.paned.add(self.tree_frame, weight=1)

        self.detail_frame = ttk.Frame(self.paned)
        self.paned.add(self.detail_frame, weight=2)

        self.lbl_info = ttk.Label(self.detail_frame, text="Select an item to view details.", font=("Consolas", 10))
        self.lbl_info.pack(pady=5, anchor="w")

        self.btn_action = ttk.Button(self.detail_frame, text="Extract Asset", command=self.extract_asset)
        self.btn_action.pack(pady=5, anchor="w")
        self.btn_action.pack_forget()

        self.txt_content = tk.Text(self.detail_frame, font=("Consolas", 10), wrap=tk.NONE)
        self.txt_content.pack(fill=tk.BOTH, expand=True)

        menubar = tk.Menu(root)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Open .STR File", command=self.open_file)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=root.quit)
        menubar.add_cascade(label="File", menu=filemenu)
        root.config(menu=menubar)

        self.current_file = None
        self.selected_data = None
        self.selected_filename = "export.dat"

    def open_file(self):
        fname = filedialog.askopenfilename(filetypes=[("STR Files", "*.str"), ("All Files", "*.*")])
        if not fname: return

        try:
            self.current_file = STRFile(fname)
            self.populate_tree()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file:\n{e}")
            import traceback
            traceback.print_exc()

    def populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        f = self.current_file

        root_id = self.tree.insert("", "end", text=os.path.basename(f.filepath), open=True)

        h_id = self.tree.insert(root_id, "end", text="Header", open=True)
        self.tree.insert(h_id, "end", text=f"Version: {f.header.get('Version', '?')}")
        self.tree.insert(h_id, "end", text=f"Sections: {f.header.get('nSections', '?')}")

        if f.stream_info:
            s_id = self.tree.insert(root_id, "end", text="Stream Info", open=True)
            self.tree.insert(s_id, "end", text=f"FileName: {f.stream_info.get('FileName', 'Unknown')}")
            self.tree.insert(s_id, "end", text=f"GUID: {hex(f.stream_info.get('GUID', 0))}")

        for i, section in enumerate(f.sections):
            comp_status = section.info.get('Compression', 'Unknown')
            sec_name = f"Section {i} ({comp_status})"

            sec_id = self.tree.insert(root_id, "end", text=sec_name, open=True)

            if 'Error' in section.info:
                self.tree.insert(sec_id, "end", text=f"Error: {section.info['Error']}")

            if 'ActualOffset' in section.info:
                 self.tree.insert(sec_id, "end", text=f"Offset: {section.info['ActualOffset']}")

            for j, chunk in enumerate(section.chunks):
                c_name = f"[{chunk['Type']}]"
                if 'FileName' in chunk:
                    c_name += f" {chunk['FileName']}"
                if 'ResourceType' in chunk:
                    c_name += f" ({chunk['ResourceType']})"

                cid = self.tree.insert(sec_id, "end", text=c_name)
                self.tree.item(cid, tags=(f"sec_{i}_chunk_{j}",))

                chunk['_ref_sec'] = i
                chunk['_ref_idx'] = j

    def on_select(self, event):
        self.btn_action.pack_forget()
        self.txt_content.delete(1.0, tk.END)
        self.selected_data = None

        selected_item = self.tree.selection()
        if not selected_item: return

        item_text = self.tree.item(selected_item, "text")
        tags = self.tree.item(selected_item, "tags")

        if tags and tags[0].startswith("sec_"):
            parts = tags[0].split('_')
            sec_idx = int(parts[1])
            chunk_idx = int(parts[3])

            chunk = self.current_file.sections[sec_idx].chunks[chunk_idx]
            self.show_chunk_details(chunk)
        else:
            self.txt_content.insert(tk.END, f"Info: {item_text}")

    def show_chunk_details(self, chunk):
        info_str = f"Type: {chunk['Type']}\n"
        if 'FileName' in chunk:
            info_str += f"File: {chunk['FileName']}\n"
            self.selected_filename = chunk['FileName']
        else:
            self.selected_filename = "exported_chunk.dat"

        if 'ResourceType' in chunk:
             info_str += f"Resource: {chunk['ResourceType']}\n"

        self.lbl_info.config(text=info_str)

        if chunk.get('Data'):
            self.selected_data = chunk['Data']
            self.btn_action.config(text=f"Extract {len(chunk['Data'])} bytes")
            self.btn_action.pack(pady=5, anchor="w")
            self.display_hex(chunk['Data'], limit=512)
        else:
            self.txt_content.insert(tk.END, "[No Data Available or Parsed]")

    def display_hex(self, data, limit=1024):
        self.txt_content.delete(1.0, tk.END)

        header = f"{'Offset':<8}  {'00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F':<48}  ASCII\n"
        self.txt_content.insert(tk.END, header)
        self.txt_content.insert(tk.END, "-"*75 + "\n")

        preview_len = min(len(data), limit)

        for i in range(0, preview_len, 16):
            chunk = data[i:i+16]
            hex_str = " ".join(f"{b:02X}" for b in chunk)
            ascii_str = "".join((chr(b) if 32 <= b < 127 else ".") for b in chunk)

            line = f"{i:08X}  {hex_str:<47}  {ascii_str}\n"
            self.txt_content.insert(tk.END, line)

        if len(data) > limit:
            self.txt_content.insert(tk.END, f"\n... (Total size {len(data)} bytes, preview truncated) ...")

    def extract_asset(self):
        if not self.selected_data: return

        path = filedialog.asksaveasfilename(initialfile=self.selected_filename)
        if path:
            try:
                with open(path, 'wb') as f:
                    f.write(self.selected_data)
                messagebox.showinfo("Success", f"Saved to {path}")
            except Exception as e:
                messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    root = tk.Tk()
    app = STRViewerApp(root)
    root.mainloop()