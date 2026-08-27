# Home Assistant MQTT

## Purpose

The optional MQTT integration uses Home Assistant MQTT Discovery to expose a
Ludus device with a player selector, active-session and active-player status,
lifecycle/error sensors, and one-shot Sign out, Restart, and Shut down buttons.

Configure it from the WebUI's **MQTT** page. Keep the broker on a trusted
network, use TLS when supported, and give Ludus a dedicated account restricted
to the necessary topics.

## Commands And Retention

Selecting a player publishes a retained request, allowing the selection to be
made before the PC is powered on. Once the machine reaches the Ludus greeter,
it consumes the request, starts the selected user's session, and resets the
selector to `Inactive`. Selecting `Inactive` clears a pending request.

After hand-off to the greeter, player requests expire after two minutes and are
rejected while another Ludus session is active.

Only player-selection messages may be retained. Sign out, restart, and shut
down use non-retained button messages with payload `PRESS`; Ludus rejects and
clears retained lifecycle commands to avoid replay after a reconnect or reboot.

## Security

Anyone permitted to publish Ludus commands can start an enrolled account
without its password, sign out the active player, or power-cycle the machine.
Do not expose broker credentials or MQTT topics to untrusted users. Use VPN or
other secured remote access for Home Assistant rather than making the broker
internet-accessible.
