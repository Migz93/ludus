# Current Status

Updated: 2026-08-27

## Implemented

- Controller-first Plasma Login player selection for members of the `ludus`
  group, with keyboard/mouse and common controller navigation.
- Version-matched custom Plasma Login greeter with vendor-greeter fallback.
- Ludus Plasma session, loading cover, Steam Big Picture launch, and first-time
  Steam setup fallback to the normal desktop.
- Shared Steam-library management with group-owned game content and private
  per-player Proton/shader data binds.
- Management WebUI for users, libraries, diagnostics, storage, credentials,
  and optional MQTT configuration.
- SELinux policy for the controller bridge and optional VS Code Remote SSH
  forwarding, with checks exposed through `ludusctl doctor`.
- Optional Home Assistant MQTT discovery, player selection, status reporting,
  and lifecycle controls.

## Remaining Validation

- Validate greeter navigation with a physical controller on the target system.
- Validate GPU, display, HDMI/VRR, and Steam Big Picture behaviour on physical
  hardware rather than only the VM.
- Complete end-to-end MQTT validation with a real broker, Home Assistant
  discovery, Wake-on-LAN workflow, and physical greeter.

## Known Limitations

- Steam readiness is detected through its Xwayland Big Picture window; future
  Steam changes may require an update.
- Player switching from Steam is not supported. The active player must sign out
  before another player starts a Ludus session.
