# CLAUDE.md

Single-file Python 3 CLI (`squarecrop.py`, needs Pillow) that makes square JPEGs
from images by cropping or padding. Docs: `README.md`, man page `squarecrop.1`.

## Conventions
- Keep one source file; no dependencies beyond Pillow and the stdlib.
- Switches are case-insensitive. `normalize_argv` lowercases only args listed in
  `KNOWN_OPTIONS`, so any new switch (short and long forms) must be added there
  and in `build_parser`. Never lowercase values or file names.
- Every Windows-style short switch (`-ls`) needs a Unix long form (`--leftside`).
  `-h`, `-?`, `--help` show help; `--version` shows `VERSION`.
- `argparse` runs with `add_help=False, allow_abbrev=False`; keep it so.
- Worker threads share state: use `reserve_filename` (lock) for output names and
  `_error_lock` for the error counter.
- Output is JPEG only; names are `<stem>_square_<mode>.jpg` and `OUTPUT_RE` must
  match every mode so scans skip our own output.
- Exit codes: 0 ok, 1 usage, 2 no files/bad argument, 3 per-file failures.

## When changing behaviour
Update together: `build_parser` + `HELP_EPILOG`, the README table, `squarecrop.1`,
and bump `VERSION` (in the docstring, the constant, and the man page header).

## Testing
No test suite. Check manually in a scratch dir with generated images, e.g.
`python -c "from PIL import Image; Image.new('RGB',(400,200),'red').save('l.png')"`
then run with `-d`/`-v`, mixed-case switches, and `-h`.
