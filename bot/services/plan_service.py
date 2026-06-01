from models import Plan, Server, WireGuardConfig


def get_plan_servers(db, plan_id: int):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan or not plan.service_type_id:
        return []

    return db.query(Server).filter(
        Server.service_type_id == plan.service_type_id,
        Server.is_active == True,
    ).all()


def get_server_active_config_count(db, server_id: int) -> int:
    return db.query(WireGuardConfig).filter(
        WireGuardConfig.server_id == server_id,
        WireGuardConfig.status == "active",
    ).count()


def get_available_servers_for_plan(db, plan_id: int):
    servers = get_plan_servers(db, plan_id)
    return [srv for srv in servers if (srv.capacity or 0) <= 0 or get_server_active_config_count(db, srv.id) < (srv.capacity or 0)]


def get_available_active_servers(db, service_type_id: int | None = None):
    query = db.query(Server).filter(Server.is_active == True)
    if service_type_id is not None:
        query = query.filter(Server.service_type_id == service_type_id)
    servers = query.all()
    return [srv for srv in servers if (srv.capacity or 0) <= 0 or get_server_active_config_count(db, srv.id) < (srv.capacity or 0)]


def build_wg_kwargs(
    server: Server,
    user_id: str,
    plan,
    plan_name: str,
    duration_days: int,
    traffic_limit_gb: float = None,
    peer_name_prefix: str = None,
):
    return dict(
        server_host=server.host,
        server_port=server.api_port or 22,
        connection_host=server.wg_server_endpoint or server.host,
        server_login_username=server.username,
        server_login_password=server.password,
        user_telegram_id=str(user_id),
        plan_id=plan.id if plan else None,
        plan_name=plan_name,
        duration_days=duration_days,
        traffic_limit_gb=(traffic_limit_gb if traffic_limit_gb is not None else (plan.traffic_gb if plan else None)),
        server_id=server.id,
        peer_name_prefix=peer_name_prefix,
        server_name=server.name,
        service_type_code=(server.service_type.code if server.service_type else None),
    )
