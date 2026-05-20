#!/usr/bin/env python3
"""Generate a Miniloong Pocket 1 SD payload that enables stock ADB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_VER_INNER = 2147483647
DEFAULT_OTA_FILE = "adb_probe.bin"
DEFAULT_PROBE_CONTENT = b"miniloong adb unlock probe\n"
PROBE_ONLY_COMMAND = (
    "LOG=/userdata/loong_upgrade_command_probe.log; "
    "SDLOG=/mnt/sdcard/loong_upgrade_command_probe.log; "
    "printf 'loong_upgrade otaCommand started\\n' >$LOG 2>/dev/null || true; "
    "printf 'loong_upgrade otaCommand started\\n' >$SDLOG 2>/dev/null || true; "
    "touch /userdata/loong_upgrade_command_started 2>/dev/null || true; "
    "touch /mnt/sdcard/loong_upgrade_command_started 2>/dev/null || true; "
    "mv /mnt/sdcard/loong_upgrade /mnt/sdcard/loong_upgrade.used 2>/dev/null || true; "
    "printf 'renamed trigger if writable\\n' >>$LOG 2>/dev/null || true; "
    "printf 'renamed trigger if writable\\n' >>$SDLOG 2>/dev/null || true; "
    "sync; "
    "while true; do sleep 3600; done"
)
ADB_ENABLE_COMMAND = (
    "LOG=/userdata/adb_unlock_probe.log; "
    "SDLOG=/mnt/sdcard/adb_unlock_probe.log; "
    "printf 'adb unlock command started\\n' >$LOG 2>/dev/null || true; "
    "printf 'adb unlock command started\\n' >$SDLOG 2>/dev/null || true; "
    "touch /userdata/adb_unlock_command_started 2>/dev/null || true; "
    "touch /mnt/sdcard/adb_unlock_command_started 2>/dev/null || true; "
    "mv /mnt/sdcard/loong_upgrade /mnt/sdcard/loong_upgrade.used 2>/dev/null || true; "
    "printf 'renamed trigger if writable\\n' >>$LOG 2>/dev/null || true; "
    "printf 'renamed trigger if writable\\n' >>$SDLOG 2>/dev/null || true; "
    "rm -f /tmp/.usb_config /etc/.usb_config; "
    "echo usb_adb_en >/etc/.usb_config; "
    "printf 'wrote /etc/.usb_config\\n' >>$LOG 2>/dev/null || true; "
    "printf 'wrote /etc/.usb_config\\n' >>$SDLOG 2>/dev/null || true; "
    "cat /etc/.usb_config >>$LOG 2>/dev/null || true; "
    "/etc/init.d/S50usb-gadget.sh restart >>$LOG 2>&1 & "
    "printf 'spawned usb gadget restart\\n' >>$LOG 2>/dev/null || true; "
    "printf 'spawned usb gadget restart\\n' >>$SDLOG 2>/dev/null || true; "
    "touch /userdata/adb_unlock_restart_spawned 2>/dev/null || true; "
    "touch /mnt/sdcard/adb_unlock_restart_spawned 2>/dev/null || true; "
    "sync; "
    "while true; do sleep 3600; done"
)
KEEPER_INSTALL_COMMAND = (
    "printf 'adb keeper otaCommand started\\n' >/mnt/sdcard/adb_keeper_install_command.log 2>/dev/null || true; "
    "sh /mnt/sdcard/adb-keeper-install.sh >>/mnt/sdcard/adb_keeper_install_command.log 2>&1; "
    "printf 'adb keeper installer returned\\n' >>/mnt/sdcard/adb_keeper_install_command.log 2>/dev/null || true; "
    "sync; "
    "while true; do sleep 3600; done"
)
COMMAND_MODES = {
    "probe": PROBE_ONLY_COMMAND,
    "adb": ADB_ENABLE_COMMAND,
    "keeper": KEEPER_INSTALL_COMMAND,
}

KEEPER_SCRIPT = """#!/bin/sh
LOG=/userdata/adb-keeper.log
INITIAL_DELAY=${ADB_KEEPER_INITIAL_DELAY:-45}
INTERVAL=${ADB_KEEPER_INTERVAL:-30}

mkdir -p /userdata 2>/dev/null || true
printf '[%s] adb-keeper starting, delay=%s interval=%s\\n' "$(date '+%F %T')" "$INITIAL_DELAY" "$INTERVAL" >>"$LOG" 2>/dev/null || true
sleep "$INITIAL_DELAY"

while true; do
    cfg="$(cat /etc/.usb_config 2>/dev/null || true)"
    funcs="$(cat /var/run/usb-gadget/funcs 2>/dev/null || true)"

    case " $funcs " in
        *" adb "*) has_adb=1 ;;
        *) has_adb=0 ;;
    esac

    if [ "$cfg" != "usb_adb_en" ] || [ "$has_adb" != "1" ]; then
        printf '[%s] forcing adb cfg=%s funcs=%s\\n' "$(date '+%F %T')" "$cfg" "$funcs" >>"$LOG" 2>/dev/null || true
        rm -f /tmp/.usb_config /etc/.usb_config
        echo usb_adb_en >/etc/.usb_config
        /etc/init.d/S50usb-gadget.sh restart >>"$LOG" 2>&1 &
        touch /userdata/adb_keeper_forced 2>/dev/null || true
    fi

    sleep "$INTERVAL"
done
"""

KEEPER_INIT_SCRIPT = """#!/bin/sh

case "$1" in
    start)
        if [ -x /usr/bin/adb-keeper.sh ]; then
            /usr/bin/adb-keeper.sh &
        fi
        ;;
    stop)
        killall adb-keeper.sh 2>/dev/null || true
        ;;
    restart|reload)
        killall adb-keeper.sh 2>/dev/null || true
        if [ -x /usr/bin/adb-keeper.sh ]; then
            /usr/bin/adb-keeper.sh &
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart}" >&2
        exit 1
        ;;
esac

exit 0
"""

KEEPER_INSTALLER = f"""#!/bin/sh
set -u

LOG=/userdata/adb-keeper-install.log
SDLOG=/mnt/sdcard/adb-keeper-install.log

mkdir -p /userdata 2>/dev/null || true
printf '[%s] installing adb keeper\\n' "$(date '+%F %T')" >"$LOG" 2>/dev/null || true
printf '[%s] installing adb keeper\\n' "$(date '+%F %T')" >"$SDLOG" 2>/dev/null || true

mv /mnt/sdcard/loong_upgrade /mnt/sdcard/loong_upgrade.used 2>/dev/null || true
printf 'renamed loong_upgrade if writable\\n' >>"$LOG" 2>/dev/null || true
printf 'renamed loong_upgrade if writable\\n' >>"$SDLOG" 2>/dev/null || true

cat > /usr/bin/adb-keeper.sh <<'ADB_KEEPER_EOF'
{KEEPER_SCRIPT.rstrip()}
ADB_KEEPER_EOF

cat > /etc/init.d/S99adb-keeper <<'ADB_KEEPER_INIT_EOF'
{KEEPER_INIT_SCRIPT.rstrip()}
ADB_KEEPER_INIT_EOF

chmod 755 /usr/bin/adb-keeper.sh /etc/init.d/S99adb-keeper
rm -f /tmp/.usb_config /etc/.usb_config
echo usb_adb_en >/etc/.usb_config
touch /userdata/adb_keeper_installed 2>/dev/null || true
printf 'installed /usr/bin/adb-keeper.sh and /etc/init.d/S99adb-keeper\\n' >>"$LOG" 2>/dev/null || true
printf 'installed /usr/bin/adb-keeper.sh and /etc/init.d/S99adb-keeper\\n' >>"$SDLOG" 2>/dev/null || true

/etc/init.d/S99adb-keeper start >>"$LOG" 2>&1 || true
/etc/init.d/S50usb-gadget.sh restart >>"$LOG" 2>&1 &
sync
"""

MASK64 = (1 << 64) - 1


def _rotl64(value: int, count: int) -> int:
    value &= MASK64
    return ((value << count) & MASK64) | (value >> (64 - count))


def _fmix64(value: int) -> int:
    value ^= value >> 33
    value = (value * 0xFF51AFD7ED558CCD) & MASK64
    value ^= value >> 33
    value = (value * 0xC4CEB9FE1A85EC53) & MASK64
    value ^= value >> 33
    return value & MASK64


def murmurhash3_x64_128_digest(data: bytes, seed: int = 42) -> bytes:
    """Return MurmurHash3_x64_128 as the daemon's little-endian 16-byte buffer."""
    c1 = 0x87C37B91114253D5
    c2 = 0x4CF5AD432745937F
    h1 = seed & MASK64
    h2 = seed & MASK64

    block_count = len(data) // 16
    for index in range(block_count):
        block = data[index * 16 : (index + 1) * 16]
        k1 = int.from_bytes(block[:8], "little")
        k2 = int.from_bytes(block[8:], "little")

        k1 = (k1 * c1) & MASK64
        k1 = _rotl64(k1, 31)
        k1 = (k1 * c2) & MASK64
        h1 ^= k1

        h1 = _rotl64(h1, 27)
        h1 = (h1 + h2) & MASK64
        h1 = (h1 * 5 + 0x52DCE729) & MASK64

        k2 = (k2 * c2) & MASK64
        k2 = _rotl64(k2, 33)
        k2 = (k2 * c1) & MASK64
        h2 ^= k2

        h2 = _rotl64(h2, 31)
        h2 = (h2 + h1) & MASK64
        h2 = (h2 * 5 + 0x38495AB5) & MASK64

    tail = data[block_count * 16 :]
    k1 = 0
    k2 = 0

    for offset, value in enumerate(tail[:8]):
        k1 ^= value << (offset * 8)
    for offset, value in enumerate(tail[8:]):
        k2 ^= value << (offset * 8)

    if k2:
        k2 = (k2 * c2) & MASK64
        k2 = _rotl64(k2, 33)
        k2 = (k2 * c1) & MASK64
        h2 ^= k2

    if k1:
        k1 = (k1 * c1) & MASK64
        k1 = _rotl64(k1, 31)
        k1 = (k1 * c2) & MASK64
        h1 ^= k1

    length = len(data)
    h1 ^= length
    h2 ^= length

    h1 = (h1 + h2) & MASK64
    h2 = (h2 + h1) & MASK64

    h1 = _fmix64(h1)
    h2 = _fmix64(h2)

    h1 = (h1 + h2) & MASK64
    h2 = (h2 + h1) & MASK64

    # loong_daemon calls ByteToHexString(..., true) on unsigned long[2].
    # In this binary, true selects uppercase hex.
    return h1.to_bytes(8, "little") + h2.to_bytes(8, "little")


def loong_upgrade_hash(ver_inner: int, ota_file: str, ota_size: int) -> tuple[str, str]:
    hash_input = f"{ver_inner}/mnt/sdcard/{ota_file}{ota_size}"
    digest = murmurhash3_x64_128_digest(hash_input.encode("utf-8"), seed=42)
    return digest.hex().upper(), hash_input


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate loong_upgrade and adb_probe.bin for a reversible "
            "Miniloong Pocket 1 ADB enable probe."
        )
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="adb_unlock_sd",
        help="Directory to write SD-root payload files into. Defaults to ./adb_unlock_sd.",
    )
    parser.add_argument(
        "--ver-inner",
        type=int,
        default=DEFAULT_VER_INNER,
        help=f"Firmware internal version to declare. Defaults to {DEFAULT_VER_INNER}.",
    )
    parser.add_argument(
        "--ota-file",
        default=DEFAULT_OTA_FILE,
        help=f"Dummy nonzero OTA filename. Defaults to {DEFAULT_OTA_FILE}.",
    )
    parser.add_argument(
        "--command",
        default=None,
        help="Custom otaCommand to embed. Overrides --mode.",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(COMMAND_MODES),
        default="probe",
        help="Payload command mode. Defaults to probe, which writes markers only.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing loong_upgrade and OTA dummy file in the output directory.",
    )
    return parser.parse_args()


def validate_ota_file_name(name: str) -> None:
    if not name or name in {".", "..", "loong_upgrade", "loong_upgrade.used"}:
        raise SystemExit(f"Unsafe --ota-file value: {name!r}")
    if "/" in name or "\\" in name:
        raise SystemExit("--ota-file must be a simple filename, not a path")


def write_payload(args: argparse.Namespace) -> None:
    validate_ota_file_name(args.ota_file)
    if args.ver_inner < 1:
        raise SystemExit("--ver-inner must be positive")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ota_path = output_dir / args.ota_file
    trigger_path = output_dir / "loong_upgrade"
    for path in (ota_path, trigger_path):
        if path.exists() and not args.force:
            raise SystemExit(f"{path} already exists; rerun with --force to overwrite")

    ota_path.write_bytes(DEFAULT_PROBE_CONTENT)
    ota_hash, hash_input = loong_upgrade_hash(
        ver_inner=args.ver_inner,
        ota_file=args.ota_file,
        ota_size=ota_path.stat().st_size,
    )

    payload = {
        "verInner": args.ver_inner,
        "otaFile": args.ota_file,
        "otaHash": ota_hash,
        "otaCommand": args.command if args.command is not None else COMMAND_MODES[args.mode],
    }
    trigger_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote SD payload directory: {output_dir}")
    print(f"  {trigger_path}")
    print(f"  {ota_path}")
    print(f"otaHash: {ota_hash}")
    print(f"hash input: {hash_input}")
    print()
    print(f"mode: {args.mode if args.command is None else 'custom'}")
    if args.command is None and args.mode == "keeper":
        installer_path = output_dir / "adb-keeper-install.sh"
        installer_path.write_text(KEEPER_INSTALLER, encoding="utf-8")
        print(f"  {installer_path}")
        print("Copy loong_upgrade, adb_probe.bin, and adb-keeper-install.sh to the SD root.")
    else:
        stale_installer = output_dir / "adb-keeper-install.sh"
        if stale_installer.exists():
            stale_installer.unlink()
        print("Copy loong_upgrade and adb_probe.bin to the root of a FAT32 or ext4 SD card.")
    print("Do not use exFAT; stock loong_daemon explicitly ignores exFAT SD media.")


def main() -> None:
    write_payload(parse_args())


if __name__ == "__main__":
    main()
