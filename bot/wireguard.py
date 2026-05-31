"""
Compatibility layer for account lifecycle management.

Historical function names are preserved to avoid touching every caller,
but the implementation now provisions SSH TCP tunnel accounts on Linux
servers and returns an `npvt-ssh://` connection URI plus QR code.
"""
import base64
import json
import logging
import secrets
import shlex
import string
import sys
from datetime import datetime, timedelta
from io import BytesIO

from database import SessionLocal
from models import Plan, Server, WireGuardConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError as e:
    logger.error(f"paramiko import failed: {e}")
    PARAMIKO_AVAILABLE = False

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError as e:
    logger.error(f"qrcode import failed: {e}")
    QRCODE_AVAILABLE = False


def _open_ssh_client(host: str, port: int, username: str, password: str):
    if not PARAMIKO_AVAILABLE:
        raise RuntimeError("paramiko module not installed")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=int(port or 22),
        username=username,
        password=password,
        timeout=10,
        auth_timeout=10,
        banner_timeout=10,
        look_for_keys=False,
        allow_agent=False,
    )
    return client


def _run_command(ssh, command: str, sudo_password: str | None = None) -> tuple[int, str, str]:
    stdin, stdout, stderr = ssh.exec_command(command)
    if sudo_password:
        stdin.write(sudo_password + "\n")
        stdin.flush()
    exit_code = stdout.channel.recv_exit_status()
    return exit_code, stdout.read().decode("utf-8", errors="ignore"), stderr.read().decode("utf-8", errors="ignore")


def _run_privileged_command(ssh, command: str, login_password: str) -> tuple[int, str, str]:
    exit_code, out, err = _run_command(ssh, "id -u")
    if exit_code == 0 and out.strip() == "0":
        wrapped = f"bash -lc {shlex.quote(command)}"
        return _run_command(ssh, wrapped)

    wrapped = f"sudo -S -p '' bash -lc {shlex.quote(command)}"
    return _run_command(ssh, wrapped, sudo_password=login_password)


def _sanitize_linux_username(value: str) -> str:
    safe = []
    for ch in (value or "").lower():
        if ch.isalnum():
            safe.append(ch)
        elif ch in {"_", "-"}:
            safe.append(ch)
    result = "".join(safe).strip("-_")
    return result or "vpnuser"


def _generate_username(user_telegram_id: str, peer_name_prefix: str | None = None) -> str:
    tail = "".join(ch for ch in str(user_telegram_id or "") if ch.isdigit())[-8:] or secrets.token_hex(3)
    prefix = _sanitize_linux_username(peer_name_prefix or "ssh")
    base = f"{prefix[:10]}_{tail}"
    suffix = secrets.token_hex(2)
    return f"{base[:27]}_{suffix}"[:32]


def _generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _build_npvt_ssh_uri(host: str, port: int, username: str, password: str, remarks: str) -> str:
    payload = {
        "sshConfigType": "SSH-Direct",
        "sni": "",
        "tlsVersion": "DEFAULT",
        "httpProxy": "",
        "authenticateProxy": False,
        "proxyUsername": "",
        "proxyPassword": "",
        "payload": "",
        "dnsTTMode": "UDP",
        "dnsServer": "",
        "nameserver": "",
        "publicKey": "",
        "udpgwPort": 0,
        "remarks": remarks,
        "sshHost": host,
        "sshPort": int(port or 22),
        "sshUsername": username,
        "sshPassword": password,
        "udpgwTransparentDNS": True,
    }
    encoded = base64.b64encode(
        json.dumps(payload, ensure_ascii=False, indent=4).encode("utf-8")
    ).decode("ascii")
    return f"npvt-ssh://{encoded}"


def _build_qr_base64(content: str) -> str | None:
    if not QRCODE_AVAILABLE or not content:
        return None
    qr = qrcode.make(content)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def save_wireguard_config_to_db(
    user_telegram_id: str,
    plan_id: int = None,
    plan_name: str = None,
    private_key: str = None,
    public_key: str = None,
    client_ip: str = None,
    wg_server_public_key: str = "",
    wg_server_endpoint: str = None,
    wg_server_port: int = None,
    wg_client_dns: str = "",
    duration_days: int = None,
    traffic_limit_gb: float = None,
    server_id: int = None,
) -> WireGuardConfig:
    db = SessionLocal()
    try:
        expires_at = datetime.utcnow() + timedelta(days=duration_days) if duration_days else None
        row = WireGuardConfig(
            user_telegram_id=str(user_telegram_id),
            plan_id=plan_id,
            plan_name=plan_name,
            private_key=private_key or "",
            public_key=public_key or "",
            client_ip=client_ip or "",
            wg_server_public_key=wg_server_public_key or "",
            wg_server_endpoint=wg_server_endpoint or "",
            wg_server_port=int(wg_server_port or 22),
            wg_client_dns=wg_client_dns or "",
            status="active",
            expires_at=expires_at,
            duration_days=duration_days,
            traffic_limit_gb=traffic_limit_gb,
            renewed_at=datetime.utcnow(),
            server_id=server_id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_wireguard_account(
    server_host: str,
    server_port: int,
    server_login_username: str,
    server_login_password: str,
    user_telegram_id: str = None,
    plan_id: int = None,
    plan_name: str = None,
    duration_days: int = None,
    traffic_limit_gb: float = None,
    server_id: int = None,
    peer_name_prefix: str = None,
) -> dict:
    if not PARAMIKO_AVAILABLE:
        return {"success": False, "error": "ماژول paramiko نصب نشده است."}
    if not QRCODE_AVAILABLE:
        return {"success": False, "error": "ماژول qrcode نصب نشده است."}
    if not all([server_host, server_login_username, server_login_password]):
        return {"success": False, "error": "اطلاعات اتصال SSH سرور کامل نیست."}

    ssh = None
    try:
        ssh = _open_ssh_client(server_host, server_port, server_login_username, server_login_password)
        remarks = (peer_name_prefix or plan_name or f"ssh-{user_telegram_id}").strip()[:64]

        username = None
        password = None
        for _ in range(5):
            candidate = _generate_username(user_telegram_id, peer_name_prefix)
            check_cmd = f"id {shlex.quote(candidate)} >/dev/null 2>&1"
            exit_code, _, _ = _run_privileged_command(ssh, check_cmd, server_login_password)
            if exit_code != 0:
                username = candidate
                password = _generate_password()
                break

        if not username or not password:
            return {"success": False, "error": "امکان تولید یوزرنیم یکتا روی سرور وجود نداشت."}

        create_cmd = (
            f"id {shlex.quote(username)} >/dev/null 2>&1 && exit 10; "
            f"useradd -m -s /usr/sbin/nologin {shlex.quote(username)} 2>/dev/null "
            f"|| useradd -m -s /bin/false {shlex.quote(username)}; "
            f"echo {shlex.quote(f'{username}:{password}')} | chpasswd; "
            f"passwd -u {shlex.quote(username)} >/dev/null 2>&1 || true"
        )
        exit_code, _, err = _run_privileged_command(ssh, create_cmd, server_login_password)
        if exit_code != 0:
            return {"success": False, "error": err.strip() or "ساخت یوزر SSH روی سرور ناموفق بود."}

        connection_uri = _build_npvt_ssh_uri(server_host, server_port, username, password, remarks)
        db_config = save_wireguard_config_to_db(
            user_telegram_id=user_telegram_id,
            plan_id=plan_id,
            plan_name=plan_name,
            private_key=password,
            public_key=connection_uri,
            client_ip=username,
            wg_server_public_key=remarks,
            wg_server_endpoint=server_host,
            wg_server_port=server_port,
            wg_client_dns="",
            duration_days=duration_days,
            traffic_limit_gb=traffic_limit_gb,
            server_id=server_id,
        )

        return {
            "success": True,
            "private_key": password,
            "public_key": connection_uri,
            "client_ip": username,
            "config": connection_uri,
            "qr_code": _build_qr_base64(connection_uri),
            "peer_comment": remarks,
            "config_id": db_config.id,
            "expires_at": db_config.expires_at,
            "server_host": server_host,
            "server_port": int(server_port or 22),
        }
    except Exception as e:
        logger.exception("SSH account creation failed")
        error_text = str(e)
        lowered = error_text.lower()
        if "authentication failed" in lowered:
            error_text = "احراز هویت SSH ناموفق بود. یوزرنیم، پسورد و پورت SSH سرور را در بخش مدیریت سرورها بررسی کنید."
        elif "unable to connect" in lowered or "timed out" in lowered:
            error_text = "اتصال SSH به سرور برقرار نشد. هاست/IP و پورت SSH سرور را بررسی کنید."
        return {"success": False, "error": error_text}
    finally:
        if ssh:
            ssh.close()


def _change_user_state(server_host: str, server_port: int, login_user: str, login_password: str, account_username: str, command: str) -> bool:
    ssh = None
    try:
        ssh = _open_ssh_client(server_host, server_port, login_user, login_password)
        exit_code, _, err = _run_privileged_command(ssh, command, login_password)
        if exit_code != 0:
            logger.warning("SSH user command failed for %s: %s", account_username, err.strip())
            return False
        return True
    except Exception as e:
        logger.warning("SSH user state change failed for %s: %s", account_username, e)
        return False
    finally:
        if ssh:
            ssh.close()


def disable_wireguard_peer(mikrotik_host: str, mikrotik_user: str, mikrotik_pass: str, mikrotik_port: int, wg_interface: str, client_ip: str):
    return _change_user_state(
        mikrotik_host,
        mikrotik_port,
        mikrotik_user,
        mikrotik_pass,
        client_ip,
        f"usermod -L {shlex.quote(client_ip)}",
    )


def enable_wireguard_peer(mikrotik_host: str, mikrotik_user: str, mikrotik_pass: str, mikrotik_port: int, wg_interface: str, client_ip: str):
    return _change_user_state(
        mikrotik_host,
        mikrotik_port,
        mikrotik_user,
        mikrotik_pass,
        client_ip,
        f"usermod -U {shlex.quote(client_ip)}; passwd -u {shlex.quote(client_ip)} >/dev/null 2>&1 || true",
    )


def reset_wireguard_peer_traffic(mikrotik_host: str, mikrotik_user: str, mikrotik_pass: str, mikrotik_port: int, wg_interface: str, client_ip: str):
    logger.info("Traffic reset is not supported for SSH accounts; returning success for %s", client_ip)
    return True


def delete_wireguard_peer(mikrotik_host: str, mikrotik_user: str, mikrotik_pass: str, mikrotik_port: int, wg_interface: str, client_ip: str):
    return _change_user_state(
        mikrotik_host,
        mikrotik_port,
        mikrotik_user,
        mikrotik_pass,
        client_ip,
        f"userdel -r {shlex.quote(client_ip)} >/dev/null 2>&1 || userdel {shlex.quote(client_ip)}",
    )


def sync_wireguard_usage_counters(mikrotik_host: str, mikrotik_user: str, mikrotik_pass: str, mikrotik_port: int, wg_interface: str):
    logger.info("Usage sync skipped: SSH tunnel mode has no remote traffic collector.")


def fetch_wireguard_peers_usage(mikrotik_host: str, mikrotik_user: str, mikrotik_pass: str, mikrotik_port: int) -> dict:
    return {}


def sync_wireguard_usage_to_db(mikrotik_host: str, mikrotik_user: str, mikrotik_pass: str, mikrotik_port: int) -> tuple[int, int]:
    db = SessionLocal()
    try:
        total = db.query(WireGuardConfig).filter(WireGuardConfig.status == "active").count()
        return 0, total
    finally:
        db.close()


def disable_expired_or_exhausted_configs(mikrotik_host: str, mikrotik_user: str, mikrotik_pass: str, mikrotik_port: int, wg_interface: str):
    db = SessionLocal()
    try:
        server = db.query(Server).filter(Server.host == mikrotik_host, Server.api_port == mikrotik_port).first()
        active_configs = db.query(WireGuardConfig).filter(WireGuardConfig.status == "active").all()
        now = datetime.utcnow()

        for config in active_configs:
            if server and config.server_id != server.id:
                continue
            plan = db.query(Plan).filter(Plan.id == config.plan_id).first() if config.plan_id else None
            duration_days = config.duration_days if config.duration_days is not None else (plan.duration_days if plan else None)
            traffic_limit_gb = config.traffic_limit_gb if config.traffic_limit_gb is not None else (plan.traffic_gb if plan else None)
            expires_at = config.expires_at or (config.created_at + timedelta(days=(duration_days or 0)))
            consumed_bytes = (config.cumulative_rx_bytes or 0) + (config.cumulative_tx_bytes or 0)
            traffic_limit_bytes = int((traffic_limit_gb or 0) * (1024 ** 3)) if traffic_limit_gb else 0

            if (expires_at and expires_at <= now) or (traffic_limit_bytes and consumed_bytes >= traffic_limit_bytes):
                if server:
                    disable_wireguard_peer(server.host, server.username, server.password, server.api_port, "", config.client_ip)
                config.status = "expired"

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
