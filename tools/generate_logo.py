#!/usr/bin/env python3
"""Generate the Nexus ZKT Integration logo assets.

The mark is the Nexus monogram: an "N" drawn as one continuous rounded
ribbon, a left stem that turns into a hook at its foot, a diagonal, and a
right stem that turns into a hook at its head. The two hooks are 180-degree
rotations of each other, so the mark reads the same upside down.

It is the same ribbon as every other Nexus app, painted teal to blue. One
publisher, one shape; the colour is what tells the apps apart in a list.

The wordmark is set in Poppins and converted to outlines with fontTools, so
the SVG lockups carry no font dependency. Poppins is licensed under the SIL
Open Font License, and outlines embedded in a logo are a permitted use. Fetch
it once before running this:

    mkdir -p /tmp/fonts && cd /tmp/fonts
    for f in Poppins-Bold.ttf Poppins-Medium.ttf; do
      gh api repos/google/fonts/contents/ofl/poppins/$f --jq .content | base64 -d > $f
    done

then, from the repository root:

    python3 tools/generate_logo.py

Without the font the mark, the tiles and every PNG are still written; only
the wordmark, the lockup and the social preview card are skipped.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "logos"
PUBLIC = ROOT / "nexus_zkt_integration" / "public" / "images"
NAME = "Nexus ZKT Integration"

# --- Mark geometry (512 x 512 canvas) ---------------------------------------

SIZE = 512
STROKE = 52.0  # ribbon weight
X_L, X_R = 127.0, 386.0  # stem centrelines
Y_TOP, Y_BOT = 124.0, 389.0  # stem extents
HOOK_R = 52.0  # a counter exactly one stroke wide, as in the Nexus mark
HOOK_TAIL = 20.0  # straight run after the turn

# --- Colour ------------------------------------------------------------------

TEAL = "#0EA5A4"  # where this app's gradient starts
BLUE = "#2B7FFF"  # shared with every Nexus mark
NAVY = "#101828"  # "NEXUS"
SLATE = "#2D3350"  # "ZKT"
RULE = "#5EC4C8"  # the dashes flanking "ZKT": a tint of TEAL
TILE = "#0E1220"  # app-icon ground, shared with Nexus Theme
MIST = "#9AA4BF"  # quiet text on the dark card

# --- Type --------------------------------------------------------------------

FONT_DIRS = [Path("/tmp/fonts"), Path(__file__).resolve().parent / "fonts"]
FONT_BOLD = "Poppins-Bold.ttf"
FONT_MEDIUM = "Poppins-Medium.ttf"


def _find_font(name: str) -> Path | None:
	for d in FONT_DIRS:
		p = d / name
		if p.is_file():
			return p
	return None


def _rgb(hex_colour: str) -> tuple[int, int, int]:
	return tuple(int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))


# --- The ribbon ----------------------------------------------------------------


def mark_path() -> str:
	"""The monogram as one SVG path, traced foot-hook to head-hook."""
	foot_tip_x = X_L + 2 * HOOK_R
	foot_y = Y_BOT - HOOK_R
	head_tip_x = X_R - 2 * HOOK_R
	head_y = Y_TOP + HOOK_R
	return (
		f"M{foot_tip_x:.2f} {foot_y - HOOK_TAIL:.2f}"
		f"L{foot_tip_x:.2f} {foot_y:.2f}"
		f"A{HOOK_R} {HOOK_R} 0 0 1 {X_L:.2f} {foot_y:.2f}"
		f"L{X_L:.2f} {Y_TOP:.2f}"
		f"L{X_R:.2f} {Y_BOT:.2f}"
		f"L{X_R:.2f} {head_y:.2f}"
		f"A{HOOK_R} {HOOK_R} 0 0 0 {head_tip_x:.2f} {head_y:.2f}"
		f"L{head_tip_x:.2f} {head_y + HOOK_TAIL:.2f}"
	)


def mark_bbox() -> tuple[float, float, float, float]:
	h = STROKE / 2
	return (X_L - h, Y_TOP - h, X_R + h, Y_BOT + h)


def _grad(gid: str) -> str:
	x0, y0, x1, y1 = mark_bbox()
	return (
		f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" '
		f'x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}">'
		f'<stop offset="0" stop-color="{TEAL}"/>'
		f'<stop offset="1" stop-color="{BLUE}"/>'
		"</linearGradient>"
	)


def _stroked(paint: str, gid: str | None = None, indent: str = "  ") -> str:
	defs = f"{indent}<defs>{_grad(gid)}</defs>\n" if gid else ""
	return (
		f'{defs}{indent}<path d="{mark_path()}" fill="none" stroke="{paint}" '
		f'stroke-width="{STROKE:g}" stroke-linecap="round" stroke-linejoin="round"/>'
	)


def _open(width: float, height: float) -> str:
	return (
		f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
		f'width="{width:.0f}" height="{height:.0f}" role="img" aria-label="{NAME}">\n'
		f"  <title>{NAME}</title>\n"
	)


def svg_mark() -> str:
	return _open(SIZE, SIZE) + f"{_stroked('url(#nz)', 'nz')}\n</svg>\n"


def svg_mono(colour: str = NAVY) -> str:
	return _open(SIZE, SIZE) + f"{_stroked(colour)}\n</svg>\n"


def svg_tile() -> str:
	inset = 0.74
	off = SIZE / 2 * (1 - inset)
	return (
		_open(SIZE, SIZE)
		+ f"  <defs>{_grad('nzt')}</defs>\n"
		+ f'  <rect width="{SIZE}" height="{SIZE}" rx="112" fill="{TILE}"/>\n'
		+ f'  <g transform="translate({off:.2f} {off:.2f}) scale({inset})">\n'
		+ f"  {_stroked('url(#nzt)', indent='  ')}\n"
		+ "  </g>\n</svg>\n"
	)


# --- Text to outlines ----------------------------------------------------------


class Text:
	"""Glyph outlines for one string, laid out with fixed letterspacing."""

	def __init__(self, font_path: Path, text: str, size: float, tracking: float):
		from fontTools.pens.svgPathPen import SVGPathPen
		from fontTools.ttLib import TTFont

		font = TTFont(str(font_path))
		upem = font["head"].unitsPerEm
		cmap = font.getBestCmap()
		gs = font.getGlyphSet()
		hmtx = font["hmtx"]

		self.scale = size / upem
		self.glyphs: list[tuple[str, float]] = []

		x = 0.0
		for ch in text:
			gname = cmap.get(ord(ch))
			if gname is None:
				x += size * 0.4 + tracking
				continue
			pen = SVGPathPen(gs)
			gs[gname].draw(pen)
			d = pen.getCommands()
			if d:
				self.glyphs.append((d, x))
			x += hmtx[gname][0] * self.scale + tracking
		self.width = x - tracking if text else 0.0

	def svg(self, x: float, baseline: float, fill: str, indent: str = "  ") -> str:
		return "\n".join(
			f'{indent}<path transform="translate({x + dx:.2f} {baseline:.2f}) '
			f'scale({self.scale:.6f} {-self.scale:.6f})" fill="{fill}" d="{d}"/>'
			for d, dx in self.glyphs
		)


# --- Lockups -------------------------------------------------------------------

WORD_SIZE = 118.0
WORD_TRACK = 12.0
SUB_SIZE = 40.0
SUB_TRACK = 20.0


def svg_lockup() -> str | None:
	"""Stacked lockup: mark over NEXUS over a ruled ZKT."""
	fb, fm = _find_font(FONT_BOLD), _find_font(FONT_MEDIUM)
	if not (fb and fm):
		return None

	word = Text(fb, "NEXUS", WORD_SIZE, WORD_TRACK)
	sub = Text(fm, "ZKT", SUB_SIZE, SUB_TRACK)

	x0, y0, x1, y1 = mark_bbox()
	mark_w, mark_h = x1 - x0, y1 - y0
	gap_mark, gap_word = 62.0, 42.0
	rule_gap, rule_len = 26.0, 54.0

	content_w = max(mark_w, word.width, sub.width + 2 * (rule_gap + rule_len))
	pad = 56.0
	W = content_w + 2 * pad
	cx = W / 2

	# Cap height carries the vertical rhythm; Poppins caps sit at ~0.70 em.
	cap_w, cap_s = WORD_SIZE * 0.70, SUB_SIZE * 0.70
	y_mark = pad
	y_word_base = y_mark + mark_h + gap_mark + cap_w
	y_sub_base = y_word_base + gap_word + cap_s
	H = y_sub_base + pad

	sub_x = cx - sub.width / 2
	rule_y = y_sub_base - cap_s / 2

	return (
		"\n".join(
			[
				_open(W, H).rstrip("\n"),
				f"  <defs>{_grad('nzl')}</defs>",
				f'  <g transform="translate({cx - mark_w / 2 - x0:.2f} {y_mark - y0:.2f})">',
				f"  {_stroked('url(#nzl)', indent='  ')}",
				"  </g>",
				word.svg(cx - word.width / 2, y_word_base, NAVY),
				sub.svg(sub_x, y_sub_base, SLATE),
				f'  <rect x="{sub_x - rule_gap - rule_len:.2f}" y="{rule_y - 1.6:.2f}" '
				f'width="{rule_len:.2f}" height="3.2" rx="1.6" fill="{RULE}"/>',
				f'  <rect x="{sub_x + sub.width + rule_gap:.2f}" y="{rule_y - 1.6:.2f}" '
				f'width="{rule_len:.2f}" height="3.2" rx="1.6" fill="{RULE}"/>',
				"</svg>",
			]
		)
		+ "\n"
	)


def svg_wordmark() -> str | None:
	"""Horizontal lockup: mark beside NEXUS, and ZKT beneath it."""
	fb, fm = _find_font(FONT_BOLD), _find_font(FONT_MEDIUM)
	if not (fb and fm):
		return None

	size = 96.0
	word = Text(fb, "NEXUS", size, 9.0)
	# Justify the second line to the first: solve for the letterspacing that
	# makes ZKT INTEGRATION exactly as wide as NEXUS. Two lines of different
	# lengths read as a mistake at this size.
	label = "ZKT INTEGRATION"
	bare = Text(fm, label, 30.0, 0.0)
	track = max(2.0, (word.width - bare.width) / (len(label) - 1))
	sub = Text(fm, label, 30.0, track)
	x0, y0, x1, y1 = mark_bbox()
	mark_w, mark_h = x1 - x0, y1 - y0

	target_h = 132.0
	s = target_h / mark_h
	gap, pad = 40.0, 26.0
	text_x = pad + mark_w * s + gap
	W = text_x + max(word.width, sub.width) + pad
	H = pad * 2 + target_h
	cap_w, cap_s = size * 0.70, 30.0 * 0.70
	block = cap_w + 20.0 + cap_s  # NEXUS, a gap, ZKT INTEGRATION
	top = pad + (target_h - block) / 2

	return (
		_open(W, H)
		+ f"  <defs>{_grad('nzw')}</defs>\n"
		+ f'  <g transform="translate({pad - x0 * s:.2f} {pad - y0 * s:.2f}) scale({s:.5f})">\n'
		+ f"  {_stroked('url(#nzw)', indent='  ')}\n"
		+ "  </g>\n"
		+ word.svg(text_x, top + cap_w, NAVY)
		+ "\n"
		+ sub.svg(text_x, top + block, SLATE)
		+ "\n</svg>\n"
	)


# --- PNG -------------------------------------------------------------------------


def _mark_mask(size: int, ss: int, inset: float = 1.0):
	"""Anti-aliased alpha mask of the ribbon, drawn at ss times resolution."""
	from PIL import Image, ImageDraw

	big = size * ss
	k = big / SIZE * inset
	pad = big * (1 - inset) / 2

	def P(x: float, y: float) -> tuple[float, float]:
		return (x * k + pad, y * k + pad)

	m = Image.new("L", (big, big), 0)
	d = ImageDraw.Draw(m)
	w = STROKE * k

	foot_y, head_y = Y_BOT - HOOK_R, Y_TOP + HOOK_R
	foot_tip_x, head_tip_x = X_L + 2 * HOOK_R, X_R - 2 * HOOK_R

	for a, b in (
		((X_L, Y_TOP), (X_L, foot_y)),
		((X_L, Y_TOP), (X_R, Y_BOT)),
		((X_R, Y_BOT), (X_R, head_y)),
		((foot_tip_x, foot_y - HOOK_TAIL), (foot_tip_x, foot_y)),
		((head_tip_x, head_y), (head_tip_x, head_y + HOOK_TAIL)),
	):
		d.line([P(*a), P(*b)], fill=255, width=round(w))

	for cx, cy, start, end in ((X_L + HOOK_R, foot_y, 0, 180), (X_R - HOOK_R, head_y, 180, 360)):
		px, py = P(cx, cy)
		# PIL paints an arc's width *inward* from the circle it is given, while
		# SVG centres a stroke on its path. Handing PIL a circle half a stroke
		# larger puts the band where the SVG puts it; without this every hook
		# comes out half a stroke small and meets its straight run with a notch.
		R = HOOK_R * k + w / 2
		d.arc([px - R, py - R, px + R, py + R], start, end, fill=255, width=round(w))

	# Round every cap and joint.
	for x, y in (
		(X_L, Y_TOP),
		(X_L, foot_y),
		(X_R, Y_BOT),
		(X_R, head_y),
		(foot_tip_x, foot_y),
		(foot_tip_x, foot_y - HOOK_TAIL),
		(head_tip_x, head_y),
		(head_tip_x, head_y + HOOK_TAIL),
	):
		px, py = P(x, y)
		d.ellipse([px - w / 2, py - w / 2, px + w / 2, py + w / 2], fill=255)

	return m


def _gradient(width: int, height: int):
	"""TEAL at top-left to BLUE at bottom-right.

	Built small and scaled up: a linear gradient survives bilinear scaling
	exactly, and a per-pixel loop over a 4096-pixel canvas takes a minute.
	"""
	from PIL import Image

	t0, t1 = _rgb(TEAL), _rgb(BLUE)
	n = 256
	small = Image.new("RGB", (n, n))
	px = small.load()
	for y in range(n):
		for x in range(n):
			t = (x + y) / (2 * (n - 1))
			px[x, y] = tuple(round(t0[i] + (t1[i] - t0[i]) * t) for i in range(3))
	return small.resize((width, height), Image.BILINEAR)


def _render(size: int, tile: bool = False, ground: str | None = None, pad: float = 0.0):
	from PIL import Image, ImageDraw

	ss = 4
	big = size * ss
	inset = 0.74 if tile else 1.0 - 2 * pad
	mask = _mark_mask(size, ss, inset=inset)
	img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
	d = ImageDraw.Draw(img)
	if tile:
		d.rounded_rectangle([0, 0, big - 1, big - 1], radius=int(112 * big / SIZE), fill=TILE)
	elif ground:
		d.rectangle([0, 0, big, big], fill=ground)
	img.paste(_gradient(big, big), (0, 0), mask)
	return img.resize((size, size), Image.LANCZOS)


def write_pngs(out_dir: Path) -> list[str]:
	try:
		import PIL
	except ImportError:
		return []

	written: list[str] = []
	for size in (1024, 512, 256, 128, 64, 32, 16):
		p = out_dir / f"logo-{size}.png"
		_render(size).save(p)
		written.append(p.name)

	for size in (1024, 512, 192):
		p = out_dir / f"logo-tile-{size}.png"
		_render(size, tile=True).save(p)
		written.append(p.name)

	# A listing card sits on white, and a transparent mark with no breathing
	# room crops badly there, so it gets a padded, opaque version of its own.
	p = out_dir / "logo-1024-opaque.png"
	_render(1024, ground="#FFFFFF", pad=0.14).convert("RGB").save(p)
	written.append(p.name)

	ico = out_dir / "favicon.ico"
	_render(64).save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
	written.append(ico.name)
	return written


def write_social_card(out_dir: Path) -> str | None:
	"""The 1280 x 640 card GitHub shows when the repository is shared."""
	fb, fm = _find_font(FONT_BOLD), _find_font(FONT_MEDIUM)
	if not (fb and fm):
		return None
	from PIL import Image, ImageDraw, ImageFont

	ss = 2
	W, H = 1280 * ss, 640 * ss
	card = Image.new("RGB", (W, H), TILE)
	d = ImageDraw.Draw(card)

	# the mark, left, on the card's own ground
	mark = _render(300 * ss)
	card.paste(mark, (120 * ss, (H - mark.height) // 2), mark)

	def font(path: Path, px: int):
		return ImageFont.truetype(str(path), px * ss)

	def tracked(x: int, y: int, text: str, face, fill: str, track: float) -> None:
		for ch in text:
			d.text((x, y), ch, font=face, fill=fill)
			x += face.getlength(ch) + track * ss

	left = 500 * ss
	big, small = font(fb, 104), font(fm, 34)
	word, label = "NEXUS", "ZKT INTEGRATION"
	word_track = 8
	tracked(left, 178 * ss, word, big, "#FFFFFF", word_track)

	# Justified to NEXUS, as in the wordmark: solve for the letterspacing that
	# makes the two lines the same width.
	word_w = sum(big.getlength(ch) for ch in word) + word_track * ss * (len(word) - 1)
	bare_w = sum(small.getlength(ch) for ch in label)
	label_track = max(2.0, (word_w - bare_w) / (len(label) - 1) / ss)
	tracked(left + 4 * ss, 314 * ss, label, small, RULE, label_track)
	d.text(
		(left + 4 * ss, 386 * ss),
		"ZKTeco attendance, straight into ERPNext \u2014\nacross every door in the building.",
		font=font(fm, 27),
		fill="#D5DAE6",
		spacing=12 * ss,
	)
	d.text((left + 4 * ss, 520 * ss), "Frappe  ·  ERPNext  ·  HRMS  15 and 16", font=font(fm, 22), fill=MIST)

	p = out_dir / "social-preview.png"
	card.resize((1280, 640), Image.LANCZOS).save(p, optimize=True)
	return p.name


def main() -> None:
	OUT.mkdir(parents=True, exist_ok=True)
	written = []
	for name, body in (
		("logo.svg", svg_mark()),
		("logo-mono.svg", svg_mono()),
		("logo-mono-light.svg", svg_mono("#FFFFFF")),
		("logo-tile.svg", svg_tile()),
		("logo-lockup.svg", svg_lockup()),
		("logo-wordmark.svg", svg_wordmark()),
	):
		if body is None:
			print(f"  ! {name} skipped - Poppins not found in {FONT_DIRS}")
			continue
		(OUT / name).write_text(body, encoding="utf-8")
		written.append(name)

	written += write_pngs(OUT)
	card = write_social_card(OUT)
	if card:
		written.append(card)
	else:
		print(f"  ! social-preview.png skipped - Poppins not found in {FONT_DIRS}")

	# The app serves its own copy; regenerate it from the same source so the
	# logo on the /apps screen can never drift from the one in the README.
	PUBLIC.mkdir(parents=True, exist_ok=True)
	(PUBLIC / "logo.svg").write_text(svg_mark(), encoding="utf-8")
	_render(512).save(PUBLIC / "logo.png")
	written += ["public/images/logo.svg", "public/images/logo.png"]

	print(f"wrote {len(written)} files:")
	for n in written:
		print(f"  {n}")


if __name__ == "__main__":
	main()
