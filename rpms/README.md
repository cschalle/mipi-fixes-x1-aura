# Prebuilt packages

RPMs are attached to the [releases](../../releases) rather than committed to the
repository, since the kernel packages run to tens of megabytes.

## libcamera (Fedora 44)

A drop-in replacement: same soname as the stock package, so PipeWire and
WirePlumber keep working.

    sudo dnf install ./libcamera-0.7.1-*.lsc2.fc44.x86_64.rpm \
                     ./libcamera-ipa-0.7.1-*.lsc2.fc44.x86_64.rpm \
                     ./libcamera-tools-0.7.1-*.lsc2.fc44.x86_64.rpm
    systemctl --user restart wireplumber

`sudo dnf downgrade libcamera libcamera-ipa libcamera-tools` reverts.

The tuning file ships inside `libcamera-ipa`, so there is nothing to install
separately.

## kernel (Fedora 44)

Built from the stock Fedora SRPM with the three patches applied as
`linux-kernel-test.patch`, and released as `2.imx471fix` so it installs
alongside the stock kernel rather than replacing it. Pick it at boot; the stock
kernel remains available.

Note it is built `--without debuginfo`, which also drops BTF from the modules.
That is fine for testing the camera but means eBPF tooling will not work against
it, so treat it as a test kernel rather than a daily driver.

## Building them yourself

Both are reproducible from the stock Fedora SRPMs; see `kernel/README.md` and
`libcamera/README.md`.
