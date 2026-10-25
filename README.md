<h1 align="center">ProtonVPN-CLI for MacOS</h1>
<p align="center">
  <img src="resources/images/linux-cli-banner.png" alt="Logo"></img>
</p>

<h3 align="center">An [unofficial] MacOS CLI for ProtonVPN. Written in Python.</h3>

## macOS Compatibility

This fork adapts the ProtonVPN Linux CLI to work natively on macOS by replacing
all Linux-specific subsystems with macOS equivalents:

| Feature | Linux original | macOS replacement |
|---|---|---|
| Default NIC detection | `ip route` / `iproute2` | `netstat -rn -f inet` |
| DNS leak protection | `/etc/resolv.conf` | `networksetup -setdnsservers` |
| IPv6 disable/restore | `ip6tables` | `networksetup -setv6off/automatic` |
| Kill Switch | `iptables` | `pf` (Packet Filter) via `pfctl` |
| Transfer stats | `/sys/class/net/*/statistics` | `netstat -I <iface> -b` |
| IPv6 detection | `/proc/sys/net/ipv6` | `ifconfig <iface>` |

> **Note:** Kill Switch requires `sudo pfctl` access and is enabled/disabled alongside the VPN connection automatically.

## Installation & Updating

#### Installing Dependencies

**Dependencies:**

- homebrew
- openvpn
- dialog (optional, needed for interactive selection)
- python3.8+

```bash
brew install openvpn dialog python3
```

### Manual Installation from source

1. Clone this repository

    `git clone https://github.com/phx/protonvpn-cli-macos`

2. Step into the directory

   `cd protonvpn-cli-macos`

3. Install

    ```bash
    pip3 install --break-system-packages -r requirements.txt
    sudo pip3 install --break-system-packages .
    ```

For updating, pull the latest version:

```bash
git pull
sudo pip3 install --break-system-packages .
```

### How to use

#### For more detailed information, see the extensive [usage guide](https://github.com/ProtonVPN/linux-cli/blob/master/USAGE.md).

| **Command**                       | **Description**                                       |
|:----------------------------------|:------------------------------------------------------|
|`protonvpn init`                   | Initialize ProtonVPN profile.                         |
|`protonvpn connect, c`             | Select a ProtonVPN server and connect to it.          |
|`protonvpn c [servername]`         | Connect to a specified server.                        |
|`protonvpn c -r`                   | Connect to a random server.                           |
|`protonvpn c -f`                   | Connect to the fastest server.                        |
|`protonvpn c --p2p`                | Connect to the fastest P2P server.                    |
|`protonvpn c --cc [countrycode]`   | Connect to the fastest server in a specified country. |
|`protonvpn c --sc`                 | Connect to the fastest Secure Core server.            |
|`protonvpn reconnect, r`           | Reconnect or connect to the last server used.         |
|`protonvpn disconnect, d`          | Disconnect the current session.                       |
|`protonvpn status, s`              | Print connection status.                              |
|`protonvpn c -f --proxy-only`      | Connect in App Proxy mode (routes only apps configured for SOCKS5 127.0.0.1:1080). |
|`protonvpn app-routing`            | Print step-by-step guide for routing Firefox through ProtonVPN. |
|`protonvpn split-tunnel list`      | List IPs/CIDRs excluded from VPN (bypass routes).     |
|`protonvpn split-tunnel add <ip>`  | Add an IP/CIDR to bypass the VPN.                     |
|`protonvpn split-tunnel remove <ip>`| Remove an IP/CIDR from the bypass list.              |
|`protonvpn split-tunnel clear`     | Remove all bypass entries and disable split tunneling.|
|`protonvpn configure`              | Change CLI configuration.                             |
|`protonvpn refresh`                | Refresh OpenVPN configuration and server data.        |
|`protonvpn examples`               | Print example commands.                               |
|`protonvpn --version`              | Display version.                                      |
|`protonvpn --help`                 | Show help message.                                    |

All connect options can be used with the `-p` flag to explicitly specify which transmission protocol is used for that connection (either `udp` or `tcp`).
