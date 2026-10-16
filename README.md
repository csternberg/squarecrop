# squarecrop

Cut square JPEGs out of images, or pad them to a square. Batch-friendly,
multithreaded, and cross-platform (Python 3 + Pillow).

- Crop a square of the shorter side from the top, bottom, left, right or middle
- Or pad the short sides to a square with black, white or any RGB colour
- Optional resize, JPEG quality control, EXIF/ICC preservation
- Transparent images are flattened onto white
- Handles EXIF orientation, wildcards, recursion, dry runs and logging

## Install

```
pip install pillow
```

Then run `python squarecrop.py ...` (or `./squarecrop.py` on Unix after `chmod +x`).
Optional: install the man page with
`install -D squarecrop.1 /usr/local/share/man/man1/squarecrop.1`.

## Usage

```
squarecrop.py [switches] [files ...]
```

Switches are **case-insensitive** and come in a Windows style and a Unix style:
`-LS`, `-ls` and `--LeftSide` are identical. `--switch=value` also works.

| Short | Long | Meaning |
|---|---|---|
| `-t` | `--top` | Crop top (portrait) / centre (landscape). Default if no mode given |
| `-ls` | `--leftside`, `--left` | Crop left side (landscape) |
| `-rs` | `--rightside`, `--right` | Crop right side (landscape) |
| `-b` | `--bottom` | Crop bottom (portrait) |
| `-i` | `--middle` | Crop a centred square from the middle |
| `-p COLOR` | `--pad`, `--expand`, `-e` | Pad to a square instead of cropping. `COLOR` = `black`, `white`, `b`, `w`, `0xAABBCC` or `#AABBCC` |
| `-z N` | `--resize` | Resize result to N x N pixels |
| `-q N` | `--quality` | JPEG quality 1-100 (default 95) |
| `-o DIR` | `--output` | Write results to DIR (created if needed) |
| `-w` | `--overwrite` | Overwrite existing output files |
| `-m` | `--strip-metadata`, `--nometadata` | Don't copy EXIF/ICC metadata |
| `-c` | `--current` | Process all images in the current folder |
| `-r` | `--recursive` | Process the current folder and all sub-folders |
| `-f GLOB` | `--file-pattern`, `--pattern` | Only process files matching GLOB |
| `-j N` | `--jobs` | Worker threads (default 4) |
| `-d` | `--dry-run`, `--dryrun` | Print output names, write nothing |
| `-l` | `--log` | Log to `squarecrop.log` |
| `-v` | `--verbose` | Print each file as it is processed |
| `-h`, `-?` | `--help` | Show help |
| | `--version` | Show version |

Crop modes can be combined (`-t -b -i` makes three files per image). `--pad`
cannot be combined with crop modes. With `--` everything after it is treated as
a file name.

### Examples

```
squarecrop.py photo.jpg                       # top/centre square
squarecrop.py -ls -rs -c                      # left and right crops of every image here
squarecrop.py -i -z 512 *.png                 # centred 512x512 squares
squarecrop.py --pad black photo.jpg           # 100x200 -> 200x200 with 50 px black bars
squarecrop.py --pad 0x336699 -r -o out        # pad everything below here, results in out/
squarecrop.py -r -f "*.png" -q 90 --dry-run   # preview only
```

## Behaviour

- **Crop geometry:** the square side is the shorter image dimension. `-t`/`-b`
  only differ from the centre on portrait images, `-ls`/`-rs` on landscape; on
  the other orientation they crop from the centre.
- **Output names:** `<name>_square_<mode>.jpg` where mode is `top`, `middle`,
  `left`, `right`, `bottom` or `pad_rrggbb`. Existing files are never
  overwritten: a `_001`, `_002`, ... suffix is added unless `-w` is given.
- **Already square** images are skipped (unless `-z` asks for a different size).
- Files named like our own output are skipped by `-c`, `-r` and `-f`, so reruns
  don't process results.
- Supported input: jpg, jpeg, png, bmp, gif (first frame), tif, tiff, webp.
  Output is always JPEG.
- Wildcards in file arguments are expanded even on cmd/PowerShell.
- Symbolic links are ignored.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Usage error (no input, conflicting switches) |
| 2 | No matching files, or invalid argument |
| 3 | One or more files failed (others are still processed; errors go to stderr) |

## License

No license specified yet.
