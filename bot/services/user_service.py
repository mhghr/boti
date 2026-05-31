from sqlalchemy import or_

from models import User, WireGuardConfig
from config import ADMIN_IDS


def get_or_create_user(db, telegram_id: str, username=None, first_name=None, last_name=None, return_created: bool = False):
    user = db.query(User).filter(User.telegram_id == str(telegram_id)).first()
    created = False
    if not user:
        admin = str(telegram_id) in ADMIN_IDS
        user = User(
            telegram_id=str(telegram_id),
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_member=False,
            is_admin=admin,
            wallet_balance=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        created = True

    if return_created:
        return user, created
    return user


def get_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == str(telegram_id)).first()


def is_admin(telegram_id: str) -> bool:
    return str(telegram_id) in ADMIN_IDS


def calculate_org_user_financials(db, user_obj: User):
    user_configs = db.query(WireGuardConfig).filter(
        WireGuardConfig.user_telegram_id == user_obj.telegram_id,
    ).all()
    total_traffic_bytes = sum((cfg.cumulative_rx_bytes or 0) + (cfg.cumulative_tx_bytes or 0) for cfg in user_configs)
    total_traffic_gb = total_traffic_bytes / (1024 ** 3)
    price_per_gb = user_obj.org_price_per_gb or 0
    debt_amount = int(total_traffic_gb * price_per_gb)
    return {
        "active_configs": [cfg for cfg in user_configs if cfg.status == "active"],
        "total_configs": user_configs,
        "active_traffic_gb": sum((cfg.cumulative_rx_bytes or 0) + (cfg.cumulative_tx_bytes or 0) for cfg in user_configs if cfg.status == "active") / (1024 ** 3),
        "deleted_traffic_gb": 0,
        "total_traffic_gb": total_traffic_gb,
        "price_per_gb": price_per_gb,
        "debt_amount": debt_amount,
    }


def search_users(db, query_text: str):
    q_raw = (query_text or "").strip()
    q = q_raw.lower()
    q_no_at = q.lstrip("@")

    filters = []
    if q_no_at:
        like_q = f"%{q_no_at}%"
        filters.extend([
            User.username.ilike(like_q),
            User.first_name.ilike(like_q),
            User.last_name.ilike(like_q),
            User.telegram_id.like(like_q),
        ])

    if not filters:
        return []

    users = db.query(User).filter(or_(*filters)).limit(50).all()

    seen = set()
    out = []
    for u in users:
        tg = str(u.telegram_id)
        if tg in seen:
            continue
        seen.add(tg)
        out.append(u)
    return out
