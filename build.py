#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the pinned simple-pipeline runtime without installing it."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--build', type=Path, default=Path('build'))
    parser.add_argument('--cross-file', type=Path)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    lock = json.loads((here / 'libcamera.lock').read_text())
    source, build = args.source.resolve(), args.build.resolve()
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != lock['revision']:
        parser.error('Source revision does not match libcamera.lock')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no']):
        parser.error('Tracked libcamera sources were modified')
    options = ['--prefix=/usr', '--libdir=lib', '--sysconfdir=/etc',
               '--buildtype=release', '--auto-features=disabled', '-Dwerror=false',
               '-Dpipelines=simple', '-Dipas=simple', '-Dsoftisp-gpu=disabled',
               '-Dcam=enabled', '-Dtest=false']
    if args.cross_file:
        options += ['--cross-file', str(args.cross_file.resolve())]
    if (build / 'meson-private/coredata.dat').exists():
        options += ['--reconfigure']
    subprocess.run(['meson', 'setup', str(build), str(source), *options], check=True)
    subprocess.run(['ninja', '-C', str(build), '-j', str(args.jobs)], check=True)
    stage = build / 'stage'
    env = os.environ.copy()
    env['DESTDIR'] = str(stage)
    subprocess.run(['meson', 'install', '-C', str(build)], env=env, check=True)
    runtime = build / 'runtime'
    next_runtime = Path(tempfile.mkdtemp(prefix='runtime-next-', dir=build))
    for name in ('lib', 'ipa', 'proxy', 'bin'):
        (next_runtime / name).mkdir()
    for name in ('libcamera.so.0.7.2', 'libcamera-base.so.0.7.2'):
        shutil.copy2(stage / 'usr/lib' / name, next_runtime / 'lib' / name)
        (next_runtime / 'lib' / name.rsplit('.', 1)[0]).symlink_to(name)
    shutil.copy2(stage / 'usr/lib/libcamera/ipa/ipa_soft_simple.so', next_runtime / 'ipa/ipa_soft_simple.so')
    shutil.copy2(stage / 'usr/libexec/libcamera/soft_ipa_proxy', next_runtime / 'proxy/soft_ipa_proxy')
    shutil.copy2(stage / 'usr/bin/cam', next_runtime / 'bin/vermeer-cam')
    if runtime.exists():
        runtime.rename(build / ('runtime-previous-' + str(time.time_ns())))
    next_runtime.rename(runtime)
    print('Built runtime:', runtime)


if __name__ == '__main__':
    main()
