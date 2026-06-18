# Miniloong ADB Unlock

Tools for generating SD-card `loong_upgrade` payloads for the Miniloong Pocket 1 stock firmware.

The main use case is enabling the stock ADB daemon on a device whose GUI exposes no ADB switch. The payload pins `/etc/.usb_config` to `usb_adb_en` and sets the ext4 immutable flag (`chattr +i`) on it. The stock `loong_storage` daemon still tries to flip USB to MTP at boot, but every write attempt fails silently and the gadget stays as ADB. After one application, ADB stays up across every boot. No init scripts, no polling, no boot-time race.

Leaf/Jawaka can also apply the same pin from Settings > Network once Leaf is
already bootable. That path writes a Leaf restore marker at
`.umrk/mlp1/adb-enabled`, so the Leaf init hook repairs
the pin at boot when the user has enabled ADB from the UI.

## What This Does

`make_adb_unlock_sd.py` creates an SD-root payload:

```text
loong_upgrade
adb_probe.bin
```

Supported modes:

```text
probe   marker-only test that proves otaCommand execution
adb     one-shot ADB enable via chattr +i on /etc/.usb_config (default)
```

Generate:

```sh
python3 make_adb_unlock_sd.py --force adb_unlock_sd
```

Copy the generated files to the root of a FAT32 or ext4 SD card:

```sh
cp -v adb_unlock_sd/loong_upgrade adb_unlock_sd/adb_probe.bin "/Volumes/SDCARD_NAME/"
sync
diskutil eject "/Volumes/SDCARD_NAME"
```

Do not use exFAT. The stock daemon explicitly ignores exFAT SD media.

## Device Flow

1. Boot the Miniloong Pocket 1 with the SD card inserted.
2. The device shows the stock upgrading screen. This is expected — `loong_daemon` is running the `otaCommand` and the trailing `while true` keeps the daemon from advancing to `UPDATE_CMD_FULL_UPGRADE`.
3. The payload renames `loong_upgrade` to `loong_upgrade.used`, writes `usb_adb_en` to `/etc/.usb_config`, and sets `chattr +i` on it so no later process can overwrite it.
4. Connect your computer to the top USB-C port. While the upgrade screen is still visible:

```sh
adb wait-for-device
adb shell 'lsattr /etc/.usb_config; cat /etc/.usb_config; cat /mnt/sdcard/adb_unlock.log'
```

5. Power off, remove the SD card (or ensure only `loong_upgrade.used` remains), then boot normally.
6. After the GUI appears:

```sh
adb wait-for-device
adb shell 'lsattr /etc/.usb_config; cat /etc/.usb_config; cat /var/run/usb-gadget/funcs'
```

Expected state on every subsequent boot:

```text
lsattr /etc/.usb_config       = ----i---------e-------
/etc/.usb_config              = usb_adb_en
/var/run/usb-gadget/funcs     contains adb
no extra processes or init scripts running
```

## Why The chattr Approach Works

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

The reason ADB normally disappears after boot is that `/loong/loong_storage` flips USB to MTP around 5-10 seconds after the daemon starts. Its strings show both writers:

```text
strings /loong/loong_storage | grep -iE "/etc/\.usb|mtp\.sh|usb_mtp"
/etc/.usb_config
/usr/bin/mtp.sh
usb_mtp_en
```

So `loong_storage` either writes `usb_mtp_en` to `/etc/.usb_config` directly or calls `/usr/bin/mtp.sh 2`, then triggers `/etc/init.d/S50usb-gadget.sh restart`.

There is a `"mtpDisable"` key in `/oem/loong/record/config/loong_storage.cfg` that looks like a clean off switch, but it is not honored as a persistent override: `loong_storage` overwrites the cfg with its hardcoded defaults (`mtpDisable=0`) within seconds of starting on every boot. The disassembly shows `BaseConfig::getDefaultConfigs()` followed by `writeConfig()` early in startup, so any value put in the cfg file is clobbered before it matters.

The fix is to pin `/etc/.usb_config` to `usb_adb_en` and set the ext4 immutable flag on the file:

```sh
echo usb_adb_en > /etc/.usb_config
chattr +i /etc/.usb_config
```

After that, every attempted write fails:

- `mtp.sh 2` runs `rm -rf /etc/.usb_config; echo usb_mtp_en > /etc/.usb_config` — both fail with `Operation not permitted`.
- `loong_storage` writing the file directly fails the same way.
- The subsequent `S50usb-gadget.sh restart` still runs, re-reads `/etc/.usb_config`, sees `usb_adb_en`, and starts the ADB function. The gadget stays as ADB.

The immutable flag is an inode attribute on ext4, so it persists across reboots until something explicitly runs `chattr -i`. Stock firmware does not touch the attribute.

Verified boot-time behavior with the keeper removed:

```text
=== boot+8s ===
usbcfg:        usb_adb_en
funcs:         adb
loong_storage: running
adbd:          running
```

ADB comes up directly during gadget init, not after a polling fix-up.

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
- The command runs before normal launcher startup and with enough privilege to write `/oem`, `/etc`, `/usr/bin`, and `/etc/init.d`.
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

To re-enable the stock MTP behavior from an ADB shell:

```sh
adb shell 'chattr -i /etc/.usb_config; sync; reboot'
```

The first boot after that lets `loong_storage` flip USB back to MTP and ADB disappears again.

To remove an older `adb-keeper` install (from previous versions of this repo):

```sh
adb shell 'rm -f /etc/init.d/S99adb-keeper /usr/bin/adb-keeper.sh /userdata/adb_keeper_installed /userdata/adb_keeper_forced; killall adb-keeper.sh 2>/dev/null || true; sync'
```

## Project Files

```text
make_adb_unlock_sd.py  payload generator
README.md              research notes and usage
```
