# Current Status

Updated: 2026-08-28

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
  and optional MQTT configuration.
- SELinux policy for optional VS Code Remote SSH forwarding, with checks
  exposed through `ludusctl doctor`.
- Optional Home Assistant MQTT discovery, player selection, status reporting,
  and lifecycle controls.

## Remaining Validation

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
