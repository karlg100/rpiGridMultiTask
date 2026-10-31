# The 192.168.1.243 broker on home-pi (graveyard Photon, freezer monitor)

The graveyard controller (Particle Photon "halloweentree", at 192.168.3.1) and
the basement freezer monitor have 192.168.1.243 built in as their MQTT broker:
Home Assistant's address before it moved to 192.168.1.244. Rather than
reflashing them, home-pi answers on 192.168.1.243 too and runs a small
mosquitto there that bridges only their topics to Home Assistant's broker:

    graveyard/#  ghosts/#  basement_freezer/#  outTopic/#      (both directions)

So `graveyard/command`, `graveyard/color/r|g|b` from the show reach the
Photon, and its `graveyard/debug` messages ("reconnected", "choosing new
random color") and the freezer readings show up on Home Assistant's broker.
Anything connecting on .243 can use only those topics. home-pi's own clients
(director, hue, web) still use 192.168.1.244 directly.

Install (as on home-pi since 2026-10-31):

```sh
sudo install -m 640 -o root -g mosquitto mosquitto-legacy-243.conf /etc/mosquitto/conf.d/legacy-243.conf
sudo nano /etc/mosquitto/conf.d/legacy-243.conf        # remote_password
sudo install -m 644 legacy-243.acl /etc/mosquitto/legacy-243.acl
sudo install -D -m 644 mosquitto-dropin.conf /etc/systemd/system/mosquitto.service.d/legacy-243.conf
sudo systemctl daemon-reload && sudo systemctl enable --now mosquitto
```

The old full-network listener from the temporary broker is kept as
`/etc/mosquitto/conf.d/haunt.conf.disabled`.

**192.168.1.243 must not be handed to anything else.** It used to be client2's
wired address; give client2's wired port a different reservation and keep .243
out of the DHCP pool.
