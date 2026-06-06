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
    "LOG=/userdata/adb_unlock.log; "
    "SDLOG=/mnt/sdcard/adb_unlock.log; "
    "printf 'adb unlock command started\\n' >$LOG 2>/dev/null || true; "
    "printf 'adb unlock command started\\n' >$SDLOG 2>/dev/null || true; "
    "mv /mnt/sdcard/loong_upgrade /mnt/sdcard/loong_upgrade.used 2>/dev/null || true; "
    "if mount -o remount,rw / 2>/dev/null || mount -o remount,rw /dev/root / 2>/dev/null; then "
    # Make sure file is mutable in case a prior install set it.
    "chattr -i /etc/.usb_config 2>/dev/null || true; "
    "if echo usb_adb_en >/etc/.usb_config && chattr +i /etc/.usb_config; then "
    "printf 'pinned /etc/.usb_config = usb_adb_en\\n' >>$LOG 2>/dev/null || true; "
    "printf 'pinned /etc/.usb_config = usb_adb_en\\n' >>$SDLOG 2>/dev/null || true; "
    "else "
    "printf 'failed to pin /etc/.usb_config\\n' >>$LOG 2>/dev/null || true; "
    "printf 'failed to pin /etc/.usb_config\\n' >>$SDLOG 2>/dev/null || true; "
    "fi; "
    "else "
    "printf 'rootfs remount rw failed\\n' >>$LOG 2>/dev/null || true; "
    "printf 'rootfs remount rw failed\\n' >>$SDLOG 2>/dev/null || true; "
    "fi; "
    "sync; "
    "while true; do sleep 3600; done"
)
COMMAND_MODES = {
    "probe": PROBE_ONLY_COMMAND,
    "adb": ADB_ENABLE_COMMAND,
}

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
        default="adb",
        help="Payload command mode. Defaults to adb, which sets mtpDisable=1 and forces /etc/.usb_config to usb_adb_en.",
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
    stale_installer = output_dir / "adb-keeper-install.sh"
    if stale_installer.exists():
        stale_installer.unlink()
    print("Copy loong_upgrade and adb_probe.bin to the root of a FAT32 or ext4 SD card.")
    print("Do not use exFAT; stock loong_daemon explicitly ignores exFAT SD media.")


def main() -> None:
    write_payload(parse_args())


if __name__ == "__main__":
    main()
