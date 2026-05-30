import socket

import paramiko


def check_server_connection(server) -> tuple[bool, str]:
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                server.host,
                port=server.api_port or 22,
                username=server.username or "",
                password=server.password or "",
                timeout=5,
                look_for_keys=False,
                allow_agent=False,
            )
        finally:
            client.close()
        return True, "اتصال SSH برقرار است"
    except Exception as e:
        return False, str(e)


def evaluate_server_parameters(server) -> dict:
    """Check SSH reachability and ability to create Linux users."""
    result = {
        "host": False,
        "ssh_login": False,
        "useradd": False,
    }

    host = (server.host or "").strip()
    api_port = server.api_port
    username = (server.username or "").strip()
    password = (server.password or "").strip()

    if not (host and isinstance(api_port, int) and 1 <= api_port <= 65535 and username and password):
        result["all_ok"] = False
        return result

    client = None
    try:
        with socket.create_connection((host, api_port), timeout=2):
            pass
        result["host"] = True

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            host,
            port=api_port,
            username=username,
            password=password,
            timeout=5,
            look_for_keys=False,
            allow_agent=False,
        )
        result["ssh_login"] = True

        stdin, stdout, stderr = client.exec_command("command -v useradd >/dev/null 2>&1 && echo ok")
        _ = stdin, stderr
        result["useradd"] = stdout.read().decode("utf-8", errors="ignore").strip() == "ok"
    except Exception:
        result["ssh_login"] = False
        result["useradd"] = False
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass

    result["all_ok"] = bool(result["host"] and result["ssh_login"] and result["useradd"])
    return result
