#!/usr/bin/env python3
"""Create a Data seed for the fuxi iPadOS bring-up on a macOS host (CI runner).

The Linux mkapfs seed is readable by apfs-fuse but the iPadOS 27 APFS kext rejects its
checkpoint ("unexpected checkpoint map entry address"), so the seed has to come from Apple's
own formatter. This script only needs a macOS host: hdiutil creates a blank APFS volume of the
requested size, the volume UUID is recorded, the image is packed to DBRDISK1, then grown to the
final container size with scripts/seed-data-grow.py.

The iPadOS kernel creates the /private/var skeleton and the first-install preferences itself, so
the volume is deliberately empty.

Outputs (next to --output):
  owner-data.dbr        packed seed (DBRDISK1) for payload --data-ramdisk
  owner-data.uuid.txt   the volume UUID the kernel config must match
"""
import argparse
import hashlib
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'drivers/DarwinBoot/Test'))
import packed_ramdisk  # noqa: E402


def run(*cmd, **kw) -> subprocess.CompletedProcess:
    print('+', ' '.join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, capture_output=True, **kw)


def volume_uuid(mountpoint: Path) -> str:
    info = run('diskutil', 'info', '-plist', str(mountpoint)).stdout
    data = plistlib.loads(info)
    for key in ('VolumeUUID', 'DiskUUID'):
        value = data.get(key)
        if value:
            return str(value)
    raise SystemExit('diskutil did not report a volume UUID')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--gib', type=int, default=14, help='Data container size in GiB')
    ap.add_argument('--output', required=True, help='packed seed output (owner-data.dbr)')
    ap.add_argument('--grow', action='store_true', default=True,
                    help='grow the container to --gib with seed-data-grow.py (default)')
    args = ap.parse_args()

    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='fuxi-data-seed-'))
    try:
        raw = work / 'data.cdr'
        mnt = work / 'mnt'
        mnt.mkdir()
        run('hdiutil', 'create', '-size', '%dg' % args.gib, '-layout', 'NONE',
            '-fs', 'APFS', '-volname', 'Data', '-type', 'UDTO', '-ov', str(raw))
        run('hdiutil', 'attach', '-nobrowse', '-readwrite', '-mountpoint', str(mnt), str(raw))
        try:
            uuid = volume_uuid(mnt)
            print('volume UUID:', uuid)
        finally:
            run('hdiutil', 'detach', str(mnt), '-force')
        base = out.with_suffix('.packed')
        packed_ramdisk.pack(raw, base)
        print('packed:', base, base.stat().st_size, 'bytes')
        if args.grow:
            run(sys.executable, str(ROOT / 'scripts/seed-data-grow.py'), '--gib', str(args.gib),
                str(base), str(out))
        else:
            out.write_bytes(base.read_bytes())
        base.unlink(missing_ok=True)
        (out.with_suffix(out.suffix + '.uuid.txt')).write_text(uuid + '\n')
        digest = hashlib.sha256(out.read_bytes()).hexdigest()
        print('seed:', out, out.stat().st_size, 'bytes sha256', digest)
        print('uuid file:', out.with_suffix(out.suffix + '.uuid.txt'))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())