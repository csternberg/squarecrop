#!/usr/bin/env python3
"""
squarecrop.py - Square image extractor and resizer
Version 2.00

Refactored features:
- Case-insensitive switches
- Multithreaded processing
- Crop modes: top/left/right/bottom
- Expand mode: black/white padding
- JPEG output only
- EXIF preservation (unless -M)
- White-background flattening for transparent images
- Dry run, logging, verbose mode
- Recursive processing
"""

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

VERSION = "2.00"

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError:
    print("ERROR: Pillow is not installed. Install with: pip install pillow")
    sys.exit(1)

SUPPORTED_EXTENSIONS = {".jpg",".jpeg",".png",".bmp",".gif",".tif",".tiff",".webp"}
ERROR_COUNT = 0

def normalize_argv(argv):
    out = [argv[0]]
    for a in argv[1:]:
        if a.startswith("-"):
            out.append(a.upper())
        else:
            out.append(a)
    return out

def configure_logging(enabled):
    if enabled:
        logging.basicConfig(
            filename="squarecrop.log",
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )

def flatten_for_jpeg(img):
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGB", img.size, (255,255,255))
        alpha = img.convert("RGBA")
        bg.paste(alpha, mask=alpha.getchannel("A"))
        return bg
    return img.convert("RGB")

def unique_filename(path):
    if not path.exists():
        return path
    n = 1
    while True:
        p = path.with_name(f"{path.stem}_{n:03d}{path.suffix}")
        if not p.exists():
            return p
        n += 1

def crop_box(w,h,mode):
    s=min(w,h)
    if mode=="TOP":
        return ((w-s)//2,0,(w+s)//2,s)
    if mode=="BOTTOM":
        return ((w-s)//2,h-s,(w+s)//2,h)
    if mode=="LEFT":
        return (0,(h-s)//2,s,(h+s)//2)
    return (w-s,(h-s)//2,w,(h+s)//2)

def output_name(src,suffix,outdir):
    base = Path(outdir) if outdir else src.parent
    return base / f"{src.stem}_{suffix}.jpg"

def save_image(img, src_img, target, args):
    kwargs={"format":"JPEG","quality":args.quality}
    if not args.strip_metadata:
        exif = src_img.info.get("exif")
        if exif:
            kwargs["exif"]=exif
    img.save(target, **kwargs)

def process_crop(source,args,mode):
    suffix = {
        "TOP":"square_top",
        "LEFT":"square_left",
        "RIGHT":"square_right",
        "BOTTOM":"square_bottom"
    }[mode]
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img)
        w,h=img.size
        if w==h and args.resize is None:
            return
        if w==h and args.resize==w:
            return
        out = img.crop(crop_box(w,h,mode))
        if args.resize:
            out = out.resize((args.resize,args.resize), Image.Resampling.LANCZOS)
        out = flatten_for_jpeg(out)
        target = output_name(source,suffix,args.output)
        if not args.overwrite:
            target = unique_filename(target)
        if args.dry_run:
            print(target)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        save_image(out,img,target,args)

def process_expand(source,args):
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img)
        w,h=img.size
        if w==h and args.resize is None:
            return
        if w==h and args.resize==w:
            return
        side=max(w,h)
        bg=(0,0,0) if args.expand=="b" else (255,255,255)
        canvas=Image.new("RGB",(side,side),bg)
        canvas.paste(flatten_for_jpeg(img),((side-w)//2,(side-h)//2))
        if args.resize:
            canvas=canvas.resize((args.resize,args.resize),Image.Resampling.LANCZOS)
        suffix="square_expand_black" if args.expand=="b" else "square_expand_white"
        target=output_name(source,suffix,args.output)
        if not args.overwrite:
            target=unique_filename(target)
        if args.dry_run:
            print(target)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        save_image(canvas,img,target,args)

def worker(source,args,modes):
    global ERROR_COUNT
    try:
        if args.expand:
            process_expand(source,args)
        else:
            for m in modes:
                process_crop(source,args,m)
    except (PermissionError, UnidentifiedImageError, OSError, Exception) as e:
        ERROR_COUNT += 1
        logging.error("%s: %s", source, e)

def collect_files(args):
    files=[]
    if args.file_pattern:
        files = list(Path(".").rglob(args.file_pattern) if args.recursive else Path(".").glob(args.file_pattern))
    elif args.recursive:
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(Path(".").rglob(f"*{ext}"))
    elif args.current:
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(Path(".").glob(f"*{ext}"))
    else:
        files=[Path(f) for f in args.files]
    return sorted({p for p in files if p.is_file() and not p.is_symlink()})

def parser():
    p=argparse.ArgumentParser(description="Square image extractor and resizer")
    p.add_argument("-D", action="store_true", dest="dry_run")
    p.add_argument("-L", action="store_true", dest="log")
    p.add_argument("-V", action="store_true", dest="verbose")
    p.add_argument("-T", action="store_true")
    p.add_argument("-LS", action="store_true")
    p.add_argument("-RS", action="store_true")
    p.add_argument("-B", action="store_true")
    p.add_argument("-E", dest="expand")
    p.add_argument("-Z", type=int, dest="resize")
    p.add_argument("-Q", type=int, default=95, dest="quality")
    p.add_argument("-W", action="store_true", dest="overwrite")
    p.add_argument("-M", action="store_true", dest="strip_metadata")
    p.add_argument("-C", action="store_true", dest="current")
    p.add_argument("-R", action="store_true", dest="recursive")
    p.add_argument("-F", dest="file_pattern")
    p.add_argument("-O", dest="output")
    p.add_argument("-J", type=int, default=4, dest="jobs")
    p.add_argument("--VERSION", action="store_true")
    p.add_argument("files", nargs="*")
    return p

def main():
    argv = normalize_argv(sys.argv)
    args = parser().parse_args(argv[1:])

    if args.VERSION:
        print("squarecrop", VERSION)
        return 0

    configure_logging(args.log)

    if args.expand:
        args.expand=args.expand.lower()
        if args.expand not in ("b","w"):
            print("ERROR: -E must be b or w")
            return 1
        if args.T or args.LS or args.RS or args.B:
            print("ERROR: -E cannot be combined with crop switches")
            return 1

    files=collect_files(args)
    if not files:
        print("No matching image files found.")
        return 2

    modes=[]
    if args.T: modes.append("TOP")
    if args.LS: modes.append("LEFT")
    if args.RS: modes.append("RIGHT")
    if args.B: modes.append("BOTTOM")
    if not modes and not args.expand:
        modes=["TOP"]

    with ThreadPoolExecutor(max_workers=max(1,args.jobs)) as ex:
        futures=[ex.submit(worker,f,args,modes) for f in files]
        for _ in as_completed(futures):
            pass

    return 3 if ERROR_COUNT else 0

if __name__=="__main__":
    sys.exit(main())
