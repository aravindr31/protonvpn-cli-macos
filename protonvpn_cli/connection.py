# Standard Libraries
import os
import sys
import subprocess
import time
import shutil
import random
import re
import configparser
import datetime
import zlib
# External Libraries
from dialog import Dialog
# protonvpn-cli Functions
from .logger import logger
from .utils import (
    check_init, pull_server_data, is_connected,
    get_servers, get_server_value, get_config_value,
    set_config_value, get_ip_info, get_country_name,
    get_fastest_server, check_update, get_default_nic,
    get_transferred_data, create_openvpn_config,
    is_ipv6_disabled, patch_passfile, get_gateway,
    get_split_tunnel_ips
)
# Constants
from .constants import (
    CONFIG_DIR, OVPN_FILE, PASSFILE, CONFIG_FILE,
    PROXY_PID_FILE, PROXY_LOG_FILE
)


def dialog(proxy_only=False):
    """Connect to a server with a dialog menu."""
    def show_dialog(headline, choices, stop=False):
        """Show the dialog and process response."""
        d = Dialog(dialog="dialog")

        logger.debug("Showing Dialog: {0}".format(headline))

        code, tag = d.menu(headline, title="ProtonVPN-CLI", choices=choices)
        if code == "ok":
            return tag
        else:
            os.system("clear")
            print("Canceled.")
            sys.exit(1)

    logger.debug("Starting dialog connect")

    # Check if dialog is installed
    dialog_check = subprocess.run(['which', 'dialog'],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
    if not dialog_check.returncode == 0:
        print("'dialog' not found. "
              "Please install dialog via your package manager.")
        logger.debug("dialog not found")
        sys.exit(1)

    pull_server_data()

    features = {0: "Normal", 1: "Secure-Core", 2: "Tor", 4: "P2P"}
    server_tiers = {0: "F", 1: "B", 2: "P"}

    servers = get_servers()

    countries = {}
    for server in servers:
        country = get_country_name(server["ExitCountry"])
        if country not in countries.keys():
            countries[country] = []
        countries[country].append(server["Name"])

    # Fist dialog
    choices = []

    for country in sorted(countries.keys()):
        country_features = []
        for server in countries[country]:
            feat = int(get_server_value(server, "Features", servers))
            if not features[feat] in country_features:
                country_features.append(features[feat])
        choices.append((country, " | ".join(sorted(country_features))))

    country = show_dialog("Choose a country:", choices)
    logger.debug("Country Choice: {0}".format(country))

    # Second dialog
    # lambda sorts servers by Load instead of name
    choices = []
    country_servers = sorted(countries[country],
                             key=lambda s: get_server_value(
                                 s, "Load", servers))

    for servername in country_servers:

        load = str(
            get_server_value(servername, "Load", servers)
        ).rjust(3, " ")

        feature = features[
            get_server_value(servername, 'Features', servers)
        ]

        tier = server_tiers[
            get_server_value(servername, "Tier", servers)
        ]

        choices.append((servername, "Load: {0}% | {1} | {2}".format(
            load, tier, feature
        )))

    server_result = show_dialog("Choose the server to connect:", choices)

    logger.debug("Server Choice: {0}".format(server_result))

    protocol_result = show_dialog(
        "Choose a protocol:", [
            ("UDP", "Better Speed"), ("TCP", "Better Reliability")
        ]
    )

    logger.debug("Protocol Choice: {0}".format(protocol_result))

    os.system("clear")
    openvpn_connect(server_result, protocol_result, proxy_only=proxy_only)


def random_c(protocol=None, proxy_only=False):
    """Connect to a random ProtonVPN Server."""

    logger.debug("Starting random connect")

    if not protocol:
        protocol = get_config_value("USER", "default_protocol")

    servers = get_servers()

    servername = random.choice(servers)["Name"]

    openvpn_connect(servername, protocol, proxy_only=proxy_only)


def fastest(protocol=None, proxy_only=False):
    """Connect to the fastest server available."""

    logger.debug("Starting fastest connect")

    if not protocol:
        protocol = get_config_value("USER", "default_protocol")

    disconnect(passed=True)
    pull_server_data(force=True)

    servers = get_servers()

    # ProtonVPN Features: 1: SECURE-CORE, 2: TOR, 4: P2P
    excluded_features = [1, 2]

    # Filter out excluded features
    server_pool = []
    for server in servers:
        if server["Features"] not in excluded_features:
            server_pool.append(server)

    fastest_server = get_fastest_server(server_pool)
    openvpn_connect(fastest_server, protocol, proxy_only=proxy_only)


def country_f(country_code, protocol=None, proxy_only=False):
    """Connect to the fastest server in a specific country."""
    logger.debug("Starting fastest country connect")

    if not protocol:
        protocol = get_config_value("USER", "default_protocol")

    country_code = country_code.strip().upper()

    disconnect(passed=True)
    pull_server_data(force=True)

    servers = get_servers()

    # ProtonVPN Features: 1: SECURE-CORE, 2: TOR, 4: P2P
    excluded_features = [1, 2]

    # Filter out excluded features and countries
    server_pool = []
    for server in servers:
        if server["Features"] not in excluded_features and server["ExitCountry"] == country_code:
            server_pool.append(server)

    if len(server_pool) == 0:
        print(
            "[!] No Server in country {0} found\n".format(country_code)
            + "[!] Please choose a valid country"
        )
        logger.debug("No server in country {0}".format(country_code))
        sys.exit(1)

    fastest_server = get_fastest_server(server_pool)
    openvpn_connect(fastest_server, protocol, proxy_only=proxy_only)


def feature_f(feature, protocol=None, proxy_only=False):
    """Connect to the fastest server in a specific country."""
    logger.debug(
        "Starting fastest feature connect with feature {0}".format(feature)
    )

    if not protocol:
        protocol = get_config_value("USER", "default_protocol")

    disconnect(passed=True)
    pull_server_data(force=True)

    servers = get_servers()

    server_pool = [s for s in servers if s["Features"] == feature]

    if len(server_pool) == 0:
        logger.debug("No servers found with users selection. Exiting.")
        print("[!] No servers found with your selection.")
        sys.exit(1)

    fastest_server = get_fastest_server(server_pool)
    openvpn_connect(fastest_server, protocol, proxy_only=proxy_only)


def direct(user_input, protocol=None, proxy_only=False):
    """Connect to a single given server directly"""

    logger.debug("Starting direct connect with {0}".format(user_input))
    pull_server_data()

    if not protocol:
        protocol = get_config_value("USER", "default_protocol")

    # For short format (UK-03/HK#5-Tor | Normal Servers/Tor Servers)
    re_short = re.compile(r"^((\w\w)(-|#)?(\d{1,3})-?(TOR)?)$")
    # For long format (IS-DE-01 | Secure-Core/Free/US Servers)
    re_long = re.compile(
        r"^(((\w\w)(-|#)?([A-Z]{2}|FREE))(-|#)?(\d{1,3})-?(TOR)?)$"
    )

    user_input = user_input.upper()

    if re_short.search(user_input):
        user_server = re_short.search(user_input)

        country_code = user_server.group(2)
        number = user_server.group(4).lstrip("0")
        tor = user_server.group(5)
        servername = "{0}#{1}".format(country_code, number) +\
                     "{0}".format('-' + tor if tor is not None else '')
    elif re_long.search(user_input):
        user_server = re_long.search(user_input)
        country_code = user_server.group(3)
        country_code2 = user_server.group(5)
        number = user_server.group(7).lstrip("0")
        tor = user_server.group(8)
        servername = "{0}-{1}#{2}".format(country_code,
                                          country_code2, number) + \
                     "{0}".format('-' + tor if tor is not None else '')
    else:
        print(
            "[!] '{0}' is not a valid servername\n".format(user_input)
            + "[!] Please enter a valid servername"
        )
        logger.debug("'{0}' is not a valid servername'".format(user_input))
        sys.exit(1)

    servers = get_servers()

    if servername not in [server["Name"] for server in servers]:
        print(
            "[!] {0} doesn't exist, ".format(servername)
            + "is under maintenance, or inaccessible with your plan.\n"
            "[!] Please enter a different, valid servername."
        )
        logger.debug("{0} doesn't exist".format(servername))
        sys.exit(1)

    openvpn_connect(servername, protocol, proxy_only=proxy_only)


def reconnect():
    """Reconnect to the last VPN Server."""

    logger.debug("Starting reconnect")

    try:
        servername = get_config_value("metadata", "connected_server")
        protocol = get_config_value("metadata", "connected_proto")
    except KeyError:
        logger.debug("No previous connection found")
        print(
            "[!] Couldn't find a previous connection\n"
            "[!] Please connect normally first"
        )
        sys.exit(1)

    try:
        proxy_only = get_config_value("metadata", "proxy_only") == "1"
    except KeyError:
        proxy_only = False

    openvpn_connect(servername, protocol, proxy_only=proxy_only)


def disconnect(passed=False):
    """Disconnect VPN if a connection is present."""

    logger.debug("Initiating disconnect")

    if is_connected():
        if passed:
            print("There is already a VPN connection running.")
            print("Terminating previous connection...")
        subprocess.run(["pkill", "openvpn"])

        time.sleep(0.5)
        timer_start = time.time()

        while True:
            if is_connected():
                if time.time() - timer_start <= 5:
                    subprocess.run(["pkill", "openvpn"])
                    time.sleep(0.2)
                else:
                    subprocess.run(
                        ["pkill", "-9", "openvpn"])
                    logger.debug("SIGKILL sent")
                    break
            else:
                break

        if is_connected():
            print("[!] Could not terminate OpenVPN process.")
            sys.exit(1)
        else:
            manage_dns("restore")
            manage_ipv6("restore")
            manage_killswitch("restore")
            manage_split_tunnel("remove")
            stop_app_proxy()
            try:
                set_config_value("metadata", "proxy_only", "0")
            except Exception:
                pass
            logger.debug("Disconnected")
            if not passed:
                print("Disconnected.")
    else:
        if not passed:
            print("No connection found.")
        manage_dns("restore")
        manage_ipv6("restore")
        manage_killswitch("restore")
        manage_split_tunnel("remove")
        stop_app_proxy()
        try:
            set_config_value("metadata", "proxy_only", "0")
        except Exception:
            pass
        logger.debug("No connection found")


def status():
    """
    Display the current VPN status

    Showing connection status (connected/disconnected),
    current IP, server name, country, server load
    """
    check_init()
    logger.debug("Getting VPN Status")

    # Quit if not connected
    if not is_connected():
        logger.debug("Disconnected")
        print("Status:     Disconnected")
        if os.path.isfile(os.path.join(CONFIG_DIR, "pf_killswitch.backup")):
            print("[!] Kill Switch is currently active.")
            logger.debug("Kill Switch active while VPN disconnected")
        else:
            ip, isp = get_ip_info()
            print("IP:         {0}".format(ip))
            print("ISP:        {0}".format(isp))
        return

    pull_server_data()

    try:
        connected_server = get_config_value("metadata", "connected_server")
        connected_protocol = get_config_value("metadata", "connected_proto")
        dns_server = get_config_value("metadata", "dns_server")
    except KeyError:
        print("It looks like there never was a connection.\n"
              "Please connect with 'protonvpn connect' first.")
        sys.exit(1)

    # Check if the VPN Server is reachable
    ping = subprocess.run(["ping", "-c", "1", dns_server],
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    if ping.returncode != 0:
        logger.debug("Could not reach VPN server")
        print("[!] Could not reach the VPN Server")
        print("[!] You may want to reconnect with 'protonvpn reconnect'")
        return

    servers = get_servers()

    ip, isp = get_ip_info()

    # Collect Information
    all_features = {0: "Normal", 1: "Secure-Core", 2: "Tor", 4: "P2P"}

    logger.debug("Collecting status information")
    country_code = get_server_value(connected_server, "ExitCountry", servers)
    country = get_country_name(country_code)
    city = get_server_value(connected_server, "City", servers)
    load = get_server_value(connected_server, "Load", servers)
    feature = get_server_value(connected_server, "Features", servers)
    last_connection = get_config_value("metadata", "connected_time")
    connection_time = time.time() - int(last_connection)

    if os.path.isfile(os.path.join(CONFIG_DIR, "pf_killswitch.backup")):
        killswitch_on = True
    else:
        killswitch_on = False
    killswitch_status = "Enabled" if killswitch_on else "Disabled"
    # Turn time into human readable format and trim microseconds
    connection_time = str(datetime.timedelta(
        seconds=connection_time)).split(".")[0]

    try:
        is_proxy_mode = get_config_value("metadata", "proxy_only") == "1"
    except KeyError:
        is_proxy_mode = False

    if is_proxy_mode or is_app_proxy_running():
        try:
            vpn_iface = get_config_value("metadata", "vpn_interface")
        except KeyError:
            vpn_iface = "proton0"

        logger.debug("Printing status (proxy mode)")
        print(
            "Status:       Connected (App Proxy Mode)\n"
            + "Proxy:        127.0.0.1:1080 (SOCKS5)\n"
            + "Interface:    {0}\n".format(vpn_iface)
            + "Time:         {0}\n".format(connection_time)
            + "System IP:    {0} ({1})\n".format(ip, isp)
            + "Server:       {0}\n".format(connected_server)
            + "Country:      {0} ({1})\n".format(country, city)
            + "Features:     {0}\n".format(all_features[feature])
            + "Protocol:     {0}\n".format(connected_protocol.upper())
            + "Kill Switch:  Disabled (Bypassed for App Proxy)\n"
            + "Firefox setup: SOCKS5 127.0.0.1:1080 (Proxy DNS enabled)"
        )
        return

    tx_amount, rx_amount = get_transferred_data()

    # Print Status Output
    logger.debug("Printing status")
    print(
        "Status:       Connected\n"
        + "Time:         {0}\n".format(connection_time)
        + "IP:           {0}\n".format(ip)
        + "Server:       {0}\n".format(connected_server)
        + "Features:     {0}\n".format(all_features[feature])
        + "Protocol:     {0}\n".format(connected_protocol.upper())
        + "Kill Switch:  {0}\n".format(killswitch_status)
        + "Country:      {0}\n".format(country)
        + "City:         {0}\n".format(city)
        + "Load:         {0}%\n".format(load)
        + "Received:     {0}\n".format(rx_amount)
        + "Sent:         {0}".format(tx_amount)
    )


def start_app_proxy(iface_name, dns_server=None, port=1080):
    """Start the SOCKS5 proxy daemon bound to the VPN interface."""
    stop_app_proxy()
    cmd = [
        sys.executable, "-m", "protonvpn_cli.socks5_proxy",
        iface_name, str(dns_server) if dns_server else "None",
        str(port), PROXY_LOG_FILE
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )
    with open(PROXY_PID_FILE, "w") as f:
        f.write(str(proc.pid))
    logger.debug("Started SOCKS5 proxy daemon with PID {0} on port {1}".format(proc.pid, port))
    return proc.pid


def stop_app_proxy():
    """Stop the SOCKS5 proxy daemon if running."""
    if os.path.isfile(PROXY_PID_FILE):
        try:
            with open(PROXY_PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 15)
            time.sleep(0.2)
            try:
                os.kill(pid, 0)
                os.kill(pid, 9)
            except OSError:
                pass
        except Exception as e:
            logger.debug("Error stopping proxy PID: {0}".format(e))
        finally:
            if os.path.isfile(PROXY_PID_FILE):
                os.remove(PROXY_PID_FILE)
    subprocess.run(["pkill", "-f", "protonvpn_cli.socks5_proxy"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def is_app_proxy_running():
    """Return True if SOCKS5 proxy process is active."""
    if not os.path.isfile(PROXY_PID_FILE):
        return False
    try:
        with open(PROXY_PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def openvpn_connect(servername, protocol, proxy_only=False):
    """Connect to VPN Server."""

    logger.debug("Initiating OpenVPN connection (proxy_only={0})".format(proxy_only))
    logger.debug(
        "Connecting to {0} via {1}".format(servername, protocol.upper())
    )

    port = {"udp": 1194, "tcp": 443}

    servers = get_servers()
    subservers = get_server_value(servername, "Servers", servers)
    ip_list = [subserver["EntryIP"] for subserver in subservers]

    # Create OpenVPN config with proxy_only setting
    create_openvpn_config(serverlist=ip_list, protocol=protocol, ports=[port[protocol.lower()]], proxy_only=proxy_only)

    disconnect(passed=True)

    # Save the pre-VPN default gateway so split tunnel routes can use it
    try:
        pre_vpn_gateway = get_gateway()
        set_config_value("metadata", "pre_vpn_gateway", pre_vpn_gateway)
        logger.debug("Pre-VPN gateway saved: {0}".format(pre_vpn_gateway))
    except RuntimeError:
        pre_vpn_gateway = None
        logger.debug("Could not determine pre-VPN gateway")

    old_ip, _ = get_ip_info()

    mode_str = " (App Proxy Mode)" if proxy_only else ""
    print("Connecting to {0} via {1}{2}...".format(servername, protocol.upper(), mode_str))

    patch_passfile(PASSFILE)

    with open(os.path.join(CONFIG_DIR, "ovpn.log"), "w+") as f:
        subprocess.Popen(
            [
                "openvpn",
                "--config", OVPN_FILE,
                "--auth-user-pass", PASSFILE,
                "--dev", "proton0",
                "--dev-type", "tun"
            ],
            stdout=f, stderr=f
        )

    logger.debug("OpenVPN process started")
    time_start = time.time()

    with open(os.path.join(CONFIG_DIR, "ovpn.log"), "r") as f:
        while True:
            content = f.read()
            f.seek(0)
            # If connection successful
            if "Initialization Sequence Completed" in content:
                dns_dhcp_regex = re.compile(
                    r"(dhcp-option DNS )"
                    r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
                )

                dns_dhcp = dns_dhcp_regex.search(content)
                dns_server = dns_dhcp.group(2) if dns_dhcp else None
                if dns_server:
                    set_config_value("metadata", "dns_server", dns_server)

                if proxy_only:
                    # In App Proxy mode: do NOT change system DNS or firewall.
                    # Find tunnel interface from log
                    vpn_dev_match = re.search(r"(?:TUN\/TAP device|Opened utun device|ifconfig\s+)(utun\d+|proton0)", content)
                    vpn_dev = vpn_dev_match.group(1) if vpn_dev_match else "proton0"

                    start_app_proxy(vpn_dev, dns_server=dns_server, port=1080)
                    set_config_value("metadata", "proxy_only", "1")
                    set_config_value("metadata", "vpn_interface", vpn_dev)

                    print()
                    print("[✓] Connected to ProtonVPN in App Proxy mode!")
                    print("[✓] System internet traffic remains UNTOUCHED on your regular Wi-Fi/LAN.")
                    print("[✓] Local SOCKS5 proxy is active on 127.0.0.1:1080 (tunnel interface: {0}).".format(vpn_dev))
                    print()
                    print("To route Firefox (and Firefox only) through this VPN:")
                    print("  1. In Firefox, open Settings -> General -> Network Settings -> Settings...")
                    print("  2. Select 'Manual proxy configuration'")
                    print("  3. SOCKS Host: 127.0.0.1   Port: 1080   (Select SOCKS v5)")
                    print("  4. Check 'Proxy DNS when using SOCKS v5' (prevents DNS leaks)")
                    print("  5. Click OK")
                    print()
                    print("All Firefox tabs now route through ProtonVPN; all other apps use normal internet.")
                    logger.debug("App Proxy connected successfully")
                    break
                else:
                    set_config_value("metadata", "proxy_only", "0")
                    # Enable DNS Leak Protection
                    if dns_server:
                        manage_dns("leak_protection", dns_server)
                    else:
                        print(
                            "[!] Could not enable DNS Leak Protection!\n"
                            "[!] Make sure you are protected!"
                        )
                    manage_ipv6("disable")
                    manage_killswitch("enable", proto=protocol.lower(),
                                      port=port[protocol.lower()])

                    # Apply split tunneling routes via the pre-VPN gateway
                    if pre_vpn_gateway:
                        manage_split_tunnel("apply", gateway=pre_vpn_gateway)
                    else:
                        logger.debug("Skipping split tunnel: no pre-VPN gateway")

                    new_ip, _ = get_ip_info()
                    if old_ip == new_ip:
                        logger.debug("Failed to connect. IP didn't change")
                        print("[!] Connection failed. Reverting all changes...")
                        disconnect(passed=True)
                    print("Connected!")
                    logger.debug("Connection successful")
                    break
            # If Authentication failed
            elif "AUTH_FAILED" in content:
                print(
                    "[!] Authentication failed. \n"
                    "[!] Please make sure that your "
                    "Username and Password is correct."
                )
                logger.debug("Authentication failure")
                sys.exit(1)
            # Stop after 45s
            elif time.time() - time_start >= 45:
                print("Connection failed.")
                logger.debug("Connection failed after 45 Seconds")
                sys.exit(1)
            time.sleep(0.1)

    # Write connection info into configuration file
    logger.debug("Writing connection info to file")
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    config["metadata"]["connected_server"] = servername
    config["metadata"]["connected_proto"] = protocol
    config["metadata"]["connected_time"] = str(int(time.time()))

    with open(CONFIG_FILE, "w+") as f:
        config.write(f)

    check_update()


def manage_dns(mode, dns_server=False):
    """
    Manage DNS to circumvent DNS Leaks on macOS.

    Uses networksetup to set/restore DNS per network service.
    Has 2 modes (string): leak_protection / restore
      leak_protection: Set ProtonVPN DNS on the active network service.
      restore: Revert DNS to DHCP-provided (empty list).
    """

    backupfile = os.path.join(CONFIG_DIR, "dns.backup")

    def get_active_network_service():
        """Return the macOS network service name that has the default route."""
        default_nic = get_default_nic()
        # Map device name → network service name via networksetup
        result = subprocess.run(
            ["networksetup", "-listnetworkserviceorder"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        service = None
        lines = result.stdout.decode().splitlines()
        for i, line in enumerate(lines):
            if "Device: {0})".format(default_nic) in line:
                # Previous line is like "(1) Wi-Fi"
                prev = lines[i - 1].strip()
                service = re.sub(r"^\(\d+\)\s+", "", prev)
                break
        if not service:
            # Fall back to scanning for a service whose device matches
            logger.debug("Could not map NIC {0} to a service, using Wi-Fi".format(default_nic))
            service = "Wi-Fi"
        return service

    if mode == "leak_protection":
        logger.debug("DNS Leak Protection initiated (macOS)")

        # Check for custom DNS Server
        if not int(get_config_value("USER", "dns_leak_protection")):
            if get_config_value("USER", "custom_dns") == "None":
                logger.debug("DNS Leak Protection is disabled")
                return
            else:
                dns_server = get_config_value("USER", "custom_dns")
                logger.debug("Using custom DNS")
        else:
            logger.debug("DNS Leak Protection is enabled")

        if not dns_server:
            raise Exception("No DNS Server has been provided.")

        service = get_active_network_service()

        # Back up current DNS servers
        current_dns = subprocess.run(
            ["networksetup", "-getdnsservers", service],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        current_dns_output = current_dns.stdout.decode().strip()
        with open(backupfile, "w") as f:
            f.write("{0}\n{1}\n".format(service, current_dns_output))
        logger.debug("DNS backup written for service: {0}".format(service))

        # Set ProtonVPN DNS
        dns_entries = dns_server.split()
        subprocess.run(
            ["networksetup", "-setdnsservers", service] + dns_entries,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        logger.debug("Set DNS to {0} for {1}".format(dns_entries, service))

        # Flush DNS cache on macOS
        subprocess.run(
            ["dscacheutil", "-flushcache"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        subprocess.run(
            ["killall", "-HUP", "mDNSResponder"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        # Store hash of current DNS state
        with open(backupfile, "rb") as f:
            filehash = zlib.crc32(f.read())
        set_config_value("metadata", "resolvconf_hash", filehash)

    elif mode == "restore":
        logger.debug("Restoring DNS (macOS)")
        if os.path.isfile(backupfile):
            with open(backupfile, "r") as f:
                lines = f.readlines()
            service = lines[0].strip()
            # The rest of the lines are the old DNS servers (or the "no servers" message)
            old_dns_lines = [l.strip() for l in lines[1:] if l.strip()]

            # If the backup says "There aren't any DNS Servers set on <service>."
            # that means DNS was set by DHCP — restore to empty (DHCP)
            if not old_dns_lines or "aren't any" in " ".join(old_dns_lines):
                subprocess.run(
                    ["networksetup", "-setdnsservers", service, "empty"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                logger.debug("Restored DNS to DHCP for {0}".format(service))
            else:
                subprocess.run(
                    ["networksetup", "-setdnsservers", service] + old_dns_lines,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                logger.debug("Restored DNS to {0} for {1}".format(old_dns_lines, service))

            # Flush DNS cache
            subprocess.run(["dscacheutil", "-flushcache"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["killall", "-HUP", "mDNSResponder"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            os.remove(backupfile)
            logger.debug("dns.backup removed")
        else:
            logger.debug("No DNS backup found")
    else:
        raise Exception("Invalid argument provided. "
                        "Mode must be 'restore' or 'leak_protection'")


def manage_ipv6(mode):
    """
    Disable and Enable IPv6 to circumvent IPv6 leaks on macOS.

    Has 2 modes (string): disable / restore.
    disable: Disables IPv6 on the active network service.
    restore: Re-enables IPv6 (sets back to Automatic).
    """

    ipv6_backupfile = os.path.join(CONFIG_DIR, "ipv6.backup")

    def get_active_service_for_nic(nic):
        """Map a NIC device name to its macOS network service name."""
        result = subprocess.run(
            ["networksetup", "-listnetworkserviceorder"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        lines = result.stdout.decode().splitlines()
        for i, line in enumerate(lines):
            if "Device: {0})".format(nic) in line:
                prev = lines[i - 1].strip()
                service = re.sub(r"^\(\d+\)\s+", "", prev)
                return service
        return "Wi-Fi"

    if mode == "disable":
        logger.debug("Disabling IPv6 (macOS)")

        if os.path.isfile(ipv6_backupfile):
            logger.debug("IPv6 backup exists, restoring first")
            manage_ipv6("restore")

        if is_ipv6_disabled():
            logger.debug("IPv6 is disabled or unavailable, skipping")
            return

        try:
            default_nic = get_default_nic()
        except RuntimeError:
            logger.debug("Could not determine NIC for IPv6 disable")
            return

        service = get_active_service_for_nic(default_nic)

        # Check current IPv6 state before disabling
        ipv6_state = subprocess.run(
            ["networksetup", "-getinfo", service],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        with open(ipv6_backupfile, "w") as f:
            f.write("{0}\n".format(service))
        logger.debug("IPv6 backup written for service: {0}".format(service))

        subprocess.run(
            ["networksetup", "-setv6off", service],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        logger.debug("IPv6 disabled for {0}".format(service))

    elif mode == "restore":
        logger.debug("Restoring IPv6 (macOS)")
        if not os.path.isfile(ipv6_backupfile):
            logger.debug("No IPv6 backup found")
            return

        with open(ipv6_backupfile, "r") as f:
            service = f.readline().strip()

        subprocess.run(
            ["networksetup", "-setv6automatic", service],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        logger.debug("IPv6 restored to Automatic for {0}".format(service))

        os.remove(ipv6_backupfile)
        logger.debug("ipv6.backup removed")

    else:
        raise Exception("Invalid argument provided. "
                        "Mode must be 'disable' or 'restore'")


def manage_killswitch(mode, proto=None, port=None):
    """
    Disable and enable the VPN Kill Switch on macOS using pf (Packet Filter).

    The Kill Switch adds pf rules that only allow traffic through the VPN
    tunnel interface. If OpenVPN stops unexpectedly, all internet traffic is
    blocked, preventing leaks.

    Modes:
      enable  – Install pf kill switch anchor rules.
      restore – Remove pf kill switch anchor rules.
    """

    backupfile = os.path.join(CONFIG_DIR, "pf_killswitch.backup")
    anchor_name = "protonvpn_killswitch"

    if mode == "restore":
        logger.debug("Restoring pf (removing kill switch)")
        if os.path.isfile(backupfile):
            # Flush our anchor
            subprocess.run(
                ["pfctl", "-a", anchor_name, "-F", "all"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            logger.debug("pf anchor {0} flushed".format(anchor_name))
            os.remove(backupfile)
            logger.debug("pf_killswitch.backup removed")
        else:
            logger.debug("No pf backup found")
        return

    # Stop if Kill Switch is disabled in config
    if not int(get_config_value("USER", "killswitch")):
        return

    if mode == "enable":
        logger.debug("Enabling Kill Switch via pf")

        # Determine the VPN tun device from the openvpn log
        with open(os.path.join(CONFIG_DIR, "ovpn.log"), "r") as f:
            content = f.read()
        device_match = re.search(r"(TUN\/TAP device) (.+) opened", content)
        if not device_match:
            print("[!] Kill Switch activation failed. "
                  "VPN device couldn't be determined.")
            logger.debug("Kill Switch failed: no device in ovpn.log")
            return
        vpn_device = device_match.group(2)
        logger.debug("VPN device for Kill Switch: {0}".format(vpn_device))

        try:
            default_nic = get_default_nic()
        except RuntimeError:
            print("[!] Kill Switch activation failed. "
                  "Could not determine default NIC.")
            return

        # Build pf rules for the anchor
        # Allow loopback, VPN tunnel, and the one UDP/TCP port used by openvpn.
        # Block everything else on the physical NIC.
        allow_lan = ""
        if int(get_config_value("USER", "killswitch")) == 2:
            # Determine LAN subnet
            lan_info = subprocess.run(
                ["ifconfig", default_nic],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            lan_cidr = None
            for line in lan_info.stdout.decode().splitlines():
                line = line.strip()
                if line.startswith("inet "):
                    parts = line.split()
                    # parts: inet <ip> netmask <hex_mask> broadcast <bcast>
                    try:
                        ip_str = parts[1]
                        # macOS reports netmask as hex (0xffffff00)
                        hex_mask = parts[3]
                        mask_int = int(hex_mask, 16)
                        import ipaddress as _ipa
                        ip_obj = _ipa.IPv4Interface(
                            "{0}/{1}".format(ip_str, mask_int)
                        )
                        lan_cidr = str(ip_obj.network)
                    except Exception:
                        pass
                    break
            if lan_cidr:
                allow_lan = (
                    "pass out on {nic} to {net} keep state\n"
                    "pass in  on {nic} from {net} keep state\n"
                ).format(nic=default_nic, net=lan_cidr)

        pf_rules = (
            "# ProtonVPN Kill Switch — managed by protonvpn-cli\n"
            "# Allow loopback\n"
            "pass quick on lo0 all\n"
            "# Allow traffic on VPN tunnel\n"
            "pass quick on {vpn} all\n"
            "# Allow outgoing OpenVPN handshake on physical NIC\n"
            "pass out quick on {nic} proto {proto} to any port {port} keep state\n"
            "pass in  quick on {nic} proto {proto} from any port {port} keep state\n"
            "{lan}"
            "# Block everything else on physical NIC\n"
            "block on {nic} all\n"
        ).format(
            vpn=vpn_device,
            nic=default_nic,
            proto=proto.lower(),
            port=port,
            lan=allow_lan
        )

        # Write pf anchor rules to a temp file and load them
        pf_rules_file = os.path.join(CONFIG_DIR, "pf_killswitch.rules")
        with open(pf_rules_file, "w") as f:
            f.write(pf_rules)

        # Mark backup so restore knows the switch is active
        with open(backupfile, "w") as f:
            f.write(vpn_device + "\n")

        # Load rules into anchor
        load = subprocess.run(
            ["pfctl", "-a", anchor_name, "-f", pf_rules_file],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if load.returncode != 0:
            print("[!] Failed to load pf kill switch rules.")
            logger.debug("pfctl load error: {0}".format(load.stderr.decode()))
            os.remove(backupfile)
        else:
            # Enable pf if not already enabled
            subprocess.run(
                ["pfctl", "-e"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            logger.debug("Kill Switch enabled via pf anchor")


def manage_split_tunnel(mode, gateway=None):
    """
    Manage split tunneling routes on macOS using the system `route` command.

    Split tunneling routes bypass the VPN and go directly through the
    original default gateway. This is applied AFTER OpenVPN connects so
    that we have a real gateway address to point routes at.

    Modes:
      apply   – Add bypass routes for all IPs in split_tunnel.txt.
      remove  – Delete previously added bypass routes.
      add     – Add a single bypass route (gateway=(ip, netmask, gw)).
      delete  – Delete a single bypass route (gateway=(ip, netmask)).
    """

    try:
        split_enabled = int(get_config_value("USER", "split_tunnel"))
    except KeyError:
        split_enabled = 0

    if mode in ("apply", "remove") and not split_enabled:
        logger.debug("Split tunneling disabled, skipping")
        return

    ips = get_split_tunnel_ips()

    def _route_add(ip, netmask, gw):
        if netmask == "255.255.255.255":
            cmd = ["route", "add", "-host", ip, gw]
        else:
            cmd = ["route", "add", "-net", ip, "-netmask", netmask, gw]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        err = res.stderr.decode().strip()
        if res.returncode == 0 or "File exists" in err:
            return True, err
        return False, err

    def _route_del(ip, netmask):
        if netmask == "255.255.255.255":
            cmd = ["route", "delete", "-host", ip]
        else:
            cmd = ["route", "delete", "-net", ip, "-netmask", netmask]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        err = res.stderr.decode().strip()
        if res.returncode == 0 or "not in table" in err or "No such process" in err:
            return True, err
        return False, err

    if mode == "apply":
        if not gateway:
            logger.debug("No gateway provided for split tunnel apply")
            return
        if not ips:
            logger.debug("Split tunnel file is empty, nothing to route")
            return

        logger.debug("Applying split tunnel routes via gateway {0}".format(gateway))
        for ip, netmask, original in ips:
            ok, err = _route_add(ip, netmask, gateway)
            if ok:
                logger.debug("Split route added/verified: {0}/{1} via {2}".format(
                    ip, netmask, gateway))
            else:
                logger.debug("Failed to add route {0}: {1}".format(original, err))

    elif mode == "remove":
        logger.debug("Removing split tunnel routes")
        for ip, netmask, original in ips:
            ok, err = _route_del(ip, netmask)
            if ok:
                logger.debug("Split route removed: {0}".format(original))
            else:
                logger.debug("Route delete note for {0}: {1}".format(original, err))

    elif mode == "add":
        if not gateway or len(gateway) != 3:
            raise ValueError("mode='add' requires gateway=(ip, netmask, gw)")
        ip, netmask, gw = gateway
        ok, err = _route_add(ip, netmask, gw)
        if not ok:
            print("[!] Failed to add route: {0}".format(err))
            logger.debug("route add failed: {0}".format(err))
        else:
            logger.debug("Dynamic split route added: {0}/{1} via {2}".format(ip, netmask, gw))

    elif mode == "delete":
        if not gateway or len(gateway) < 2:
            raise ValueError("mode='delete' requires gateway=(ip, netmask)")
        ip, netmask = gateway[0], gateway[1]
        ok, err = _route_del(ip, netmask)
        if not ok:
            print("[!] Failed to delete route: {0}".format(err))
            logger.debug("route delete failed: {0}".format(err))
        else:
            logger.debug("Dynamic split route deleted: {0}/{1}".format(ip, netmask))

    else:
        raise ValueError("Invalid mode. Must be: apply, remove, add, delete")
