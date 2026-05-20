# Miniloong ADB Keeper

Tools for generating SD-card `loong_upgrade` payloads for the Miniloong Pocket 1 stock firmware.

The main use case is enabling the stock ADB daemon even when the GUI exposes no ADB switch. The persistent `keeper` mode installs a small boot-time script that waits for the stock launcher/storage stack to settle, then switches USB back to ADB if the GUI changes it to MTP.

## What This Does

`make_adb_unlock_sd.py` creates an SD-root payload:

```text
loong_upgrade
adb_probe.bin
adb-keeper-install.sh    # keeper mode only
```

Supported modes:

```text
probe   marker-only test that proves otaCommand execution
adb     one-shot ADB enable during the stock upgrade flow
keeper  persistent boot-time ADB re-enabler
```

The recommended mode is `keeper`:

```sh
python3 make_adb_unlock_sd.py --force --mode keeper adb_keeper_sd
```

Copy the generated files to the root of a FAT32 or ext4 SD card:

```sh
cp -v adb_keeper_sd/loong_upgrade adb_keeper_sd/adb_probe.bin adb_keeper_sd/adb-keeper-install.sh "/Volumes/SDCARD_NAME/"
sync
diskutil eject "/Volumes/SDCARD_NAME"
```

Do not use exFAT. The stock daemon explicitly ignores exFAT SD media.

## Device Flow

1. Boot the Miniloong Pocket 1 with the SD card inserted.
2. The device will show the stock upgrading screen. This is expected.
3. The payload renames `loong_upgrade` to `loong_upgrade.used` on the SD card.
4. In `keeper` mode, it installs:
5. Make sure your compuer is connected to the top USB-C port
```text
/usr/bin/adb-keeper.sh
/etc/init.d/S99adb-keeper
```

6. While the upgrade screen is still visible, test:

```sh
adb wait-for-device
adb shell 'ls -l /usr/bin/adb-keeper.sh /etc/init.d/S99adb-keeper; cat /userdata/adb-keeper-install.log; cat /userdata/adb-keeper.log'
```

7. Power off, remove the SD card or ensure only `loong_upgrade.used` remains, then boot normally.
8. Wait about 60-90 seconds after the GUI appears, then run:

```sh
adb wait-for-device
adb shell 'cat /etc/.usb_config; cat /var/run/usb-gadget/funcs 2>/dev/null; cat /userdata/adb-keeper.log; ps | grep adb-keeper'
```

Expected state:

```text
/etc/.usb_config = usb_adb_en
/var/run/usb-gadget/funcs contains adb
adb-keeper.sh is running
```

## Why A Keeper Is Needed

The stock firmware already contains ADB:

```text
/usr/bin/adbd
/etc/profile.d/adbd.sh
/etc/profile.d/usb-gadget.sh
/etc/init.d/S50usb-gadget.sh
/usr/bin/usb-gadget
/usr/bin/mtp.sh
```

The default profile enables:

```sh
export ADB_TCP_PORT=5555
export ADBD_SHELL=/bin/bash
export USB_FUNCS="adb mtp"
```

However, the stock GUI/storage stack can switch USB mode after boot. The relevant stock helper is:

```sh
/usr/bin/mtp.sh 1  # writes usb_adb_en and restarts USB gadget
/usr/bin/mtp.sh 2  # writes usb_mtp_en and restarts USB gadget
```

Live testing showed the GUI/storage stack changed the device back to MTP after reboot:

```text
adb-keeper starting, delay=45 interval=30
forcing adb cfg=usb_mtp_en funcs=mtp
```

The keeper fixes that by checking after boot and periodically forcing ADB back on.

## How The SD Payload Works

The stock daemon `/loong/loong_daemon` has a startup path named `upgradeFromTfCard()`. During daemon startup, before normal Loong services finish loading, it checks:

```text
/mnt/sdcard/loong_upgrade
```

This file is not a simple autorun script. It is JSON metadata for the stock SD update path:

```json
{
  "verInner": 2147483647,
  "otaFile": "adb_probe.bin",
  "otaHash": "800313800EA919BAB7C9B43DF34E908D",
  "otaCommand": "..."
}
```

The daemon gates execution on:

```text
SD card is not exFAT
loong_upgrade JSON parses
verInner, otaFile, otaHash, and otaCommand members exist
/mnt/sdcard/<otaFile> exists and has nonzero size
otaHash matches the daemon's hash check
verInner is greater than the installed firmware's internal version
```

Only after those checks does it run `otaCommand` through the stock `CMD_EXECUTE` operation path.

The hash input is:

```text
decimal(verInner) + "/mnt/sdcard/" + otaFile + decimal(ota_file_size)
```

The hash function is MurmurHash3 x64 128 with seed `42`. The result must be formatted as uppercase hex. This matters: an earlier lowercase hash failed silently.

The generated payload uses a harmless nonzero `adb_probe.bin` as the required `otaFile`. The command intentionally sleeps forever after doing its work so `loong_daemon` does not continue into:

```text
UPDATE_CMD_FULL_UPGRADE /mnt/sdcard/adb_probe.bin
```

## Security Notes

This firmware's SD update design is powerful and risky:

- A file on removable SD media can trigger privileged command execution during boot.
- The command runs before normal launcher startup and with enough privilege to write `/etc`, `/usr/bin`, and `/etc/init.d`.
- The hash is not a signature. It is a MurmurHash3 value over predictable metadata and file size, so anyone who understands the recipe can generate a valid payload.
- `verInner` is only a monotonic version gate. Setting it to a high signed 32-bit value, such as `2147483647`, bypasses normal older-version rejection on current observed firmware.
- A malicious SD card could persist changes by installing init scripts or modifying system state.
- The daemon also supports copying an SD-card `oem` directory into the mounted `/oem/` partition inside the same validated update path.

This repository exists for owner-controlled research and recovery. Treat payloads as privileged firmware modifications.

## Recovery And Cleanup

The payload renames the trigger to:

```text
loong_upgrade.used
```

If the device is stuck on the upgrade screen, power off and remove the SD card or make sure there is no active `loong_upgrade` file on the card.

To disable the keeper from an ADB shell:

```sh
adb shell 'rm -f /etc/init.d/S99adb-keeper /usr/bin/adb-keeper.sh /userdata/adb_keeper_installed; killall adb-keeper.sh 2>/dev/null || true; sync'
```

To switch back to MTP manually:

```sh
adb shell '/usr/bin/mtp.sh 2'
```

If the keeper is still installed, it may switch the device back to ADB after its next interval.

## Project Files

```text
make_adb_unlock_sd.py  payload generator
README.md              research notes and usage
```

