#!/usr/bin/env python3
"""
squarecrop.py - Square image extractor and resizer
Version 2.10

Features:
- Case-insensitive switches, Windows style (-ls) and Unix style (--leftside)
- Multithreaded processing
- Crop modes: top / left side / right side / bottom
- Expand mode: black/white padding
- JPEG output only
- EXIF / ICC preservation (unless -m)
- White-background flattening for transparent images
- Dry run, logging, verbose mode
- Recursive processing
"""

import argparse
import glob
import logging
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

VERSION = "2.10"

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError:
    print("ERROR: Pillow is not installed. Install with: pip install pillow", file=sys.stderr)
    sys.exit(1)

try:
    LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    LANCZOS = Image.LANCZOS

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}

# Files we created ourselves; skipped when scanning so reruns don't recurse on output.
OUTPUT_RE = re.compile(r"_square_(top|middle|left|right|bottom|expand_black|expand_white|pad_[0-9a-f]{6})(_\d{3})?$", re.I)

_name_lock = threading.Lock()
_reserved = set()
_error_lock = threading.Lock()
_error_count = 0

# Every switch, with its Windows-style short form first and Unix-style long forms after.
# Switches are matched case-insensitively (-LS == -ls == --LeftSide == --leftside).
KNOWN_OPTIONS = {
    "-h", "-?", "--help",
    "--version",
    "-t", "--top",
    "-ls", "--leftside", "--left",
    "-rs", "--rightside", "--right",
    "-b", "--bottom",
    "-i", "--middle",
    "-p", "--pad", "-e", "--expand",
    "-z", "--resize",
    "-q", "--quality",
    "-w", "--overwrite",
    "-m", "--strip-metadata", "--nometadata",
    "-c", "--current",
    "-r", "--recursive",
    "-f", "--file-pattern", "--pattern",
    "-o", "--output",
    "-j", "--jobs",
    "-d", "--dry-run", "--dryrun",
    "-l", "--log",
    "-v", "--verbose",
}


def normalize_argv(argv):
    """Lower-case recognised switches only; values and file names are left untouched."""
    out = []
    for a in argv:
        if a == "--":
            out.append(a)
            out.extend(argv[len(out):])
            break
        if a.startswith("-") and len(a) > 1:
            name, eq, value = a.partition("=")
            if name.lower() in KNOWN_OPTIONS:
                a = name.lower() + eq + value
        out.append(a)
    return out


NAMED_COLORS = {"black": (0, 0, 0), "white": (255, 255, 255), "b": (0, 0, 0), "w": (255, 255, 255)}


def pad_color(text):
    """black, white, b, w, or hex RGB such as 0xAABBCC / #AABBCC -> (r, g, b)."""
    t = text.strip().lower()
    if t in NAMED_COLORS:
        return NAMED_COLORS[t]
    h = t[2:] if t.startswith("0x") else t[1:] if t.startswith("#") else None
    if h is not None and len(h) == 6:
        try:
            v = int(h, 16)
            return (v >> 16, (v >> 8) & 255, v & 255)
        except ValueError:
            pass
    raise argparse.ArgumentTypeError("must be black, white or a colour like 0xAABBCC")


def positive_int(text):
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer")
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def quality_value(text):
    n = positive_int(text)
    if n > 100:
        raise argparse.ArgumentTypeError("must be between 1 and 100")
    return n


HELP_EPILOG = """\
Switches are case-insensitive: -LS, -ls and --LeftSide are all the same.
Each Windows-style switch has a Unix-style long form (shown above).

Crop modes (can be combined; default is -t). The crop is a square of the
shorter side. -i always takes it from the centre. -t/-b are only meaningful
for portrait images and -ls/-rs for landscape images; on the other
orientation they crop from the centre.
Output files are named <name>_square_<mode>.jpg and never overwrite
existing files unless -w is given.

Examples:
  squarecrop.py photo.jpg                      crop top/centre square
  squarecrop.py -ls -rs -c                     left and right crops of every image here
  squarecrop.py -i -c                          centred square of every image here
  squarecrop.py --pad 0x336699 photo.jpg       100x200 -> 200x200, 50px bars of that colour
  squarecrop.py --recursive --pad white -z 1024 -o out
  squarecrop.py -r -f "*.png" -q 90 --dry-run
"""


def build_parser():
    p = argparse.ArgumentParser(
        prog="squarecrop",
        description="Square image extractor and resizer (JPEG output).",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
        allow_abbrev=False,
        usage="%(prog)s [switches] [files ...]",
    )
    g = p.add_argument_group("crop modes")
    g.add_argument("-t", "--top", action="store_true", help="crop top (portrait) / centre (landscape)")
    g.add_argument("-ls", "--leftside", "--left", action="store_true", dest="leftside",
                   help="crop left side (landscape)")
    g.add_argument("-rs", "--rightside", "--right", action="store_true", dest="rightside",
                   help="crop right side (landscape)")
    g.add_argument("-b", "--bottom", action="store_true", help="crop bottom (portrait)")
    g.add_argument("-i", "--middle", action="store_true", help="crop a centred square from the middle")
    g.add_argument("-p", "--pad", "-e", "--expand", type=pad_color, metavar="COLOR", dest="pad",
                   help="don't crop: pad the short sides to a square with COLOR "
                        "(black, white or 0xAABBCC)")

    g = p.add_argument_group("output")
    g.add_argument("-z", "--resize", type=positive_int, metavar="PIXELS",
                   help="resize result to PIXELS x PIXELS")
    g.add_argument("-q", "--quality", type=quality_value, default=95, metavar="1-100",
                   help="JPEG quality (default: 95)")
    g.add_argument("-o", "--output", metavar="DIR", help="write results to DIR (created if needed)")
    g.add_argument("-w", "--overwrite", action="store_true", help="overwrite existing output files")
    g.add_argument("-m", "--strip-metadata", "--nometadata", action="store_true", dest="strip_metadata",
                   help="do not copy EXIF/ICC metadata")

    g = p.add_argument_group("input selection")
    g.add_argument("-c", "--current", action="store_true", help="process all images in the current folder")
    g.add_argument("-r", "--recursive", action="store_true",
                   help="process images in the current folder and all sub-folders")
    g.add_argument("-f", "--file-pattern", "--pattern", metavar="GLOB", dest="file_pattern",
                   help='only process files matching GLOB (e.g. "*.png")')
    g.add_argument("files", nargs="*", metavar="files", help="image files (wildcards allowed)")

    g = p.add_argument_group("misc")
    g.add_argument("-j", "--jobs", type=positive_int, default=4, metavar="N", help="worker threads (default: 4)")
    g.add_argument("-d", "--dry-run", "--dryrun", action="store_true", dest="dry_run",
                   help="show what would be written, write nothing")
    g.add_argument("-l", "--log", action="store_true", help="log to squarecrop.log")
    g.add_argument("-v", "--verbose", action="store_true", help="print each file as it is processed")
    g.add_argument("--version", action="store_true", help="show version and exit")
    g.add_argument("-h", "-?", "--help", action="help", help="show this help and exit")
    return p


log = logging.getLogger("squarecrop")
log.addHandler(logging.NullHandler())  # silent unless -l is given
log.setLevel(logging.INFO)


def configure_logging(enabled):
    if enabled:
        h = logging.FileHandler("squarecrop.log", encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)


def flatten_for_jpeg(img):
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        alpha = img.convert("RGBA")
        bg.paste(alpha, mask=alpha.getchannel("A"))
        return bg
    return img.convert("RGB")


def reserve_filename(path, overwrite):
    """Pick an output name and reserve it so concurrent workers never pick the same one."""
    with _name_lock:
        if overwrite:
            _reserved.add(path)
            return path
        n = 0
        candidate = path
        while candidate.exists() or candidate in _reserved:
            n += 1
            candidate = path.with_name(f"{path.stem}_{n:03d}{path.suffix}")
        _reserved.add(candidate)
        return candidate


def crop_box(w, h, mode):
    s = min(w, h)
    if mode == "MIDDLE":
        return ((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2)
    if mode == "TOP":
        return ((w - s) // 2, 0, (w + s) // 2, s)
    if mode == "BOTTOM":
        return ((w - s) // 2, h - s, (w + s) // 2, h)
    if mode == "LEFT":
        return (0, (h - s) // 2, s, (h + s) // 2)
    return (w - s, (h - s) // 2, w, (h + s) // 2)  # RIGHT


def output_name(src, suffix, outdir):
    base = Path(outdir) if outdir else src.parent
    return base / f"{src.stem}_{suffix}.jpg"


def save_image(img, src_img, target, args):
    kwargs = {"format": "JPEG", "quality": args.quality}
    if not args.strip_metadata:
        exif = src_img.info.get("exif")
        if exif:
            kwargs["exif"] = exif
        icc = src_img.info.get("icc_profile")
        if icc:
            kwargs["icc_profile"] = icc
    img.save(target, **kwargs)


def finish(image, src_img, suffix, source, args):
    target = reserve_filename(output_name(source, suffix, args.output), args.overwrite)
    if args.dry_run:
        print(target)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    save_image(image, src_img, target, args)
    return target


def already_square(w, h, args):
    return w == h and (args.resize is None or args.resize == w)


CROP_SUFFIX = {
    "TOP": "square_top",
    "MIDDLE": "square_middle",
    "LEFT": "square_left",
    "RIGHT": "square_right",
    "BOTTOM": "square_bottom",
}


def process_crop(source, args, mode):
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        if already_square(w, h, args):
            return None
        out = img.crop(crop_box(w, h, mode))
        if args.resize:
            out = out.resize((args.resize, args.resize), LANCZOS)
        out = flatten_for_jpeg(out)
        return finish(out, img, CROP_SUFFIX[mode], source, args)


def process_expand(source, args):
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        if already_square(w, h, args):
            return None
        side = max(w, h)
        canvas = Image.new("RGB", (side, side), args.pad)
        canvas.paste(flatten_for_jpeg(img), ((side - w) // 2, (side - h) // 2))
        if args.resize:
            canvas = canvas.resize((args.resize, args.resize), LANCZOS)
        suffix = "square_pad_%02x%02x%02x" % args.pad
        return finish(canvas, img, suffix, source, args)


def worker(source, args, modes):
    global _error_count
    try:
        targets = [process_expand(source, args)] if args.pad is not None else [process_crop(source, args, m) for m in modes]
        written = [t for t in targets if t]
        if not written:
            if args.verbose:
                print(f"{source}: already square, skipped")
            log.info("%s: skipped (already square)", source)
        for t in written:
            if args.verbose and not args.dry_run:
                print(f"{source} -> {t}")
            log.info("%s -> %s%s", source, t, " (dry run)" if args.dry_run else "")
    except Exception as e:  # one bad file must not stop the batch
        with _error_lock:
            _error_count += 1
        kind = "not a supported image" if isinstance(e, UnidentifiedImageError) else e
        print(f"ERROR: {source}: {kind}", file=sys.stderr)
        log.error("%s: %s", source, e)


def scan(pattern, recursive):
    try:
        it = Path(".").rglob(pattern) if recursive else Path(".").glob(pattern)
        return list(it)
    except (NotImplementedError, ValueError):  # absolute or odd patterns
        return [Path(p) for p in glob.glob(pattern, recursive=recursive)]


def collect_files(args):
    files = []
    if args.file_pattern:
        files += scan(args.file_pattern, args.recursive)
    elif args.recursive or args.current:
        files += [p for p in scan("*", args.recursive) if p.suffix.lower() in SUPPORTED_EXTENSIONS]
    files = [p for p in files if not OUTPUT_RE.search(p.stem)]

    for f in args.files:  # shells such as cmd/PowerShell don't expand wildcards
        matches = [Path(m) for m in glob.glob(f)] if glob.has_magic(f) else [Path(f)]
        if not matches:
            print(f"WARNING: no match for {f}", file=sys.stderr)
        for m in matches:
            if not m.exists():
                print(f"WARNING: not found: {m}", file=sys.stderr)
            else:
                files.append(m)
    return sorted({p for p in files if p.is_file() and not p.is_symlink()})


def main(argv=None):
    parser = build_parser()
    argv = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(normalize_argv(argv))

    if args.version:
        print("squarecrop", VERSION)
        return 0

    if not (args.files or args.current or args.recursive or args.file_pattern):
        parser.print_usage(sys.stderr)
        print("No input given. Use -h for help.", file=sys.stderr)
        return 1

    if args.pad is not None and (args.middle or args.top or args.leftside or args.rightside or args.bottom):
        print("ERROR: --pad cannot be combined with crop switches (-i -t -ls -rs -b)", file=sys.stderr)
        return 1

    configure_logging(args.log)

    files = collect_files(args)
    if not files:
        print("No matching image files found.", file=sys.stderr)
        return 2

    modes = []
    if args.middle:
        modes.append("MIDDLE")
    if args.top:
        modes.append("TOP")
    if args.leftside:
        modes.append("LEFT")
    if args.rightside:
        modes.append("RIGHT")
    if args.bottom:
        modes.append("BOTTOM")
    if not modes and args.pad is None:
        modes = ["TOP"]

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for f in files:
            ex.submit(worker, f, args, modes)

    return 3 if _error_count else 0


if __name__ == "__main__":
    sys.exit(main())
