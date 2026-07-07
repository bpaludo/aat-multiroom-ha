# NOTICE

This project is a fork of **[lcglustosa/aat-multiroom-ha](https://github.com/lcglustosa/aat-multiroom-ha)**
by Leandro Lustosa, distributed under the MIT License (see `LICENSE`). The
original copyright is preserved.

Fork maintained by **Palalab** for deploying AAT PMR amplifiers to client Home
Assistant instances. Reviewed against the official *AAT Digital Matrix
Amplifiers API Rev.12* (firmware V3.08+).

## Changes in this fork (v0.3.0)

1. **Reconnection after idle reset.** The AAT resets idle TCP connections after
   `TCPTIMEOUT` seconds. A read that returns EOF now tears the socket down and
   the command is retried once on a fresh connection, so the first command after
   an idle reset no longer fails. Added a timeout on `drain()` too.
2. **Device error codes surfaced.** Rejections (codes 7/8/17/18) are detected
   with framing-safe logic (an error code in the command slot, never mistaken
   for a valid echoed value) and raised as `AatCommandError` → shown in the HA
   UI, instead of being silently swallowed.
3. **Mute re-enabled** on the `media_player` (`VOLUME_MUTE` was removed upstream
   to work around HomeKit; that workaround is now opt-in).
4. **HomeKit hacks are opt-in.** The `light`-as-volume entities and the `TV`
   media-player class only appear when the "HomeKit compatibility" option is on.
   Default is the honest `SPEAKER` class with a real `VOLUME_MUTE`.
5. **Stable identity.** Device and entity `unique_id`s are keyed on the config
   entry_id, not the host IP — the device registry survives a DHCP change.
6. **Topology auto-detected.** Number of zones/inputs is derived from the
   `MODEL` reply (full PMA/PMRH/PMR table) instead of being typed by the user.
7. Shared base entity (`entity.py`), EQ/preamp moved to the device
   Configuration section, expanded tests, faster default poll (20 s).

The upstream project remains the reference for anyone wanting the HomeKit-first
behavior out of the box.
