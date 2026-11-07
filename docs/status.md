# Current Status

Updated: 2026-11-07

## Implemented

- Controller-first Plasma Login player selection for members of the `ludus`
  group, using KWin's normalised gamepad API alongside mouse interaction.
- Greeter-local two-step confirmation for shutdown and restart.
- Version-matched custom Plasma Login greeter with vendor-greeter fallback.
- Ludus Plasma session, loading cover, Steam Big Picture launch, and first-time
  Steam setup fallback to the normal desktop.
- Shared Steam-library management with group-owned game content and private
  per-player Proton/shader data binds.
- Management WebUI for users, libraries, diagnostics, storage, credentials,
  installed-game inventory, and optional MQTT configuration.
- Disabled-by-default Proton overlay DPI repair with console and per-game
  policy, active-player-only reconciliation, audit backup, and queued restore.
- Disabled-by-default Steam launch policy with ScopeBuddy profiles (adaptive
  native, fixed-resolution upscale, custom), console/per-game controls,
  per-player replace-temporarily or manual override acceptance, and journalled
  restoration.
- Console-wide MangoHud layout and enablement with independent per-game policy,
  private configuration/audit backup, MangoApp selection for managed ScopeBuddy,
  and the existing journalled Steam launch writer and recovery controls.
- SELinux policy for optional VS Code Remote SSH forwarding, with checks
  exposed through `ludusctl doctor`.
- Optional Home Assistant MQTT discovery, player selection, status reporting,
  and lifecycle controls.

## Local Deployment Validation

- Installed through `sudo ./install.sh` on 2026-11-07 with Plasma Login 6.8.2.
  All five Ludus services were active, all 23 doctor checks were healthy, and
  SELinux remained enforcing. The installed MangoHud settings helper responded
  successfully. Overlay rendering and hotkeys still need target validation.

## Remaining Validation

- Exercise MangoHud/MangoApp through both launch paths on Bazzite
  Desktop KDE with NVIDIA, including overlay visibility, metrics, hotkeys,
  two players, conflicts, reset and uninstall recovery. Native OpenGL injection
  is not provided by the normal `MANGOHUD=1` path.

- Validate controller hot-plug and additional controller models against the
  KWin gamepad API on the target system.
- Validate GPU, display, HDMI/VRR, and Steam Big Picture behaviour on physical
  hardware rather than only the VM.
- Complete end-to-end MQTT validation with a real broker, Home Assistant
  discovery, Wake-on-LAN workflow, and physical greeter.

## Known Limitations

- Steam readiness is detected through its Xwayland Big Picture window; future
  Steam changes may require an update.
- Player switching from Steam is not supported. The active player must sign out
  before another player starts a Ludus session.
