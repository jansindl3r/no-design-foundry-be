from fontTools.ttLib import TTFont
from io import BytesIO
from tools.generic import (
    get_components_in_subsetted_text,
    fonts_to_base64,
    extract_kerning_hb,
    extract_kerning_kern,
    get_widths,
    get_margins,
    rename_name_ttfont,
    rename_name_ufo,
)
from defcon import Font
from datetime import datetime
from rasterizer.rasterizer import rasterize
from rotorizer.rotorizer import rotorize
from pathlib import Path
from flask import Flask
from flask_cors import CORS, cross_origin
from flask import Flask, request, jsonify, abort
from gc import collect

base = Path(__file__).parent

app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

origins = ["http://localhost:3000", "*"]

suffix_name_map = {
    "rotorizer": ["Rotorized Underlay", "Rotorized Overlay"],
    "rasterizer": ["Rasterized", "Rasterized"],
}

@app.route("/filters/<filter_identifier>", methods=["POST"])
@cross_origin()
def filter_preview(filter_identifier):
    if filter_identifier not in ["rasterizer", "rotorizer"]:
        raise abort(404, description="Filter not found")

    font_file = request.files.get('font_file').read()
    preview_string = request.form.get('preview_string')
    resolution = int(request.form.get('resolution', 30))
    depth = int(request.form.get('depth', 200))

    # raise HTTPException(status_code=404, detail="Item not found")
    start = datetime.now()
    missing_glyphs = []
    binary_font = BytesIO(font_file)
    tt_font = TTFont(binary_font, lazy=True)
    cmap = tt_font.getBestCmap()
    glyph_names_to_process = [cmap.get(ord(char), None) for char in set(preview_string)]

    glyph_names_to_process = [
        glyph_name for glyph_name in glyph_names_to_process if glyph_name != None
    ]

    missing_glyphs = [
        character
        for character in preview_string
        if cmap.get(ord(character), None) == None
    ]

    components = get_components_in_subsetted_text(tt_font, glyph_names_to_process)
    glyph_names_to_process.extend(components)
    cmap_reversed = {v: k for k, v in cmap.items() if v in glyph_names_to_process}

    ufo = Font()
    ufo.info.unitsPerEm = tt_font["head"].unitsPerEm
    ufo.info.familyName = tt_font["name"].getBestFamilyName() + " Rotorized"
    ufo.info.styleName = tt_font["name"].getBestSubFamilyName()
    for glyph_name in glyph_names_to_process:
        new_glyph = ufo.newGlyph(glyph_name)
        new_glyph.unicode = cmap_reversed.get(glyph_name, None)

    if "kern" in tt_font:
        ufo.kerning.update(extract_kerning_kern(tt_font, preview_string, cmap))

    if filter_identifier == "rasterizer":
        widths = get_widths(tt_font, glyph_names_to_process)
        ufo.kerning.update(extract_kerning_hb(font_file, widths, preview_string, cmap))
        output = [
            rasterize(
                ufo=ufo,
                tt_font=tt_font,
                binary_font=binary_font,
                glyph_names_to_process=glyph_names_to_process,
                resolution=resolution,
            )
        ]

    elif filter_identifier == "rotorizer":
        output = rotorize(
            ufo=ufo,
            tt_font=tt_font,
            depth=depth,
            glyph_names_to_process=glyph_names_to_process,
            cmap_reversed=cmap_reversed,
            is_cff = tt_font.sfntVersion == "OTTO"
        )

    end = datetime.now()
    total = (end - start).total_seconds()

    response = fonts_to_base64(output)
    warnings = []
    if missing_glyphs:
        warnings.append(
            f'Your font is missing these characters: {", ".join(missing_glyphs)}'
        )
    collect()
    return jsonify({
        "fonts": response,
        "warnings": warnings,
        "margins": get_margins(tt_font),
        "response_time": total,
        "preview_string": "".join([char for char in preview_string if char not in missing_glyphs])
    }), 200
    
ranges = [
    (32, 126),
]
# ranges = [
#     (32, 127),
#     (128, 255),
#     (256, 383),
#     (384, 591),
#     (7680, 7935),
# ]

def is_in_ranges(code_point):
    for start, end in ranges:
        if start <= code_point <= end:
            return True
    return False

@app.route("/filters/<filter_identifier>/get", methods=["POST"])
@cross_origin()
def filter_download(filter_identifier):  
    if filter_identifier not in ["rasterizer", "rotorizer"]:
        raise abort(404, description="Filter not found")

    font_file = request.files.get('font_file').read()
    depth = int(request.form.get('depth', 200))
    resolution = int(request.form.get('resolution', 30))

    binary_font = BytesIO(font_file)
    tt_font = TTFont(binary_font)
    # glyph_names_to_process = tt_font.getGlyphOrder()
    glyph_names_to_process = []
    cmap_reversed = {v:k for k,v in tt_font.getBestCmap().items()}
    for glyph_name, unicode_value in cmap_reversed.items():
        if is_in_ranges(unicode_value):
            glyph_names_to_process.append(glyph_name)
    components = get_components_in_subsetted_text(tt_font, glyph_names_to_process)
    glyph_names_to_process.extend(components)

    ufo = Font()
    ufo.info.unitsPerEm = tt_font["head"].unitsPerEm
    ufo.info.familyName = tt_font["name"].getBestFamilyName() + " Rotorized"
    ufo.info.styleName = tt_font["name"].getBestSubFamilyName()

    for glyph_name in glyph_names_to_process:
        new_glyph = ufo.newGlyph(glyph_name)
        new_glyph.unicode = cmap_reversed.get(glyph_name, None)

    if filter_identifier == "rasterizer":
        output = [rasterize(
                ufo=ufo,
                tt_font=tt_font,
                binary_font=binary_font,
                glyph_names_to_process=glyph_names_to_process,
                resolution=resolution)]
    elif filter_identifier == "rotorizer":
        output = rotorize(
            ufo=ufo,
            glyph_names_to_process=glyph_names_to_process,
            cmap_reversed=cmap_reversed,
            tt_font=tt_font,
            depth=depth,
        )
    

    for f, font in enumerate(output):
        if isinstance(font, Font):
            rename_name_ufo(font, suffix_name_map[filter_identifier][f])
        else:
            rename_name_ttfont(font, suffix_name_map[filter_identifier][f])

    response = fonts_to_base64(output)
    collect()
    return jsonify({
        "fonts": response
    }), 200



if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
