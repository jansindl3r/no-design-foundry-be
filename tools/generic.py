import base64
import defcon
import re
import uharfbuzz as hb

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
from io import BytesIO
from itertools import chain
from fontTools.ttLib import TTFont
from ufo2ft import compileTTF, compileOTF
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.cffLib import PrivateDict
from typing import Dict, Tuple

from ufo2ft.featureWriters.kernFeatureWriter import KernFeatureWriter
from ufo2ft.featureWriters.ast import FeatureFile
from fontTools.feaLib.builder import Builder

from extractor.formats.opentype import (
    extractGlyphOrder,
    extractOpenTypeInfo,
    extractOpenTypeKerning,
    extractOpenTypeGlyphs,
    extractUnicodeVariationSequences
)

MAX_ERR = .2

FAMILY_RELATED_IDS = dict(
    LEGACY_FAMILY=1,
    TRUETYPE_UNIQUE_ID=3,
    FULL_NAME=4,
    POSTSCRIPT_NAME=6,
    PREFERRED_FAMILY=16,
    WWS_FAMILY=21,
)

WINDOWS_ENGLISH_IDS = 3, 1, 0x409
MAC_ROMAN_IDS = 1, 0, 0

def insert_suffix(string, family_name, suffix):
    # check whether family_name is a substring
    start = string.find(family_name)
    if start != -1:
        # insert suffix after the family_name substring
        end = start + len(family_name)
        new_string = string[:end] + suffix + string[end:]
    else:
        # it's not, we just append the suffix at the end
        new_string = string + suffix
    return new_string

def get_current_family_name(table):
    family_name_rec = None
    for plat_id, enc_id, lang_id in (WINDOWS_ENGLISH_IDS, MAC_ROMAN_IDS):
        for name_id in (
            FAMILY_RELATED_IDS["PREFERRED_FAMILY"],
            FAMILY_RELATED_IDS["LEGACY_FAMILY"],
        ):
            family_name_rec = table.getName(
                nameID=name_id,
                platformID=plat_id,
                platEncID=enc_id,
                langID=lang_id,
            )
            if family_name_rec is not None:
                break
        if family_name_rec is not None:
            break
    if not family_name_rec:
        raise ValueError("family name not found; can't add suffix")
    return family_name_rec.toUnicode()

def rename_record(name_record, family_name, suffix):
    string = name_record.toUnicode()
    new_string = insert_suffix(string, family_name, suffix)
    name_record.string = new_string
    return string, new_string


def add_family_suffix(font, suffix):
    table = font["name"]

    family_name = get_current_family_name(table)

    # postcript name can't contain spaces
    ps_family_name = family_name.replace(" ", "")
    ps_suffix = suffix.replace(" ", "")
    for rec in table.names:
        name_id = rec.nameID
        if name_id not in FAMILY_RELATED_IDS.values():
            continue
        if name_id == FAMILY_RELATED_IDS["POSTSCRIPT_NAME"]:
            old, new = rename_record(rec, ps_family_name, ps_suffix)
        elif name_id == FAMILY_RELATED_IDS["TRUETYPE_UNIQUE_ID"]:
            # The Truetype Unique ID rec may contain either the PostScript
            # Name or the Full Name string, so we try both
            if ps_family_name in rec.toUnicode():
                old, new = rename_record(rec, ps_family_name, ps_suffix)
            else:
                old, new = rename_record(rec, family_name, suffix)
        else:
            old, new = rename_record(rec, family_name, suffix)

    return family_name

def rename_name_ttfont(font, suffix) -> None:
    try:
        add_family_suffix(font, f" {suffix}")
    except Exception as e:
        print(e)
        pass

def rename_name_ufo(font, suffix) -> None:
    old_name = font.info.familyName
    new_name =  f"{old_name} {suffix}"

    font.info.openTypeNameRecords.clear()

    font.info.familyName = new_name
    font.info.styleMapFamilyName = new_name

    font.info.openTypeNamePreferredFamilyName = new_name
    font.info.openTypeNameCompatibleFullName = new_name


    # font.info.openTypeNameWWSFamilyName = new_name
    # font.info.openTypeNameWWSSubfamilyName = new_name

    # else:
    #     pass

def inject_features(source, destination):
    for table_name in ("GPOS", "GSUB", "GDEF"):
        if table_name in source:
            destination[table_name].table = source[table_name].table
    # go = [glyph_name for glyph_name in source.getGlyphOrder() if glyph_name in destination.getGlyphOrder()]

def get_glyph(char_string):
    glyph = defcon.objects.glyph.Glyph()
    pen = glyph.getPen()
    char_string.draw(pen)
    pen.endPath()
    return glyph

def get_charstring(glyph):
    cff_pen = T2CharStringPen(None, [], CFF2=True)
    glyph.draw(cff_pen)
    cff_pen.endPath()
    private = PrivateDict()
    return cff_pen.getCharString(private=private)

def export_font(font, flavour="ttf"):
    if isinstance(font, defcon.Font):
        if flavour == "ttf":
            font = compileTTF(font, removeOverlaps=False, flattenComponents=False)
        elif flavour == "otf":
            font = compileOTF(font, removeOverlaps=True)
        else:
            raise Exception("flavour not matched")
    if isinstance(font, TTFont):
        font_bytes = BytesIO()
        font.save(font_bytes)
        return font_bytes
    else:
        raise Exception("not good instance")

def export_fonts(fonts, flavour="ttf"):
    fonts_ = []
    for font in fonts:
        fonts_.append(export_font(font))
    return fonts_

def fonts_to_base64(fonts):
    fonts_ = export_fonts(fonts)
    return [base64.b64encode(font.getvalue()).decode('ascii') for font in fonts_]

def get_components_in_subsetted_text(tt_font, glyph_names):
    if "glyf" in tt_font:
        def get_component_names(glyf, glyph_names, collector=[]):
            components = list(chain(*[glyf[glyph_name].getComponentNames(glyf) for glyph_name in glyph_names]))
            if components:
                collector += components
                return get_component_names(glyf, components, collector)
            else:
                return collector
        glyf = tt_font["glyf"]
        components = []
        cmap = tt_font.getBestCmap()
        keep_glyphs = filter(lambda glyph_name:False if glyph_name is None else True, glyph_names)
        return get_component_names(glyf, list(keep_glyphs))
    else:
        return ()

def get_widths(tt_font, glyph_names):
    widths = {}
    for glyph_name in glyph_names:
        widths[glyph_name] = tt_font["hmtx"][glyph_name][0]
    return widths

def extractFontFromOpenType(
    tt_font,
    destination,
    extract_glyphs=True,
):  
    extractGlyphOrder(tt_font, destination)
    try:
        extractOpenTypeInfo(tt_font, destination)
    except:
        pass
    if extract_glyphs:
        extractOpenTypeGlyphs(tt_font, destination)
    else:
        for glyph_name in destination.glyphOrder:
            destination.newGlyph(glyph_name)        
    extractUnicodeVariationSequences(tt_font, destination)
    kerning, groups = extractOpenTypeKerning(tt_font, destination)
    destination.groups.update(groups)
    destination.kerning.update(kerning)

def extract_to_ufo(tt_font: TTFont, extract_glyphs=True) -> defcon.Font:
    ufo = defcon.Font()
    extractFontFromOpenType(tt_font, ufo, extract_glyphs=extract_glyphs)
    cmap_reversed = {v:k for k,v in tt_font.getBestCmap().items()}
    if not extract_glyphs:
        for glyph_name in tt_font.getGlyphOrder():
            new_glyph = ufo.newGlyph(glyph_name)
            new_glyph.unicode = cmap_reversed.get(glyph_name, None)
    return ufo

def zip_list(font_list):
    pass

def extract_kerning_hb(font_data:bytes, widths:Dict[Tuple[str, str], int], content: str, cmap: dict) -> Dict[Tuple[str, str], int]:
    blob = hb.Blob(font_data)
    face = hb.Face(blob)
    font = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(content)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True})
    positions = buf.glyph_positions
    kerning = {}
    for i, pos in enumerate(positions[:-1]):
        x_advance = pos.x_advance
        key = (cmap.get(ord(content[i])), cmap.get(ord(content[i+1])))
        if None not in key:
            value = x_advance - widths[cmap[ord(content[i])]]
            if value != 0:
                if key not in kerning:
                    kerning[key] = value 
    return kerning

def extract_kerning_kern(tt_font, preview_string, cmap):
    kerning = tt_font["kern"].kernTables[0]
    output = {}
    for i, character in enumerate(preview_string[:-1]):
        left = cmap[ord(character)]
        right = cmap[ord(preview_string[i+1])]
        try:
            output[(left, right)] = kerning[(left, right)]
        except:
            print("extracting kerning exception")
            pass
    return output
    # return {}

def inject_kerning(source: defcon.Font, output_font: TTFont) -> None:
    kerning_writer = KernFeatureWriter(ignoreMarks=True)
    featureFile = FeatureFile()
    kerning_writer.write(source, featureFile)
    builder = Builder(output_font, featureFile)
    builder.build()
    # pass


def extractGlyfGlyph(source, glyph_name):
    return source["glyf"][glyph_name]

def extractCffGlyph(source, glyph_name):
    cff = source["CFF "]
    content = cff.cff[cff.cff.keys()[0]]
    glyph = content.CharStrings[glyph_name]
    output_pen = TTGlyphPen([])
    cu2quPen = Cu2QuPen(other_pen=output_pen, max_err=MAX_ERR)
    glyph.draw(cu2quPen)
    try:
        cu2quPen.endPath()
    except:
        pass
    return output_pen.glyph()

def extractCff2Glyph(source, glyph_name):
    cff2 = source["CFF2"]
    content = cff2.cff[cff2.cff.keys()[0]]
    glyph = content.CharStrings[glyph_name]
    output_pen = TTGlyphPen([])
    cu2quPen = Cu2QuPen(other_pen=output_pen, max_err=MAX_ERR)
    glyph.draw(cu2quPen)
    cu2quPen.endPath()
    return output_pen.glyph()


def createCmap(preview_string_glyph_names, cmap_reversed):
    outtables = []
    subtable = CmapSubtable.newSubtable(4)
    subtable.platformID = 0
    subtable.platEncID = 3
    subtable.language = 0
    subtable.cmap = {cmap_reversed[glyph_name]:glyph_name for glyph_name in preview_string_glyph_names if glyph_name in cmap_reversed}
    outtables.append(subtable)
    return outtables

def get_margins(tt_font):
    os_2 = tt_font["OS/2"]
    try:
        sCapHeight = os_2.sCapHeight
    except AttributeError:
        sCapHeight = os_2.sTypoAscender
    usWinAscent = os_2.usWinAscent
    usWinDescent = os_2.usWinDescent
    sTypoLineGap = os_2.sTypoLineGap
    margin_bottom = -usWinDescent / usWinAscent
    margin_top = sCapHeight / usWinAscent - 1 if sTypoLineGap else 0
    # return {"marginBottom": round(margin_bottom, 3), "marginTop": round(margin_top, 3)}
    return {"marginBottom": 0, "marginTop": round(margin_top, 3)}

def extractTTFontGlyphs(source, output, glyph_names_to_process):
    is_ttf = False
    is_cff = False
    is_cff2 = False
    if "glyf" in source:
        is_ttf = True
    elif "CFF " in source:
        is_cff = True
    elif "CFF2" in source:
        is_cff2 = True
    for glyph_name in glyph_names_to_process:
        if is_ttf:
            glyph = extractGlyfGlyph(source, glyph_name)
        elif is_cff2:
            glyph = extractCff2Glyph(source, glyph_name)
        elif is_cff:
            glyph = extractCffGlyph(source, glyph_name)
        output["glyf"][glyph_name] = glyph
        output["hmtx"][glyph_name] = source["hmtx"][glyph_name]


if __name__ == "__main__":
    from pathlib import Path
    base = Path(__file__).parent
    from fontTools.ttLib import TTFont
    font = TTFont(base.parent.parent / "be_test" / "fonts" / "Futura LT Condensed Extra Bold Oblique.ttf")
    rename_name_ttfont(font, "Rotated")
    font.save("test.ttf")