# Vermeer camera

Working libcamera integration for the OVX8000 main, OV16A1Q front and IMX355
ultrawide cameras on Poco F6 Pro / Redmi K70. Kernel drivers and board wiring
are in [vermeer-mainline](https://github.com/zuwwik/vermeer-mainline).

The [libcamera fork](https://github.com/zuwwik/vermeer-libcamera) supplies sensor
helpers, contrast autofocus, highlight-aware exposure, native colour processing
and offline RAW10 still processing. `libcamera.lock` pins the exact source.
Lens power is released outside active capture sessions. Native CCM tuning is
in `tuning/simple/`; the AE/AF algorithms and sensor modes are preserved.

Default processed sizes: main 4088x3072, front 2296x1728, ultrawide 3272x2464.
The configured preview budget preserves these binned modes and does not reduce
full RAW still dimensions. Offline stills clip white-balanced sensor channels
before the colour matrix, matching preview and keeping clipped highlights neutral.
Main has contrast AF; front and ultrawide are fixed
focus. Full 50 MP, OIS, Android PDAF/HDR and Qualcomm ICP are not enabled.

The separate [Plasma Camera fork](https://github.com/zuwwik/vermeer-plasma-camera)
contains the deployed JPEG 100 still workflow and front/rear orientation fixes.
Its application binary is packaged there, independently of this runtime.

## Build

Use the native target compiler, Meson, Ninja, pkg-config, Python with Jinja2,
PyYAML/PLY, and libyaml development files. Optional features are disabled unless
needed by the simple pipeline. A target sysroot can be supplied through a Meson
cross file.

```sh
python3 build.py --source ../vermeer-libcamera
# Cross build:
python3 build.py --source ../vermeer-libcamera --cross-file /path/to/target.ini
```

The command verifies the source revision and produces `build/runtime/` without
changing the running system. Install that complete runtime as a set; the core,
base library, IPA and proxy share a private ABI.

## Install on the musl phone

`prebuilt/aarch64-linux-musl/` is the exact deployed `20261029-colour2` runtime and cam
tool. It is for the aarch64 musl system, not a glibc rootfs. Verify it with
`sha256sum -c SHA256SUMS`.

Close camera clients, then as root:

```sh
python3 install.py --runtime prebuilt/aarch64-linux-musl
# Or use the rebuilt set:
python3 install.py --runtime build/runtime --version local-build
```

The installer saves previous configuration, stages a versioned runtime and
updates the libcamera configuration and musl library search path. It does not
restart applications, WirePlumber, the kernel or the phone. Reboot normally or
restart camera clients and the desktop's WirePlumber service after installation.
The user needs access to the camera media/video nodes and system DMA heap;
`integration/70-vermeer-camera.rules` supplies the heap rule.

Native libcamera/PipeWire clients use the camera directly. V4L2-only client
compatibility remains unresolved and no bridge service is enabled here.

## Verify

```sh
vermeer-cam --list
vermeer-cam -c 1 --capture=30
python3 tests/test-libcamera-colors.py ../vermeer-libcamera
```

Prebuilt library licenses are in `LICENSES/` and `COPYING.libcamera.rst`; the
corresponding source is the pinned libcamera fork. Tuning file licenses are
declared in their headers.
