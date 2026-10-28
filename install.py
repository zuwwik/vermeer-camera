#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage the working camera runtime and back up replaced configuration."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--version', default='20261029-power1')
    parser.add_argument('--root', type=Path, help='Stage into a mounted target rootfs')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root = args.root.resolve() if args.root else Path('/')
    runtime = args.runtime.resolve()
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]*', args.version):
        parser.error('Invalid runtime version')
    if not args.root:
        if os.geteuid() != 0 or platform.machine() != 'aarch64':
            parser.error('Run as root on the aarch64 musl phone, or use --root')
        if b'xiaomi,vermeer' not in Path('/proc/device-tree/compatible').read_bytes().split(b'\0'):
            parser.error('This is not a Xiaomi Vermeer')
        if not Path('/lib/ld-musl-aarch64.so.1').exists():
            parser.error('This integration requires a musl rootfs')
    names = ['lib/libcamera.so.0.7.2', 'lib/libcamera-base.so.0.7.2',
             'ipa/ipa_soft_simple.so', 'proxy/soft_ipa_proxy', 'bin/vermeer-cam']
    for name in names:
        if not (runtime / name).is_file():
            parser.error('Missing runtime file: ' + name)
    base = root / 'usr/local/lib/vermeer-camera'
    current = base / 'current'
    if current.exists() and not current.is_symlink():
        parser.error('Runtime selector exists and is not a symlink')
    base.mkdir(parents=True, exist_ok=True)
    target = base / args.version
    if target.exists():
        if not all((target / n).is_file() and (target / n).read_bytes() == (runtime / n).read_bytes()
                   for n in names if not n.startswith('bin/')):
            parser.error('Existing version differs; use a new --version')
    else:
        temporary = base / ('.' + args.version + '.new')
        shutil.copytree(runtime, temporary, symlinks=True)
        temporary.rename(target)
    backup = root / 'var/backups/vermeer-camera' / str(time.time_ns())
    backup.mkdir(parents=True)
    records = []

    def save(path):
        record = {'path': '/' + str(path.relative_to(root))}
        if path.is_symlink():
            record['symlink'] = os.readlink(path)
        elif path.exists():
            name = str(len(records))
            shutil.copy2(path, backup / name)
            record['copy'] = name
        records.append(record)
        (backup / 'restore.json').write_text(json.dumps(records, indent=2) + '\n')

    def write(name, data, mode=0o644):
        path = root / name.lstrip('/')
        save(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.vermeer-new')
        temporary.write_bytes(data)
        temporary.chmod(mode)
        temporary.replace(path)

    tuning = root / 'usr/local/share/libcamera/vermeer-colors-20261026/simple'
    tuning.mkdir(parents=True, exist_ok=True)
    for p in (here / 'tuning/simple').glob('*.yaml'):
        write('/' + str((tuning / p.name).relative_to(root)), p.read_bytes())
    for name in ('70-vermeer-camera.rules', '51-vermeer-camera.conf'):
        directory = '/etc/udev/rules.d/' if name.endswith('.rules') else '/etc/wireplumber/wireplumber.conf.d/'
        write(directory + name, (here / 'integration' / name).read_bytes())
    write('/etc/libcamera/configuration.yaml', (here / 'integration/configuration.yaml').read_bytes())
    search_file = root / 'etc/ld-musl-aarch64.path'
    paths = search_file.read_text().strip().split(':') if search_file.exists() else ['/lib', '/usr/local/lib', '/usr/lib']
    selected = '/usr/local/lib/vermeer-camera/current/lib'
    paths = [selected] + [p for p in paths if p and p != selected]
    write('/etc/ld-musl-aarch64.path', (':'.join(paths) + '\n').encode())
    write('/usr/local/bin/vermeer-cam', (runtime / 'bin/vermeer-cam').read_bytes(), 0o755)
    save(current)
    temporary = base / '.current.new'
    temporary.symlink_to(args.version)
    temporary.replace(current)
    os.sync()
    print('Installed runtime:', target)
    print('Previous configuration:', backup)
    print('Restart camera clients and the desktop WirePlumber service, or reboot normally.')


if __name__ == '__main__':
    main()
