"""Security configuration - SSH hardening, firewall."""

import logging

from paramiko import SSHClient

from scripts.deploy.services.ssh.connection import exec_command
from scripts.deploy.utils.ip_detection import get_current_ip

logger = logging.getLogger(__name__)


def is_fail2ban_installed(conn: SSHClient) -> bool:
    """Check if fail2ban is installed on remote host."""
    code, out, _ = exec_command(conn, "which fail2ban-server 2>/dev/null")
    return code == 0 and "fail2ban" in out


def configure_ssh_security(conn: SSHClient, current_ip: str) -> None:
    """Configure SSH security - allow current IP, harden config."""
    script = f"""
# Allow current IP for SSH
iptables -C INPUT -p tcp -s {current_ip} --dport 22 -j ACCEPT 2>/dev/null || \
  iptables -I INPUT -p tcp -s {current_ip} --dport 22 -j ACCEPT

# UFW if available
if command -v ufw >/dev/null 2>&1; then
  ufw allow from {current_ip} to any port 22
  ufw --force enable 2>/dev/null || true
fi
"""
    for line in script.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            exec_command(conn, line)


def configure_security(conn: SSHClient) -> None:
    """Run full security configuration sequence."""
    logger.info("Configuring security...")
    current_ip = get_current_ip()
    configure_ssh_security(conn, current_ip)

    if is_fail2ban_installed(conn):
        logger.info("Fail2ban is installed")
    else:
        logger.info("Fail2ban not installed (optional)")
