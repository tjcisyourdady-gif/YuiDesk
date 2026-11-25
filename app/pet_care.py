"""完全独立于 AI 的完整本地桌宠养成系统（互动 / 小卖部与背包 / 每日任务 / 成就墙 / 成长等级）."""

from __future__ import annotations

import datetime
import json
import sqlite3
import threading
import time
from typing import Any

from app.paths import get_db_path

# 小卖部商品目录（购买后放入背包，随时使用/投喂/送礼）
SHOP_ITEMS: dict[str, dict[str, Any]] = {
    "black_tea": {
        "id": "black_tea",
        "name": "放学后热红茶",
        "category": "饮品",
        "price": 6,
        "desc": "饱食+14  精力+10  心情+8",
        "hunger": 14,
        "mood": 8,
        "energy": 10,
        "exp": 10,
        "pet_state": "tea",
        "duration": 3.8,
        "bubble": "暖呼呼的放学后红茶，最放松了",
    },
    "dorayaki": {
        "id": "dorayaki",
        "name": "日式红豆铜锣烧",
        "category": "点心",
        "price": 12,
        "desc": "饱食+24  心情+14  经验+12",
        "hunger": 24,
        "mood": 14,
        "energy": 4,
        "exp": 12,
        "pet_state": "eat_cake",
        "duration": 3.8,
        "bubble": "红豆馅甜甜的，真好吃",
    },
    "strawberry_cake": {
        "id": "strawberry_cake",
        "name": "草莓奶油蛋糕",
        "category": "甜点",
        "price": 20,
        "desc": "饱食+36  心情+26  经验+20",
        "hunger": 36,
        "mood": 26,
        "energy": 8,
        "exp": 20,
        "pet_state": "eat_cake",
        "duration": 4.2,
        "bubble": "哇，最爱的草莓奶油蛋糕，幸福感爆棚",
    },
    "matcha_pudding": {
        "id": "matcha_pudding",
        "name": "宇治抹茶布丁",
        "category": "甜点",
        "price": 14,
        "desc": "饱食+18  心情+22  经验+14",
        "hunger": 18,
        "mood": 22,
        "energy": 4,
        "exp": 14,
        "pet_state": "eat_cake",
        "duration": 3.8,
        "bubble": "软绵绵入口即化的抹茶布丁",
    },
    "lemon_soda": {
        "id": "lemon_soda",
        "name": "元气柠檬汽水",
        "category": "饮品",
        "price": 15,
        "desc": "精力+38  心情+12  经验+10",
        "hunger": 6,
        "mood": 12,
        "energy": 38,
        "exp": 10,
        "pet_state": "stretch",
        "duration": 3.6,
        "bubble": "咕嘟咕嘟喝完汽水，精力瞬间拉满",
    },
    "guitar_pick": {
        "id": "guitar_pick",
        "name": "轻音限定吉他拨片",
        "category": "礼物",
        "price": 35,
        "desc": "送礼！亲密经验+55  心情+32",
        "hunger": 0,
        "mood": 32,
        "energy": 6,
        "exp": 55,
        "pet_state": "shy_blush",
        "duration": 4.2,
        "bubble": "送给我的限定拨片吗？太开心了，我会好好珍藏的",
    },
}

# 直接日常互动动作
CARE_ACTIONS: dict[str, dict[str, Any]] = {
    "pet": {
        "name": "摸摸头",
        "energy_cost": 0,
        "hunger": 0,
        "mood": 12,
        "energy": 2,
        "exp": 8,
        "coins_reward": 0,
        "pet_state": "pet_head",
        "duration": 3.4,
        "bubble": "嘿嘿，被摸头好舒服呀",
        "quest_key": "pet",
    },
    "music": {
        "name": "戴耳机听歌",
        "energy_cost": 0,
        "hunger": -2,
        "mood": 15,
        "energy": 6,
        "exp": 10,
        "coins_reward": 0,
        "pet_state": "music_dance",
        "duration": 4.2,
        "bubble": "戴上耳机跟着节拍摇摆起来",
        "quest_key": "play",
    },
    "sit": {
        "name": "坐下晃小腿",
        "energy_cost": 0,
        "hunger": -1,
        "mood": 8,
        "energy": 18,
        "exp": 6,
        "coins_reward": 0,
        "pet_state": "sit_swing",
        "duration": 4.2,
        "bubble": "坐下来晃晃小腿放松一下",
        "quest_key": "",
    },
    "guitar": {
        "name": "练吉他演出",
        "energy_cost": 14,
        "hunger": -8,
        "mood": 16,
        "energy": -14,
        "exp": 28,
        "coins_reward": 22,
        "pet_state": "practice_guitar",
        "duration": 4.5,
        "bubble": "精彩演完一曲，赚到 22 枚零花钱啦",
        "quest_key": "work",
    },
    "study": {
        "name": "认真学习",
        "energy_cost": 12,
        "hunger": -6,
        "mood": 6,
        "energy": -12,
        "exp": 30,
        "coins_reward": 16,
        "pet_state": "study_desk",
        "duration": 4.2,
        "bubble": "认真做完笔记，成长值和零花钱都涨啦",
        "quest_key": "work",
    },
    "stretch": {
        "name": "伸个懒腰",
        "energy_cost": 0,
        "hunger": -2,
        "mood": 8,
        "energy": 15,
        "exp": 6,
        "coins_reward": 0,
        "pet_state": "stretch",
        "duration": 3.4,
        "bubble": "呼——伸个懒腰元气恢复",
        "quest_key": "",
    },
    "nap": {
        "name": "午睡小憩",
        "energy_cost": 0,
        "hunger": -4,
        "mood": 8,
        "energy": 36,
        "exp": 6,
        "coins_reward": 0,
        "pet_state": "sleep",
        "duration": 5.2,
        "bubble": "小憩一会儿，精力恢复满满",
        "quest_key": "",
    },
    "praise": {
        "name": "夸夸她",
        "energy_cost": 0,
        "hunger": 0,
        "mood": 14,
        "energy": 4,
        "exp": 10,
        "coins_reward": 0,
        "pet_state": "proud_pose",
        "duration": 3.6,
        "bubble": "哼哼，被夸奖了好得意呀",
        "quest_key": "play",
    },
}

DAILY_QUEST_DEFS: list[dict[str, Any]] = [
    {"id": "q_checkin", "title": "完成今日签到打卡", "target": 1, "reward_coins": 15, "reward_exp": 20},
    {"id": "q_pet", "title": "今天摸摸头 3 次", "target": 3, "reward_coins": 18, "reward_exp": 22},
    {"id": "q_feed", "title": "投喂零食或饮品 2 次", "target": 2, "reward_coins": 22, "reward_exp": 26},
    {"id": "q_work", "title": "一起练吉他或学习 1 次", "target": 1, "reward_coins": 25, "reward_exp": 30},
]

ACHIEVEMENT_DEFS: list[dict[str, Any]] = [
    {"id": "a_first", "title": "初次相遇", "desc": "完成第 1 次互动陪伴", "check": lambda r: (r["total_pets"] + r["total_feeds"] + r["total_practices"]) >= 1},
    {"id": "a_pet10", "title": "摸头狂魔", "desc": "累计摸摸头 10 次", "check": lambda r: r["total_pets"] >= 10},
    {"id": "a_feed10", "title": "下午茶大师", "desc": "累计投喂美食 10 次", "check": lambda r: r["total_feeds"] >= 10},
    {"id": "a_work5", "title": "轻音部王牌", "desc": "累计练吉他或学习 5 次", "check": lambda r: r["total_practices"] >= 5},
    {"id": "a_eat5", "title": "吃文件小怪兽", "desc": "累计吃掉 5 个文件图标", "check": lambda r: r["total_files_eaten"] >= 5},
    {"id": "a_lv5", "title": "放学后茶友", "desc": "亲密等级达到 Lv.5", "check": lambda r: r["level"] >= 5},
    {"id": "a_lv10", "title": "永恒轻音搭档", "desc": "亲密等级达到 Lv.10", "check": lambda r: r["level"] >= 10},
]


def _level_title(level: int) -> str:
    if level < 4:
        return "初遇同桌"
    if level < 8:
        return "放学后茶友"
    if level < 13:
        return "轻音部搭档"
    if level < 20:
        return "默契主唱拍档"
    return "永恒轻音羁绊"


def _exp_needed(level: int) -> int:
    return 60 + (level - 1) * 35


def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


def _default_daily_progress(today_str: str) -> dict[str, Any]:
    return {
        "date": today_str,
        "progress": {"q_checkin": 0, "q_pet": 0, "q_feed": 0, "q_work": 0},
        "claimed": [],
    }


class PetCareEngine:
    """完全本地、离线可用的桌宠养成系统，彻底独立于 AI."""

    def __init__(self) -> None:
        self._path = get_db_path()
        self._lock = threading.RLock()
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_table(self) -> None:
        now = time.time()
        today_str = datetime.date.today().isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pet_care_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    pet_name TEXT NOT NULL DEFAULT '小唯',
                    hunger REAL NOT NULL DEFAULT 82,
                    mood REAL NOT NULL DEFAULT 88,
                    energy REAL NOT NULL DEFAULT 85,
                    level INTEGER NOT NULL DEFAULT 1,
                    exp INTEGER NOT NULL DEFAULT 0,
                    coins INTEGER NOT NULL DEFAULT 100,
                    total_pets INTEGER NOT NULL DEFAULT 0,
                    total_feeds INTEGER NOT NULL DEFAULT 0,
                    total_practices INTEGER NOT NULL DEFAULT 0,
                    total_files_eaten INTEGER NOT NULL DEFAULT 0,
                    checkin_streak INTEGER NOT NULL DEFAULT 0,
                    last_checkin_date TEXT NOT NULL DEFAULT '',
                    last_tick_at REAL NOT NULL,
                    logs_json TEXT NOT NULL DEFAULT '[]',
                    inventory_json TEXT NOT NULL DEFAULT '{}',
                    daily_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            # 兼容旧库平滑加列
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(pet_care_state)").fetchall()}
            if "inventory_json" not in cols:
                conn.execute("ALTER TABLE pet_care_state ADD COLUMN inventory_json TEXT NOT NULL DEFAULT '{}'")
            if "daily_json" not in cols:
                conn.execute("ALTER TABLE pet_care_state ADD COLUMN daily_json TEXT NOT NULL DEFAULT '{}'")
            if "total_files_eaten" not in cols:
                conn.execute("ALTER TABLE pet_care_state ADD COLUMN total_files_eaten INTEGER NOT NULL DEFAULT 0")

            default_inv = json.dumps({"black_tea": 2, "strawberry_cake": 1}, ensure_ascii=False)
            default_daily = json.dumps(_default_daily_progress(today_str), ensure_ascii=False)
            conn.execute(
                """
                INSERT OR IGNORE INTO pet_care_state (id, last_tick_at, inventory_json, daily_json)
                VALUES (1, ?, ?, ?)
                """,
                (now, default_inv, default_daily),
            )
            # 若旧记录背包是空对象且没有任何投喂记录，赠送新手零食礼包
            row = conn.execute("SELECT inventory_json, total_feeds FROM pet_care_state WHERE id = 1").fetchone()
            if row and row["inventory_json"] in ("", "{}") and int(row["total_feeds"]) == 0:
                conn.execute(
                    "UPDATE pet_care_state SET inventory_json = ? WHERE id = 1",
                    (default_inv,),
                )

    def _get_daily(self, row: sqlite3.Row) -> dict[str, Any]:
        today_str = datetime.date.today().isoformat()
        try:
            d = json.loads(row["daily_json"] or "{}")
        except Exception:
            d = {}
        if d.get("date") != today_str:
            d = _default_daily_progress(today_str)
            if row["last_checkin_date"] == today_str:
                d["progress"]["q_checkin"] = 1
        return d

    def _get_inventory(self, row: sqlite3.Row) -> dict[str, int]:
        try:
            inv = json.loads(row["inventory_json"] or "{}")
            return {k: int(v) for k, v in inv.items() if int(v) > 0 and k in SHOP_ITEMS}
        except Exception:
            return {}

    def _apply_time_decay(self, conn: sqlite3.Connection) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM pet_care_state WHERE id = 1").fetchone()
        assert row is not None
        now = time.time()
        elapsed_min = max(0.0, (now - float(row["last_tick_at"])) / 60.0)
        effective_min = min(elapsed_min, 180.0)
        if effective_min >= 2.0:
            hunger = max(12.0, float(row["hunger"]) - effective_min * 0.14)
            mood_drop = effective_min * (0.12 if hunger < 30 else 0.06)
            mood = max(20.0, float(row["mood"]) - mood_drop)
            energy = min(100.0, float(row["energy"]) + effective_min * 0.09)
            conn.execute(
                "UPDATE pet_care_state SET hunger = ?, mood = ?, energy = ?, last_tick_at = ? WHERE id = 1",
                (hunger, mood, energy, now),
            )
            row = conn.execute("SELECT * FROM pet_care_state WHERE id = 1").fetchone()
            assert row is not None
        return row

    def _serialize(self, row: sqlite3.Row) -> dict[str, Any]:
        level = int(row["level"])
        today = datetime.date.today().isoformat()
        logs = json.loads(row["logs_json"] or "[]")
        inv = self._get_inventory(row)
        daily = self._get_daily(row)
        hunger = round(float(row["hunger"]))
        mood = round(float(row["mood"]))
        energy = round(float(row["energy"]))

        if hunger <= 25:
            status_text = "肚子咕噜叫了，想吃小零食"
        elif energy <= 22:
            status_text = "有点困了，伸个懒腰或午睡一下吧"
        elif mood >= 85:
            status_text = "心情超好，元气满满"
        elif mood >= 55:
            status_text = "状态不错，正安安静静陪着你"
        else:
            status_text = "有点无聊，摸摸头或听会儿歌吧"

        quests_out = []
        for q in DAILY_QUEST_DEFS:
            cur_val = int(daily["progress"].get(q["id"], 0))
            claimed = q["id"] in daily["claimed"]
            quests_out.append(
                {
                    **q,
                    "current": min(q["target"], cur_val),
                    "completed": cur_val >= q["target"],
                    "claimed": claimed,
                }
            )

        row_dict = dict(row)
        achievements_out = [
            {
                "id": a["id"],
                "title": a["title"],
                "desc": a["desc"],
                "unlocked": bool(a["check"](row_dict)),
            }
            for a in ACHIEVEMENT_DEFS
        ]

        shop_out = [{**item, "owned": inv.get(item["id"], 0)} for item in SHOP_ITEMS.values()]

        return {
            "pet_name": row["pet_name"],
            "hunger": hunger,
            "mood": mood,
            "energy": energy,
            "level": level,
            "title": _level_title(level),
            "exp": int(row["exp"]),
            "exp_needed": _exp_needed(level),
            "coins": int(row["coins"]),
            "total_pets": int(row["total_pets"]),
            "total_feeds": int(row["total_feeds"]),
            "total_practices": int(row["total_practices"]),
            "total_files_eaten": int(row["total_files_eaten"]),
            "checkin_streak": int(row["checkin_streak"]),
            "checked_in_today": row["last_checkin_date"] == today,
            "status_text": status_text,
            "is_hungry": hunger <= 25,
            "is_tired": energy <= 22,
            "inventory": inv,
            "shop": shop_out,
            "quests": quests_out,
            "achievements": achievements_out,
            "logs": logs[:10],
        }

    def get_state(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = self._apply_time_decay(conn)
            return self._serialize(row)

    def rename_pet(self, new_name: str) -> dict[str, Any]:
        clean = (new_name or "").strip()[:12] or "小唯"
        with self._lock, self._connect() as conn:
            self._apply_time_decay(conn)
            conn.execute("UPDATE pet_care_state SET pet_name = ? WHERE id = 1", (clean,))
            row = conn.execute("SELECT * FROM pet_care_state WHERE id = 1").fetchone()
            assert row is not None
            return self._serialize(row)

    def _append_log(self, logs: list[dict[str, str]], text: str) -> list[dict[str, str]]:
        ts = datetime.datetime.now().strftime("%H:%M")
        return [{"time": ts, "text": text}] + logs[:15]

    def _add_exp(self, level: int, exp: int, gain: int) -> tuple[int, int, bool]:
        exp += gain
        leveled_up = False
        while exp >= _exp_needed(level) and level < 99:
            exp -= _exp_needed(level)
            level += 1
            leveled_up = True
        return level, exp, leveled_up

    def daily_checkin(self) -> dict[str, Any]:
        today = datetime.date.today()
        today_str = today.isoformat()
        yesterday_str = (today - datetime.timedelta(days=1)).isoformat()

        with self._lock, self._connect() as conn:
            row = self._apply_time_decay(conn)
            if row["last_checkin_date"] == today_str:
                return {"ok": False, "message": "今天已经签到过啦", "state": self._serialize(row)}
            streak = int(row["checkin_streak"]) + 1 if row["last_checkin_date"] == yesterday_str else 1
            bonus_coins = 30 + min(25, (streak - 1) * 5)
            level, exp, leveled_up = self._add_exp(int(row["level"]), int(row["exp"]), 25)
            coins = int(row["coins"]) + bonus_coins
            mood = _clamp(float(row["mood"]) + 10)
            daily = self._get_daily(row)
            daily["progress"]["q_checkin"] = 1
            logs = self._append_log(
                json.loads(row["logs_json"] or "[]"),
                f"连续第 {streak} 天签到，获得 {bonus_coins} 零花钱",
            )
            conn.execute(
                """
                UPDATE pet_care_state
                SET level = ?, exp = ?, coins = ?, mood = ?, checkin_streak = ?,
                    last_checkin_date = ?, logs_json = ?, daily_json = ?, last_tick_at = ?
                WHERE id = 1
                """,
                (
                    level, exp, coins, mood, streak, today_str,
                    json.dumps(logs, ensure_ascii=False),
                    json.dumps(daily, ensure_ascii=False),
                    time.time(),
                ),
            )
            updated = conn.execute("SELECT * FROM pet_care_state WHERE id = 1").fetchone()
            assert updated is not None
            msg = f"签到成功！连续 {streak} 天，零花钱 +{bonus_coins}"
            if leveled_up:
                msg += f"，升至 Lv.{level}「{_level_title(level)}」"
            return {
                "ok": True,
                "message": msg,
                "pet_state": "happy",
                "duration": 3.5,
                "bubble": msg,
                "state": self._serialize(updated),
            }

    def buy_item(self, item_id: str) -> dict[str, Any]:
        item = SHOP_ITEMS.get(item_id)
        if not item:
            return {"ok": False, "message": "商品不存在", "state": self.get_state()}
        with self._lock, self._connect() as conn:
            row = self._apply_time_decay(conn)
            coins = int(row["coins"])
            if coins < item["price"]:
                return {
                    "ok": False,
                    "message": f"零花钱不足（需要 {item['price']} 币），去练吉他或学习赚点零花钱吧",
                    "state": self._serialize(row),
                }
            inv = self._get_inventory(row)
            inv[item_id] = inv.get(item_id, 0) + 1
            coins -= item["price"]
            logs = self._append_log(json.loads(row["logs_json"] or "[]"), f"购买了「{item['name']}」(-{item['price']}币)")
            conn.execute(
                "UPDATE pet_care_state SET coins = ?, inventory_json = ?, logs_json = ?, last_tick_at = ? WHERE id = 1",
                (coins, json.dumps(inv, ensure_ascii=False), json.dumps(logs, ensure_ascii=False), time.time()),
            )
            updated = conn.execute("SELECT * FROM pet_care_state WHERE id = 1").fetchone()
            assert updated is not None
            return {
                "ok": True,
                "message": f"已购买「{item['name']}」放入背包",
                "state": self._serialize(updated),
            }

    def use_item(self, item_id: str) -> dict[str, Any]:
        item = SHOP_ITEMS.get(item_id)
        if not item:
            return {"ok": False, "message": "物品不存在", "state": self.get_state()}
        with self._lock, self._connect() as conn:
            row = self._apply_time_decay(conn)
            inv = self._get_inventory(row)
            if inv.get(item_id, 0) <= 0:
                return {"ok": False, "message": f"背包里没有「{item['name']}」，请先购买", "state": self._serialize(row)}
            inv[item_id] -= 1
            if inv[item_id] <= 0:
                inv.pop(item_id, None)

            hunger = _clamp(float(row["hunger"]) + item["hunger"])
            mood = _clamp(float(row["mood"]) + item["mood"])
            energy = _clamp(float(row["energy"]) + item["energy"])
            level, exp, leveled_up = self._add_exp(int(row["level"]), int(row["exp"]), item["exp"])
            daily = self._get_daily(row)
            daily["progress"]["q_feed"] = int(daily["progress"].get("q_feed", 0)) + 1
            logs = self._append_log(
                json.loads(row["logs_json"] or "[]"),
                f"使用了「{item['name']}」（经验+{item['exp']}）",
            )
            conn.execute(
                """
                UPDATE pet_care_state
                SET hunger = ?, mood = ?, energy = ?, level = ?, exp = ?,
                    total_feeds = total_feeds + 1, inventory_json = ?,
                    daily_json = ?, logs_json = ?, last_tick_at = ?
                WHERE id = 1
                """,
                (
                    hunger, mood, energy, level, exp,
                    json.dumps(inv, ensure_ascii=False),
                    json.dumps(daily, ensure_ascii=False),
                    json.dumps(logs, ensure_ascii=False),
                    time.time(),
                ),
            )
            updated = conn.execute("SELECT * FROM pet_care_state WHERE id = 1").fetchone()
            assert updated is not None
            bubble = item["bubble"]
            if leveled_up:
                bubble = f"升级啦！成为 Lv.{level}「{_level_title(level)}」"
            return {
                "ok": True,
                "message": f"已投喂/赠送「{item['name']}」",
                "pet_state": item["pet_state"],
                "duration": item["duration"],
                "bubble": bubble,
                "state": self._serialize(updated),
            }

    def claim_quest(self, quest_id: str) -> dict[str, Any]:
        qdef = next((q for q in DAILY_QUEST_DEFS if q["id"] == quest_id), None)
        if not qdef:
            return {"ok": False, "message": "任务不存在", "state": self.get_state()}
        with self._lock, self._connect() as conn:
            row = self._apply_time_decay(conn)
            daily = self._get_daily(row)
            if quest_id in daily["claimed"]:
                return {"ok": False, "message": "奖励已领取", "state": self._serialize(row)}
            if int(daily["progress"].get(quest_id, 0)) < qdef["target"]:
                return {"ok": False, "message": "任务尚未完成", "state": self._serialize(row)}

            daily["claimed"].append(quest_id)
            coins = int(row["coins"]) + qdef["reward_coins"]
            level, exp, leveled_up = self._add_exp(int(row["level"]), int(row["exp"]), qdef["reward_exp"])
            logs = self._append_log(
                json.loads(row["logs_json"] or "[]"),
                f"完成每日任务「{qdef['title']}」，获得 {qdef['reward_coins']} 币",
            )
            conn.execute(
                """
                UPDATE pet_care_state
                SET coins = ?, level = ?, exp = ?, daily_json = ?, logs_json = ?, last_tick_at = ?
                WHERE id = 1
                """,
                (
                    coins, level, exp,
                    json.dumps(daily, ensure_ascii=False),
                    json.dumps(logs, ensure_ascii=False),
                    time.time(),
                ),
            )
            updated = conn.execute("SELECT * FROM pet_care_state WHERE id = 1").fetchone()
            assert updated is not None
            msg = f"领取成功：零花钱+{qdef['reward_coins']}，经验+{qdef['reward_exp']}"
            return {
                "ok": True,
                "message": msg,
                "pet_state": "proud_pose",
                "duration": 3.4,
                "bubble": "任务达成！感觉自己超厉害的",
                "state": self._serialize(updated),
            }

    def perform_action(self, action_id: str) -> dict[str, Any]:
        spec = CARE_ACTIONS.get(action_id)
        if not spec:
            return {"ok": False, "message": "未知互动动作", "state": self.get_state()}

        with self._lock, self._connect() as conn:
            row = self._apply_time_decay(conn)
            energy = float(row["energy"])
            if spec["energy_cost"] > 0 and energy < spec["energy_cost"]:
                return {
                    "ok": False,
                    "message": "精力不够啦，先坐下休息、伸懒腰或喝杯柠檬汽水吧",
                    "pet_state": "sleep",
                    "duration": 3.5,
                    "bubble": "有点累了，先歇一小会儿吧",
                    "state": self._serialize(row),
                }

            coins = int(row["coins"]) + spec["coins_reward"]
            hunger = _clamp(float(row["hunger"]) + spec["hunger"])
            mood = _clamp(float(row["mood"]) + spec["mood"])
            energy = _clamp(energy + spec["energy"])
            level, exp, leveled_up = self._add_exp(int(row["level"]), int(row["exp"]), spec["exp"])

            total_pets = int(row["total_pets"]) + (1 if action_id == "pet" else 0)
            total_practices = int(row["total_practices"]) + (1 if action_id in ("guitar", "study") else 0)

            daily = self._get_daily(row)
            if spec["quest_key"] == "pet":
                daily["progress"]["q_pet"] = int(daily["progress"].get("q_pet", 0)) + 1
            elif spec["quest_key"] == "work":
                daily["progress"]["q_work"] = int(daily["progress"].get("q_work", 0)) + 1

            summary = f"{spec['name']}（经验+{spec['exp']}"
            if spec["coins_reward"]:
                summary += f"，零花钱+{spec['coins_reward']}"
            summary += "）"
            logs = self._append_log(json.loads(row["logs_json"] or "[]"), summary)

            conn.execute(
                """
                UPDATE pet_care_state
                SET hunger = ?, mood = ?, energy = ?, level = ?, exp = ?, coins = ?,
                    total_pets = ?, total_practices = ?, daily_json = ?, logs_json = ?, last_tick_at = ?
                WHERE id = 1
                """,
                (
                    hunger, mood, energy, level, exp, coins,
                    total_pets, total_practices,
                    json.dumps(daily, ensure_ascii=False),
                    json.dumps(logs, ensure_ascii=False),
                    time.time(),
                ),
            )
            updated = conn.execute("SELECT * FROM pet_care_state WHERE id = 1").fetchone()
            assert updated is not None
            bubble = spec["bubble"]
            if leveled_up:
                bubble = f"升级啦！成为 Lv.{level}「{_level_title(level)}」"
            return {
                "ok": True,
                "message": summary,
                "pet_state": spec["pet_state"],
                "duration": spec["duration"],
                "bubble": bubble,
                "state": self._serialize(updated),
            }

    def reward_file_eaten(self, count: int = 1) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = self._apply_time_decay(conn)
            hunger = _clamp(float(row["hunger"]) + 5 * count)
            mood = _clamp(float(row["mood"]) + 4 * count)
            coins = int(row["coins"]) + 3 * count
            level, exp, _ = self._add_exp(int(row["level"]), int(row["exp"]), 5 * count)
            logs = self._append_log(
                json.loads(row["logs_json"] or "[]"),
                f"吃掉了 {count} 个文件图标（饱食+{5 * count}，零花钱+{3 * count}）",
            )
            conn.execute(
                """
                UPDATE pet_care_state
                SET hunger = ?, mood = ?, coins = ?, level = ?, exp = ?,
                    total_files_eaten = total_files_eaten + ?, logs_json = ?, last_tick_at = ?
                WHERE id = 1
                """,
                (hunger, mood, coins, level, exp, count, json.dumps(logs, ensure_ascii=False), time.time()),
            )
            updated = conn.execute("SELECT * FROM pet_care_state WHERE id = 1").fetchone()
            assert updated is not None
            return self._serialize(updated)
