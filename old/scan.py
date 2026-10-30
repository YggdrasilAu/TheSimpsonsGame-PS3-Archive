import os
import html


FILE_PATHS = [

r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\L04_TreeHugger\tree_hugger\Story_mode\igcs\igc_02_folderstream_str\build\PS3\pal_en\assets_rws\tree_hugger\tree_hugger\audio\streams\tree_hugger\Story_mode\igcs\igc_02_folderstream.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\LHub-00_SprHub\spr_hub\zone07_str\build\PS3\pal_en\assets_rws\spr_hub\spr_hub\audio\streams\spr_hub\zone07.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\LHub-00_SprHub\spr_hub\zone03_str\build\PS3\pal_en\assets_rws\spr_hub\spr_hub\audio\streams\spr_hub\zone03.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\L03_HungryHungryHomer\eighty_bites\Zone1_str\build\PS3\pal_en\assets_rws\eighty_bites\eighty_bites\audio\streams\eighty_bites\Zone1.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\L14_BigSuperHappy\bigsuperhappy\story_mode\igcs\igc_13_folderstream_str\build\PS3\pal_en\assets_rws\bigsuperhappy\bigsuperhappy\audio\streams\bigsuperhappy\story_mode\igcs\igc_13_folderstream.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\L04_TreeHugger\tree_hugger\Story_mode\igcs\igc_14_folderstream_str\build\PS3\pal_en\assets_rws\tree_hugger\tree_hugger\audio\streams\tree_hugger\Story_mode\igcs\igc_14_folderstream.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\L05_MobRules\mob_rules\challenge_mode\challenge_mode_design_str\build\PS3\pal_en\assets_rws\mob_rules\mob_rules\audio\streams\mob_rules\challenge_mode\challenge_mode_design.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\L06_EnterTheCheatrix\cheater\challenge_mode\challenge_mode_design_str\build\PS3\pal_en\assets_rws\cheater\cheater\audio\streams\cheater\challenge_mode\challenge_mode_design.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\L11_NeverQuest\neverquest\zone02_str\build\PS3\pal_en\assets_rws\neverquest\neverquest\audio\streams\neverquest\zone02.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\L11_NeverQuest\neverquest\zone04_str\build\PS3\pal_en\assets_rws\neverquest\neverquest\audio\streams\neverquest\zone04.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\LHub-00_SprHub\spr_hub\design\Act_3_folderstream_str\build\PS3\pal_en\assets_rws\spr_hub\spr_hub\audio\streams\spr_hub\design\Act_3_folderstream.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\LHub-00_SprHub\spr_hub\zone02_str\build\PS3\pal_en\assets_rws\spr_hub\spr_hub\audio\streams\spr_hub\zone02.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\L03_HungryHungryHomer\eighty_bites\Zone3_str\build\PS3\pal_en\assets_rws\eighty_bites\eighty_bites\audio\streams\eighty_bites\Zone3.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\LHub-00_SprHub\spr_hub\zone14_str\build\PS3\pal_en\assets_rws\spr_hub\spr_hub\audio\streams\spr_hub\zone14.sbk",
r"A:\RemakeEngine\Main\EngineApps\Games\TheSimpsonsGame-PS3\GameFiles\EU-Full-audio_reorg-isRenamed\L15_Rhymes\rhymes\story_mode\story_mode_design_str\build\PS3\pal_en\assets_rws\rhymes\rhymes\audio\streams\rhymes\story_mode\story_mode_design.sbk",
]
OUTPUT_HTML = "HexDump.html"

def format_line(offset, chunk):
    """Helper to format a single 16-byte chunk into a hex dump line."""
    hex_str = ' '.join(f'{b:02X}' for b in chunk)
    ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
    safe_ascii = html.escape(ascii_str)
    return f"{offset:08X}  {hex_str:<47}  |{safe_ascii}|"

def generate_hexdump(data):
    """Takes binary data and returns a formatted hex dump string with repetition compression."""
    if not data:
        return ""

    lines = []

    # Initialize state with the first chunk
    prev_chunk = data[0:16]
    lines.append(format_line(0, prev_chunk))

    repeat_count = 0
    last_offset = 0

    # Process the rest of the chunks
    for i in range(16, len(data), 16):
        chunk = data[i:i+16]

        if chunk == prev_chunk:
            repeat_count += 1
            last_offset = i
        else:
            if repeat_count == 1:
                # Only 2 identical lines total. Just print the second one normally.
                lines.append(format_line(last_offset, prev_chunk))
            elif repeat_count >= 2:
                # 3 or more identical lines total (48+ bytes). Compress intermediate lines.
                lines.append(f"*\n* ... line repeats {repeat_count - 1} times ...\n*")
                lines.append(format_line(last_offset, prev_chunk))

            # Print the current (different) chunk
            lines.append(format_line(i, chunk))

            # Reset state for the next sequence
            prev_chunk = chunk
            repeat_count = 0

    # Handle any remaining repetitions at the end of the file
    if repeat_count == 1:
        lines.append(format_line(last_offset, prev_chunk))
    elif repeat_count >= 2:
        lines.append(f"*\n* ... line repeats {repeat_count - 1} times ...\n*")
        lines.append(format_line(last_offset, prev_chunk))

    return '\n'.join(lines)

def main():
    html_out = [
        "<section class='bodyy'>",
        "<h1>.smb Files: Hex Dump Analysis</h1>"
    ]

    for path in FILE_PATHS:
        html_out.append("<div class='file-block'>")
        html_out.append(f"<div class='file-path'><strong>File:</strong> {path}</div>")

        try:
            if not os.path.exists(path):
                raise FileNotFoundError("File not found on disk.")

            size = os.path.getsize(path)
            html_out.append(f"<div class='file-size'><strong>Size:</strong> {size} bytes</div>")

            with open(path, 'rb') as f:
                data = f.read()

            dump = generate_hexdump(data)
            html_out.append(f"<pre>{dump}</pre>")

        except Exception as e:
            html_out.append(f"<div class='error'><strong>Error:</strong> {str(e)}</div>")

        html_out.append("</div>")

    html_out.append("</section>")

    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_out))

    print(f"Success! Compressed hex dump generated at: {os.path.abspath(OUTPUT_HTML)}")

if __name__ == "__main__":
    main()