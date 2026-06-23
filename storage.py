import json
import os
import sqlite3
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS ads (
    source TEXT NOT NULL,
    ad_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    city TEXT,
    category TEXT,
    price REAL,
    area REAL,
    active INTEGER NOT NULL DEFAULT 1,
    found_at TEXT,
    last_seen_at TEXT,
    last_checked_at TEXT,
    payload TEXT NOT NULL,
    PRIMARY KEY (source, ad_id)
);

CREATE INDEX IF NOT EXISTS idx_ads_source_city ON ads(source, city);
CREATE INDEX IF NOT EXISTS idx_ads_active ON ads(active);
CREATE INDEX IF NOT EXISTS idx_ads_last_checked ON ads(last_checked_at);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class AdsStorage:
    def __init__(self, db_path):
        self.db_path = db_path
        self._ready = False

    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self):
        if self._ready:
            return

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
        self._ready = True

    def upsert_ad(self, ad):
        self.init()
        source = ad.get("source") or "olx"
        ad_id = ad.get("ad_id") or ad.get("url") or ad.get("title")
        if not ad_id:
            return False

        ad = dict(ad)
        ad["ad_id"] = ad_id
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        found_at = ad.get("found_at") or now

        with self.connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM ads WHERE source = ? AND ad_id = ?",
                (source, ad_id),
            ).fetchone()

            connection.execute(
                """
                INSERT INTO ads (
                    source, ad_id, url, title, city, category, price, area,
                    active, found_at, last_seen_at, last_checked_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, ad_id) DO UPDATE SET
                    url = excluded.url,
                    title = excluded.title,
                    city = excluded.city,
                    category = excluded.category,
                    price = excluded.price,
                    area = excluded.area,
                    active = excluded.active,
                    last_seen_at = excluded.last_seen_at,
                    last_checked_at = COALESCE(excluded.last_checked_at, ads.last_checked_at),
                    payload = excluded.payload
                """,
                (
                    source,
                    ad_id,
                    ad.get("url", ""),
                    ad.get("title", ""),
                    ad.get("city") or "Інше",
                    ad.get("search_name", ""),
                    ad.get("price"),
                    ad.get("area"),
                    1 if ad.get("active", True) else 0,
                    found_at,
                    now,
                    ad.get("last_checked_at"),
                    json.dumps(ad, ensure_ascii=False),
                ),
            )

        return existing is None

    def has_ad(self, source, ad_id):
        self.init()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM ads WHERE source = ? AND ad_id = ?",
                (source, ad_id),
            ).fetchone()
        return row is not None

    def get_state(self, key, default=None):
        self.init()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_state WHERE key = ?",
                (key,),
            ).fetchone()

        if row is None:
            return default

        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set_state(self, key, value):
        self.init()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO app_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), time.strftime("%Y-%m-%d %H:%M:%S")),
            )

    def load_city_ads(self, source):
        self.init()
        city_ads = {}
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM ads
                WHERE source = ? AND active = 1
                ORDER BY COALESCE(found_at, ''), rowid
                """,
                (source,),
            ).fetchall()

        for row in rows:
            ad = json.loads(row["payload"])
            city = ad.get("city") or "Інше"
            city_ads.setdefault(city, []).append(ad)

        return city_ads

    def find_by_key(self, key, key_builder):
        self.init()
        with self.connect() as connection:
            rows = connection.execute("SELECT payload FROM ads WHERE active = 1").fetchall()

        for row in rows:
            ad = json.loads(row["payload"])
            if key_builder(ad) == key:
                return ad

        return None

    def get_ads_for_active_check(self, sources, limit):
        self.init()
        sources = [source for source in sources if source]
        if not sources or limit <= 0:
            return []

        placeholders = ",".join("?" for _ in sources)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT payload FROM ads
                WHERE active = 1 AND source IN ({placeholders})
                ORDER BY COALESCE(last_checked_at, ''), COALESCE(found_at, ''), rowid
                LIMIT ?
                """,
                (*sources, limit),
            ).fetchall()

        return [json.loads(row["payload"]) for row in rows]

    def mark_inactive(self, source, ad_id):
        self.init()
        with self.connect() as connection:
            connection.execute(
                "UPDATE ads SET active = 0, last_checked_at = ? WHERE source = ? AND ad_id = ?",
                (time.strftime("%Y-%m-%d %H:%M:%S"), source, ad_id),
            )

    def update_checked_at(self, source, ad_id):
        self.init()
        with self.connect() as connection:
            connection.execute(
                "UPDATE ads SET last_checked_at = ? WHERE source = ? AND ad_id = ?",
                (time.strftime("%Y-%m-%d %H:%M:%S"), source, ad_id),
            )

    def migrate_from_ads_dir(self, ads_root, id_builder):
        self.init()
        migrated = 0
        if not os.path.isdir(ads_root):
            return migrated

        for root, _, files in os.walk(ads_root):
            for filename in files:
                if not filename.endswith(".json"):
                    continue

                path = os.path.join(root, filename)
                try:
                    with open(path, "r", encoding="utf-8") as file:
                        ads = json.load(file)
                except (OSError, json.JSONDecodeError):
                    continue

                if not isinstance(ads, list):
                    continue

                for ad in ads:
                    if not isinstance(ad, dict):
                        continue
                    source = ad.get("source") or ("domria" if "domria" in root else "olx")
                    ad["source"] = source
                    ad["ad_id"] = ad.get("ad_id") or id_builder(source, ad.get("url"))
                    if self.upsert_ad(ad):
                        migrated += 1

        return migrated
