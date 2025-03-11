
# WireGuard Configuration Settings

# Default server settings
DEFAULT_WG_PORT = 443  # Default port for WireGuard
DEFAULT_WG_MTU = 1440  # Default MTU value

# Peer settings
PERSISTENT_KEEPALIVE = 15  # Seconds

# Client settings
CLIENT_DNS_PRIMARY = "78.157.42.100"  # Primary DNS server
CLIENT_IPV4_BASE = "10.0.0.0/8"  # Base IPv4 address for clients
CLIENT_IPV4_ADDITIONAL_PREFIX = "10.202.10."  # Prefix for additional IPv4 addresses

# DNS configuration
DEFAULT_IPV6_PREFIX = "fd00::"  # IPv6 prefix for client addresses

# Security settings
ALLOWED_IPS = ["0.0.0.0/3", "::/3"]  # Allowed IPs for traffic routing

# Generate WireGuard keys
def generate_wireguard_keys():
    """
    Generate WireGuard private and public keys.
    In a real implementation, you should use the wg command or a proper WireGuard library.
    """
    import base64
    import os
    
    private_key = base64.b64encode(os.urandom(32)).decode('utf-8')
    # This is a simplified version for demonstration
    # In production, you should derive the public key from the private key using WireGuard's algorithms
    public_key = base64.b64encode(os.urandom(32)).decode('utf-8')
    
    return private_key, public_key

# Generate WireGuard config
def create_wireguard_config(private_key, public_key, endpoint, client_ipv4, client_ipv4_add, client_ipv6, dns_servers):
    """
    Create a WireGuard configuration file content.
    
    Args:
        private_key: Client's private key
        public_key: Server's public key
        endpoint: Server endpoint (IP:port)
        client_ipv4: Client's IPv4 address
        client_ipv4_add: Client's additional IPv4 address
        client_ipv6: Client's IPv6 address
        dns_servers: List of DNS servers
    
    Returns:
        str: WireGuard configuration content
    """
    dns_list = ", ".join(dns_servers)
    allowed_ips = ", ".join(ALLOWED_IPS)
    
    config = f"""[Interface]
PrivateKey = {private_key}
Address = {client_ipv4}, {client_ipv4_add}, {client_ipv6}
DNS = {dns_list}
MTU = {DEFAULT_WG_MTU}

[Peer]
PublicKey = {public_key}
AllowedIPs = {allowed_ips}
Endpoint = {endpoint}:{DEFAULT_WG_PORT}
PersistentKeepalive = {PERSISTENT_KEEPALIVE}
"""
    
    return config
