from __future__ import annotations

from pathlib import Path

from videogen.application.ports import UserFacingError
from videogen.domain.hook import HookLayout, HookLayoutError, HookSpec, HookStyle, layout_hook
from videogen.domain.models import MediaInfo
from videogen.infrastructure.fonts import SubtitleFont


def append_hook_ass(path: Path, info: MediaInfo, spec: HookSpec, font: SubtitleFont, style: HookStyle | None = None) -> HookLayout | None:
    try:
        layout = layout_hook(spec, info, font, style)
    except HookLayoutError as error:
        raise UserFacingError(str(error)) from error
    if layout is None:
        return None
    content = path.read_text(encoding="utf-8-sig")
    style_marker = "[Events]"
    appearance = style or HookStyle(schema_version=1)
    text_color = _ass_color(appearance.text_color)
    background_color = _ass_color(appearance.background_color)
    ass_style = ("Style: Hook,{family},{size},&H00000000,&H00000000,&H00000000,&H00FFFFFF,"
             "{bold},{italic},0,0,100,100,0,0,1,0,0,8,0,0,0,1").format(size=layout.font_size, family=font.postscript_name, bold=-1 if font.raw.weight() >= 600 else 0, italic=-1 if font.raw.style().value else 0)
    content = content.replace(style_marker, style_marker, 1)
    # Add Hook to the V4+ Styles section without touching existing subtitle events.
    events_at = content.index(style_marker)
    before, after = content[:events_at], content[events_at:]
    before = before.rstrip() + "\n" + ass_style + "\n\n"
    start = _ass_time(layout.start)
    end = _ass_time(layout.end)
    events = []
    for line in layout.lines:
        if appearance.background_enabled:
            events.append(
                f"Dialogue: 1,{start},{end},Hook,,0,0,0,,{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\1c{background_color}}}"
                + _rounded_rect(line.x, line.y, line.width, line.height, line.radius)
                + "{\\p0}"
            )
        events.append(
            f"Dialogue: 2,{start},{end},Hook,,0,0,0,,{{\\an5\\pos({line.x + line.width / 2:g},{line.y + line.height * 0.5:g})"
            f"\\fs{layout.font_size}\\bord0\\shad0\\1c{text_color}}}{_escape(line.text)}"
        )
    path.write_text(before + after.rstrip() + "\n" + "\n".join(events) + "\n", encoding="utf-8-sig")
    return layout


def _ass_color(color: str) -> str:
    return "&H" + color[5:7] + color[3:5] + color[1:3] + "&"


def _rounded_rect(x: float, y: float, width: float, height: float, radius: float) -> str:
    x0, y0, x1, y1 = (round(x), round(y), round(x + width), round(y + height))
    r = max(0, round(radius))
    # Cubic corners approximated by standard 0.5523 control-point factor.
    c = round(r * 0.5523)
    return (f"m {x0+r} {y0} l {x1-r} {y0} b {x1-r+c} {y0} {x1} {y0+r-c} {x1} {y0+r} "
            f"l {x1} {y1-r} b {x1} {y1-r+c} {x1-r+c} {y1} {x1-r} {y1} "
            f"l {x0+r} {y1} b {x0+r-c} {y1} {x0} {y1-r+c} {x0} {y1-r} "
            f"l {x0} {y0+r} b {x0} {y0+r-c} {x0+r-c} {y0} {x0+r} {y0} c")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def _ass_time(seconds: float) -> str:
    total = max(0, round(seconds * 100))
    hours, rem = divmod(total, 360000)
    minutes, rem = divmod(rem, 6000)
    whole, centiseconds = divmod(rem, 100)
    return f"{hours}:{minutes:02}:{whole:02}.{centiseconds:02}"
