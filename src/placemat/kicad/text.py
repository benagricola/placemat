"""pcbnew side of a silk text: the PCB_TEXT the writer draws for a Text op, and the box KiCad gives it. The writer adds the text to the
board (write._draw_text); the reader measures an arrangement's label the same way it reads a stamped one (kicad/read.py)."""
from __future__ import annotations

from .quiet import import_pcbnew

pcbnew = import_pcbnew()

from ..values import Box, Face

# The layers KiCad's DRC judges a text's mirroring on (drc_test_provider_text_mirroring.cpp): a text on a back one must
# be mirrored, one on a front one must not be.
_FRONT_TEXT_LAYERS = (pcbnew.F_Cu, pcbnew.F_SilkS, pcbnew.F_Mask, pcbnew.F_Fab)
_BACK_TEXT_LAYERS = (pcbnew.B_Cu, pcbnew.B_SilkS, pcbnew.B_Mask, pcbnew.B_Fab)
_HJUST = {"left": pcbnew.GR_TEXT_H_ALIGN_LEFT, "centre": pcbnew.GR_TEXT_H_ALIGN_CENTER, "right": pcbnew.GR_TEXT_H_ALIGN_RIGHT}
_VJUST = {"top": pcbnew.GR_TEXT_V_ALIGN_TOP, "centre": pcbnew.GR_TEXT_V_ALIGN_CENTER, "bottom": pcbnew.GR_TEXT_V_ALIGN_BOTTOM}


def _nm(v: float) -> int:
    return pcbnew.FromMM(float(v))


def _mirror_for_layer(text, default: bool = False) -> None:
    """Mirror a text as its layer's face asks: on a back layer mirrored, on a front one not, elsewhere `default`."""
    layer = text.GetLayer()
    text.SetMirrored(True if layer in _BACK_TEXT_LAYERS else False if layer in _FRONT_TEXT_LAYERS else default)


def text_item(board, op):
    """The PCB_TEXT for Text op `op`, not yet on the board."""
    t = pcbnew.PCB_TEXT(board)
    t.SetText(op.text)
    t.SetLayer(board.GetLayerID(op.layer) if op.layer else (pcbnew.B_SilkS if op.face is Face.BACK else pcbnew.F_SilkS))
    _mirror_for_layer(t, op.mirrored)
    t.SetTextSize(pcbnew.VECTOR2I(_nm(op.size), _nm(op.size)))
    t.SetTextThickness(_nm(op.thickness))
    t.SetHorizJustify(_HJUST[op.hjust])
    t.SetVertJustify(_VJUST[op.vjust])
    t.SetTextAngleDegrees(op.rotation)
    t.SetIsKnockout(op.knockout)
    t.SetPosition(pcbnew.VECTOR2I(_nm(op.at.x), _nm(op.at.y)))
    if op.side is not None:
        # KiCad's box round the text (descenders, the knockout margin) reaches past the
        # anchor: slide the text so the edge of what it draws (the glyphs, or the
        # knockout frame) facing the item sits exactly at the anchor.
        bb = t.GetEffectiveShape().BBox()
        name = op.side.name
        if name == "NORTH":
            t.Move(pcbnew.VECTOR2I(0, _nm(op.at.y) - bb.GetBottom()))
        elif name == "SOUTH":
            t.Move(pcbnew.VECTOR2I(0, _nm(op.at.y) - bb.GetTop()))
        elif name == "WEST":
            t.Move(pcbnew.VECTOR2I(_nm(op.at.x) - bb.GetRight(), 0))
        else:
            t.Move(pcbnew.VECTOR2I(_nm(op.at.x) - bb.GetLeft(), 0))
    return t


def text_box(board, op) -> Box:
    """The box KiCad gives the text the writer draws for `op`: what kicad/read.py reads a stamped label's region from."""
    bb = text_item(board, op).GetEffectiveShape().BBox()
    mm = pcbnew.ToMM
    return Box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))
