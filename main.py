import json
import hashlib
import os
import re
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from storage import AdsStorage
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_FILE = os.path.join(BASE_DIR, "seen.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
USERS_FILE = os.path.join(BASE_DIR, "users.json")
FAVORITES_FILE = os.path.join(BASE_DIR, "favorites.json")
ADS_DIR = os.path.join(BASE_DIR, "data", "ads")
ADS_DB_FILE = os.getenv(
    "DATABASE_PATH",
    os.path.join(BASE_DIR, "data", "ads.db")
)
SEARCH_CACHE_FILE = os.path.join(BASE_DIR, "data", "search_cache.json")
ADS_STORAGE = AdsStorage(ADS_DB_FILE)
ALWAYS_VISIBLE_CITIES = ["Житомир"]

SOURCES = {
    "olx": {"name": "OLX", "button": "🏘 OLX оголошення"},
    "domria": {"name": "DOM.RIA", "button": "🏘 DOM.RIA оголошення"},
}
SOURCE_ORDER = ["olx", "domria"]

DOMRIA_CITIES = {
    "Житомир": "zhitomir",
    "Бердичів": "berdichev",
    "Коростень": "korosten",
    "Коростишів": "korostyshev",
    "Малин": "malin",
    "Овруч": "ovruch",
    "Олевськ": "olevsk",
    "Радомишль": "radomyshl",
    "Звягель": "zvyagel",
    "Новоград-Волинський": "novograd-volynskiy",
    "Андрушівка": "andrushovka",
    "Баранівка": "baranovka",
    "Черняхів": "chernyakhov",
    "Чуднів": "chudnov",
    "Романів": "romanov",
    "Любар": "lyubar",
    "Ружин": "ruzhin",
    "Попільня": "popelnya",
    "Хорошів": "horoshev",
    "Лугини": "lugini",
}

DOMRIA_CATEGORY_PATHS = {
    "sale_commercial": "prodazha-kom-nedvizhimosti",
    "rent_commercial": "arenda-kom-nedvizhimosti",
    "sale_houses": "prodazha-domov",
    "rent_houses": "arenda-domov",
    "sale_apartments": "prodazha-kvartir",
    "rent_apartments": "arenda-kvartir",
    "sale_land": "prodazha-uchastkov",
    "sale_maf": "prodazha-kom-nedvizhimosti",
}

DOMRIA_CATEGORY_KEYWORDS = {
    "sale_maf": ["маф", "maf", "кіоск", "киоск", "павільйон", "павильон", "ларьок", "ларек"],
}

DEFAULT_SOURCE = "olx"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}
DETAIL_WORKERS = 8
CITY_WORKERS = 4
REQUEST_TIMEOUT = 8
OLX_MAX_PAGES = 3
DOMRIA_MAX_PAGES = 3
DOMRIA_EMPTY_CACHE_SECONDS = 6 * 3600

CITIES = [
    "Андрушівка",
    "Баранівка",
    "Бердичів",
    "Брусилів",
    "Ємільчине",
    "Житомир",
    "Звягель",
    "Новоград-Волинський",
    "Коростень",
    "Коростишів",
    "Любар",
    "Малин",
    "Народичі",
    "Нова Борова",
    "Овруч",
    "Олевськ",
    "Попільня",
    "Пулини",
    "Радомишль",
    "Романів",
    "Ружин",
    "Хорошів",
    "Черняхів",
    "Чуднів",
    "Вишевичі",
    "Висока Піч",
    "Глибочиця",
    "Гришківці",
    "Довбиш",
    "Довжик",
    "Іршанськ",
    "Кам'яний Брід",
    "Миропіль",
    "Новогуйвинське",
    "Озерне",
    "Станишівка",
    "Тетерівка",
    "Ушомир",
    "Коростишів",
    "смт Гришківці",
    "Лугини",
]
ALWAYS_VISIBLE_CITIES = list(dict.fromkeys(CITIES))
TRACKED_CITIES = set(ALWAYS_VISIBLE_CITIES)

DOMRIA_CITIES.update(
    {
        "Брусилів": "brusilov",
        "Ємільчине": "emilchino",
        "Народичі": "narodichi",
        "Нова Борова": "novaya-borovaya",
        "Пулини": "puliny",
        "Вишевичі": "vyshevichi",
        "Висока Піч": "vysokaya-pech",
        "Глибочиця": "glubochitsa",
        "Гришківці": "grishkovtsy",
        "Довбиш": "dovbysh",
        "Довжик": "dovzhik",
        "Іршанськ": "irshansk",
        "Кам'яний Брід": "kamennyy-brod",
        "Миропіль": "miropol",
        "Новогуйвинське": "novoguyvinskoe",
        "Озерне": "ozernoe",
        "Станишівка": "stanishovka",
        "Тетерівка": "teterivka",
        "Ушомир": "ushomir",
        "смт Гришківці": "grishkovtsy",
    }
)

CITY_ALIASES = {
    "Житомир": ["Житомир", "Житомира", "Житомирі", "Житомиру", "Житомиром", "м. Житомир", "місто Житомир"],
    "Бердичів": ["Бердичів", "Бердичева", "Бердичеві", "Бердичеву", "м. Бердичів"],
    "Коростень": ["Коростень", "Коростеня", "Коростені", "Коростеню", "м. Коростень"],
    "Коростишів": ["Коростишів", "Коростишева", "Коростишеві", "Коростишеву", "м. Коростишів"],
    "Звягель": ["Звягель", "Звягеля", "Звягелі", "Звягелю"],
    "Новоград-Волинський": ["Новоград-Волинський", "Новоград-Волинського", "Новограда-Волинського"],
    "Малин": ["Малин", "Малина", "Малині", "Малину", "м. Малин"],
    "Овруч": ["Овруч", "Овруча", "Овручі", "Овручу", "м. Овруч"],
    "Олевськ": ["Олевськ", "Олевська", "Олевську", "Олевську", "м. Олевськ"],
    "Радомишль": ["Радомишль", "Радомишля", "Радомишлі", "Радомишлю", "м. Радомишль"],
    "Андрушівка": ["Андрушівка", "Андрушівки", "Андрушівці", "Андрушівку"],
    "Баранівка": ["Баранівка", "Баранівки", "Баранівці", "Баранівку"],
    "Брусилів": ["Брусилів", "Брусилова", "Брусилові", "Брусилову"],
    "Ємільчине": ["Ємільчине", "Ємільчиного", "Ємільчиному"],
    "Любар": ["Любар", "Любара", "Любарі", "Любару"],
    "Народичі": ["Народичі", "Народичів", "Народичах"],
    "Нова Борова": ["Нова Борова", "Нової Борової", "Новій Боровій"],
    "Попільня": ["Попільня", "Попільні", "Попільню"],
    "Пулини": ["Пулини", "Пулинах", "Пулинів"],
    "Романів": ["Романів", "Романова", "Романові", "Романову"],
    "Ружин": ["Ружин", "Ружина", "Ружині", "Ружину"],
    "Хорошів": ["Хорошів", "Хорошева", "Хорошеві", "Хорошеву"],
    "Черняхів": ["Черняхів", "Черняхова", "Черняхові", "Черняхову"],
    "Чуднів": ["Чуднів", "Чуднова", "Чуднові", "Чуднову"],
    "Вишевичі": ["Вишевичі", "Вишевичів", "Вишевичах"],
    "Висока Піч": ["Висока Піч", "Високої Печі", "Високій Печі"],
    "Глибочиця": ["Глибочиця", "Глибочиці", "Глибочицю"],
    "Гришківці": ["Гришківці", "Гришківців", "Гришківцях", "смт Гришківці"],
    "смт Гришківці": ["смт Гришківці", "Гришківці"],
    "Довбиш": ["Довбиш", "Довбиша", "Довбиші"],
    "Довжик": ["Довжик", "Довжика", "Довжику"],
    "Іршанськ": ["Іршанськ", "Іршанська", "Іршанську"],
    "Кам'яний Брід": ["Кам'яний Брід", "Кам’яний Брід", "Кам'яного Броду", "Кам’яного Броду"],
    "Миропіль": ["Миропіль", "Мирополя", "Мирополі"],
    "Новогуйвинське": ["Новогуйвинське", "Новогуйвинського", "Новогуйвинському"],
    "Озерне": ["Озерне", "Озерного", "Озерному"],
    "Станишівка": ["Станишівка", "Станишівки", "Станишівці"],
    "Тетерівка": ["Тетерівка", "Тетерівки", "Тетерівці"],
    "Ушомир": ["Ушомир", "Ушомира", "Ушомирі"],
    "Лугини": ["Лугини", "Лугинах", "Лугинів"],
}

CITY_CANONICAL = {}
for city in CITIES:
    CITY_CANONICAL.setdefault(city.casefold(), city)
    for alias in CITY_ALIASES.get(city, [city]):
        CITY_CANONICAL.setdefault(alias.casefold(), city)

DEFAULT_CONFIG = {
    "searches": [
        {
            "id": "sale_commercial",
            "source": "olx",
            "name": "Продаж комерції",
            "url": "https://m.olx.ua/uk/nedvizhimost/kommercheskaya-nedvizhimost/prodazha-kommercheskoy-nedvizhimosti/zht/",
            "enabled": True,
        },
        {
            "id": "sale_apartments",
            "source": "olx",
            "name": "Продаж квартир",
            "url": "https://m.olx.ua/uk/nedvizhimost/kvartiry/prodazha-kvartir/zht/",
            "enabled": False,
        },
        {
            "id": "sale_houses",
            "source": "olx",
            "name": "Продаж будинків",
            "url": "https://m.olx.ua/uk/nedvizhimost/doma/prodazha-domov/zht/",
            "enabled": True,
        },
        {
            "id": "sale_maf",
            "source": "olx",
            "name": "Продаж МАФів / кіосків",
            "url": "https://m.olx.ua/uk/nedvizhimost/kommercheskaya-nedvizhimost/prodazha-kommercheskoy-nedvizhimosti/zht/q-%D0%BC%D0%B0%D1%84/",
            "enabled": True,
        },
        {
            "id": "rent_commercial",
            "source": "olx",
            "name": "Оренда комерції",
            "url": "https://m.olx.ua/uk/nedvizhimost/kommercheskaya-nedvizhimost/arenda-kommercheskoy-nedvizhimosti/zht/",
            "enabled": False,
        },
        {
            "id": "rent_houses",
            "source": "olx",
            "name": "Оренда будинків",
            "url": "https://m.olx.ua/uk/nedvizhimost/doma/arenda-domov/zht/",
            "enabled": False,
        },
        {
            "id": "rent_maf",
            "source": "olx",
            "name": "Оренда МАФів / кіосків",
            "url": "https://m.olx.ua/uk/nedvizhimost/kommercheskaya-nedvizhimost/arenda-kommercheskoy-nedvizhimosti/zht/q-%D0%BC%D0%B0%D1%84/",
            "enabled": False,
        },
        {
            "id": "rent_apartments",
            "source": "olx",
            "name": "Оренда квартир",
            "url": "https://m.olx.ua/uk/nedvizhimost/kvartiry/arenda-kvartir/zht/",
            "enabled": False,
        },
        {
            "id": "sale_land",
            "source": "olx",
            "name": "Продаж земельних ділянок",
            "url": "https://m.olx.ua/uk/nedvizhimost/zemlya/prodazha-zemli/zht/",
            "enabled": False,
        },
        {
            "id": "domria_sale_commercial",
            "source": "domria",
            "name": "Продаж комерції",
            "domria_category": "sale_commercial",
            "enabled": True,
        },
        {
            "id": "domria_rent_commercial",
            "source": "domria",
            "name": "Оренда комерції",
            "domria_category": "rent_commercial",
            "enabled": True,
        },
        {
            "id": "domria_sale_houses",
            "source": "domria",
            "name": "Продаж будинків",
            "domria_category": "sale_houses",
            "enabled": True,
        },
        {
            "id": "domria_rent_houses",
            "source": "domria",
            "name": "Оренда будинків",
            "domria_category": "rent_houses",
            "enabled": False,
        },
        {
            "id": "domria_sale_apartments",
            "source": "domria",
            "name": "Продаж квартир",
            "domria_category": "sale_apartments",
            "enabled": True,
        },
        {
            "id": "domria_rent_apartments",
            "source": "domria",
            "name": "Оренда квартир",
            "domria_category": "rent_apartments",
            "enabled": False,
        },
        {
            "id": "domria_sale_land",
            "source": "domria",
            "name": "Продаж землі",
            "domria_category": "sale_land",
            "enabled": True,
        },
        {
            "id": "domria_sale_maf",
            "source": "domria",
            "name": "Продаж МАФів / кіосків",
            "domria_category": "sale_maf",
            "enabled": True,
        },
    ],
    "filters": {
        "include_keywords": [
            "приміщення",
            "магазин",
            "склад",
            "офіс",
            "маф",
            "кіоск",
            "павільйон",
            "комерц",
            "виробнич",
            "бізнес",
            "фасад",
            "земельн",
            "ділянк",
            "будинок",
            "комплекс",
            "ангар",
            "сто",
            "азс",
        ],
        "exclude_keywords": ["гараж", "паркомісце"],
        "min_area": 30,
        "max_area": None,
        "min_price": None,
        "max_price": None,
    },
}


def load_json_file(path, default):
    if not os.path.exists(path):
        return deepcopy(default)

    try:
        with open(path, "r", encoding="utf-8") as file:
            content = file.read().strip()
            if not content:
                return deepcopy(default)
            return json.loads(content)
    except (OSError, json.JSONDecodeError):
        return deepcopy(default)


def load_search_cache():
    ensure_ads_storage()
    cache = ADS_STORAGE.get_state("search_cache", {})
    return cache if isinstance(cache, dict) else {}


def save_search_cache(cache):
    ensure_ads_storage()
    ADS_STORAGE.set_state("search_cache", cache)


def search_cache_key(search, city_name):
    return f"{search.get('id') or search.get('domria_category')}:{city_name}"


def is_search_cache_active(cache, search, city_name):
    value = cache.get(search_cache_key(search, city_name))
    try:
        return float(value) > time.time()
    except (TypeError, ValueError):
        return False


def set_empty_search_cache(cache, search, city_name):
    cache[search_cache_key(search, city_name)] = time.time() + DOMRIA_EMPTY_CACHE_SECONDS


def clear_search_cache(cache, search, city_name):
    cache.pop(search_cache_key(search, city_name), None)


APP_JSON_MIGRATIONS = {
    "config": (CONFIG_FILE, DEFAULT_CONFIG),
    "search_cache": (SEARCH_CACHE_FILE, {}),
    "seen": (SEEN_FILE, []),
    "users": (USERS_FILE, []),
    "favorites": (FAVORITES_FILE, {}),
}


def migrate_app_json_to_sqlite():
    if ADS_STORAGE.get_state("_app_json_migrated", False):
        return

    for key, (path, default) in APP_JSON_MIGRATIONS.items():
        if os.path.exists(path):
            ADS_STORAGE.set_state(key, load_json_file(path, default))

    ADS_STORAGE.set_state("_app_json_migrated", True)


def load_config():
    ensure_ads_storage()
    config = ADS_STORAGE.get_state("config", DEFAULT_CONFIG)

    if not isinstance(config, dict):
        config = deepcopy(DEFAULT_CONFIG)

    config.setdefault("searches", [])
    config.setdefault("filters", {})

    existing = {search.get("id"): search for search in config["searches"]}
    merged_searches = []

    for default_search in DEFAULT_CONFIG["searches"]:
        search = dict(default_search)
        if default_search["id"] in existing:
            search.update(existing[default_search["id"]])
        merged_searches.append(search)

    config["searches"] = merged_searches

    # Міграція старого неправильного DOM.RIA URL, який повертав 404.
    for search in config["searches"]:
        if search.get("id") == "domria_sale_commercial":
            search["url"] = "https://dom.ria.com/uk/prodazha-kom-nedvizhimosti/zhitomir/"

    for key, value in DEFAULT_CONFIG["filters"].items():
        config["filters"].setdefault(key, deepcopy(value))

    save_config(config)
    return config


def save_config(config):
    ensure_ads_storage()
    ADS_STORAGE.set_state("config", config)



def get_source_name(source_code):
    if not source_code:
        source_code = DEFAULT_SOURCE
    return SOURCES.get(source_code, {}).get("name", str(source_code).upper())


def get_source_button_title(source_code):
    return SOURCES.get(source_code, {}).get("button", get_source_name(source_code))


def get_current_source(context):
    return context.user_data.get("current_source", DEFAULT_SOURCE)


def search_source(search):
    return search.get("source") or DEFAULT_SOURCE


def ensure_ads_storage():
    ADS_STORAGE.init()
    migrate_app_json_to_sqlite()

    migrated_state = ADS_STORAGE.get_state("_ads_json_migrated")
    marker = os.path.join(BASE_DIR, "data", ".ads_db_migrated")
    if migrated_state or os.path.exists(marker):
        ADS_STORAGE.set_state("_ads_json_migrated", migrated_state or {"migrated": "legacy", "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        return

    migrated = ADS_STORAGE.migrate_from_ads_dir(ADS_DIR, canonical_ad_identity)
    ADS_STORAGE.set_state("_ads_json_migrated", {"migrated": migrated, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    print(f"SQLite: мігровано оголошень з JSON: {migrated}")


def seen_value(source_code, url):
    return f"{source_code}:{canonical_ad_identity(source_code, url)}"


def load_seen():
    ensure_ads_storage()
    return set(ADS_STORAGE.get_state("seen", []))


def save_seen(seen):
    ensure_ads_storage()
    ADS_STORAGE.set_state("seen", sorted(seen))


def load_users():
    ensure_ads_storage()
    return set(str(user) for user in ADS_STORAGE.get_state("users", []))


def save_users(users):
    ensure_ads_storage()
    ADS_STORAGE.set_state("users", sorted(users))


def add_user(chat_id):
    users = load_users()
    users.add(str(chat_id))
    save_users(users)


def load_favorites():
    ensure_ads_storage()
    favorites = ADS_STORAGE.get_state("favorites", {})
    return favorites if isinstance(favorites, dict) else {}


def save_favorites(favorites):
    ensure_ads_storage()
    ADS_STORAGE.set_state("favorites", favorites)


def ad_key(ad):
    value = ad.get("ad_id") or canonical_ad_identity(ad.get("source") or DEFAULT_SOURCE, ad.get("url")) or ad.get("title", "")
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def add_favorite(chat_id, ad):
    favorites = load_favorites()
    chat_id = str(chat_id)
    user_favorites = favorites.setdefault(chat_id, [])
    key = ad_key(ad)

    if not any(item.get("key") == key for item in user_favorites):
        saved_ad = dict(ad)
        saved_ad["key"] = key
        saved_ad["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        user_favorites.append(saved_ad)
        save_favorites(favorites)
        return True

    return False


def get_user_favorites(chat_id):
    return load_favorites().get(str(chat_id), [])


def find_ad_by_key(key):
    ensure_ads_storage()
    ad = ADS_STORAGE.find_by_key(key, ad_key)
    if ad:
        return ad

    for ads in load_favorites().values():
        for ad in ads:
            if ad.get("key") == key or ad_key(ad) == key:
                return ad

    return None


def normalize_filename(name):
    safe_name = re.sub(r"[^А-Яа-яІіЇїЄєҐґA-Za-z0-9_ -]", "", name)
    return safe_name.strip().replace(" ", "_") or "Інше"


def clean_url(url):
    url = urldefrag(url or "")[0]
    url = re.sub(r"([?&])search_reason=[^&]+&?", r"\1", url)
    url = re.sub(r"([?&])page=\d+&?", r"\1", url)
    return url.rstrip("?&")


def canonical_ad_identity(source_code, url):
    url = clean_url(url or "")

    if source_code == "domria":
        match = re.search(r"-(\d+)\.html(?:$|[?#])", url)
        if match:
            return match.group(1)

    if source_code == "olx":
        match = re.search(r"-ID([A-Za-z0-9]+)\.html", url)
        if match:
            return match.group(1)

    return url


def add_page_param(url, page):
    if page <= 1:
        return url

    separator = "&" if "?" in url else "?"
    return f"{url}{separator}page={page}"


def normalize_space(text):
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_duplicate_text(text):
    text = normalize_space(text).casefold()
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"[^\w\sА-Яа-яІіЇїЄєҐґ]", " ", text)
    text = re.sub(r"\b(?:id|код|номер)\s*\d+\b", " ", text)
    return normalize_space(text)


def ad_content_key(ad):
    title = ad.get("title") or ""
    description = ad.get("description") or ""
    content = normalize_duplicate_text(f"{title} {description}")

    if len(content) < 20:
        return None

    source = ad.get("source") or DEFAULT_SOURCE
    city = ad.get("city") or ad.get("city_hint") or ""
    category = ad.get("search_name") or ""
    area = ad.get("area") or ""
    price = ad.get("price") or ""
    fingerprint = "|".join(
        [
            source,
            normalize_duplicate_text(city),
            normalize_duplicate_text(category),
            str(area),
            str(price),
            content[:900],
        ]
    )
    return hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()


def canonical_city(value):
    value = normalize_space(value)
    if not value:
        return None

    value = re.sub(r"^(м\.|місто|смт|с\.|село)\s+", "", value, flags=re.IGNORECASE).strip()
    value = value.strip(" ,.-")
    return CITY_CANONICAL.get(value.casefold())


def city_callback_key(city):
    normalized = normalize_filename(city).lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def detect_city(text):
    letters = "А-Яа-яІіЇїЄєҐґA-Za-z"
    text = normalize_space(text)

    for city in sorted(set(CITIES), key=len, reverse=True):
        aliases = CITY_ALIASES.get(city, [city])

        for alias in aliases:
            pattern = rf"(?<![{letters}]){re.escape(alias)}(?![{letters}])"
            if re.search(pattern, text, flags=re.IGNORECASE):
                return "смт Гришківці" if city == "Гришківці" else city

    return "Інше"


def detect_city_from_location(location):
    location = normalize_space(location)
    if not location:
        return None

    parts = re.split(r"[,;|·\-]", location)
    for part in parts:
        city = canonical_city(part)
        if city:
            return "смт Гришківці" if city == "Гришківці" and location.lower().startswith("смт") else city

    city = detect_city(location)
    return None if city == "Інше" else city


def extract_location_from_text(text, source_code=None):
    text = normalize_space(text)
    if not text:
        return None

    patterns = [
        r"Місцезнаходження\s+(.{2,120}?)(?:\s+Житомирська область|\s+ID:|\s+Поскаржитися|$)",
        r"(?:Продаж|Оренда|Купити|Орендувати).{0,80}?\s+-\s+([^:]{2,80}?)\s+на\s+Olx",
        r"Адреса(?:\s+новобудови)?\s*[-:]\s*(.{2,120}?)(?:\.|,?\s+ЖК|\s+DIM\.RIA|$)",
        r"Розташування\s*[-:]\s*(.{2,120}?)(?:\.|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            location = normalize_space(match.group(1))
            location = re.sub(r"\s+(Показати|Опубліковано|Сьогодні|Вчора)\b.*$", "", location, flags=re.IGNORECASE)
            if location:
                return location

    return None


def save_ad_to_city(ad):
    ensure_ads_storage()
    source_code = ad.get("source") or DEFAULT_SOURCE
    ad_identity = ad.get("ad_id") or canonical_ad_identity(source_code, ad.get("url"))
    ad["ad_id"] = ad_identity
    ad["content_key"] = ad.get("content_key") or ad_content_key(ad)
    if ADS_STORAGE.has_content_key(source_code, ad.get("content_key")):
        return False

    return ADS_STORAGE.upsert_ad(ad)


def is_ad_still_active(ad):
    url = ad.get("url")
    if not url:
        return False

    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except Exception:
        return True

    if response.status_code in (404, 410):
        return False

    if response.status_code >= 500:
        return True

    text = normalize_space(BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)).lower()
    inactive_phrases = [
        "оголошення неактивне",
        "оголошення видалено",
        "оголошення не знайдено",
        "сторінку не знайдено",
        "страница не найдена",
        "объявление неактивно",
        "объявление удалено",
        "object not found",
        "realty not found",
    ]

    return not any(phrase in text for phrase in inactive_phrases)


def remove_inactive_saved_ads(source_code=None, max_checks=25):
    ensure_ads_storage()
    sources = [source_code] if source_code else SOURCE_ORDER
    ads = ADS_STORAGE.get_ads_for_active_check(sources, max_checks)
    removed_total = 0

    if not ads:
        return removed_total

    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        futures = {executor.submit(is_ad_still_active, ad): ad for ad in ads}

        for future in as_completed(futures):
            ad = futures[future]
            current_source = ad.get("source") or DEFAULT_SOURCE
            ad_id = ad.get("ad_id") or canonical_ad_identity(current_source, ad.get("url"))

            try:
                active = future.result()
            except Exception:
                active = True

            if active:
                ADS_STORAGE.update_checked_at(current_source, ad_id)
                continue

            ADS_STORAGE.mark_inactive(current_source, ad_id)
            removed_total += 1
            city_name = ad.get("city") or "Інше"
            print(f"{get_source_name(current_source)} / {city_name}: видалено неактуальне оголошення")

    return removed_total


async def send_to_all(context, text, reply_markup=None):
    for chat_id in load_users():
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
        except Exception as error:
            print(f"Не вдалося надіслати повідомлення {chat_id}: {error}")


async def send_status_to_all(context, text):
    messages = []

    for chat_id in load_users():
        try:
            message = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                disable_web_page_preview=True,
            )
            messages.append(message)
        except Exception as error:
            print(f"Не вдалося надіслати статус {chat_id}: {error}")

    return messages


async def edit_status_messages(messages, text):
    for message in messages:
        try:
            await message.edit_text(text)
        except Exception as error:
            print(f"Не вдалося оновити статус {message.chat_id}: {error}")


def main_menu():
    keyboard = [
        [SOURCES["olx"]["button"], SOURCES["domria"]["button"]],
        ["🌐 Інші джерела"],
        ["⭐ Обране", "📊 Статус"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def source_menu(source_code):
    if not source_code:
        source_code = DEFAULT_SOURCE
    source_name = get_source_name(source_code)
    keyboard = [
        ["🔎 Перевірити зараз", "📂 Категорії"],
        ["🏙️ Містечка", "⭐ Обране"],
        ["⚙️ Фільтри"],
        ["📊 Статус"],
        ["🏠 Головне меню"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def city_detail_menu():
    keyboard = [["⬅️ До містечок"], ["🏠 Головне меню"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def categories_menu(config, source_code=DEFAULT_SOURCE):
    keyboard = []
    row = []

    source_searches = [search for search in config["searches"] if search_source(search) == source_code]

    for index, search in enumerate(source_searches, start=1):
        icon = "✅" if search.get("enabled") else "⬜"
        row.append(f"{icon} {index}. {search['name']}")

        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append(["⬅️ Назад"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def filters_menu(config):
    current_filters = config["filters"]
    empty = "не задано"

    keyboard = [
        [
            f"📏 Мін. площа: {current_filters.get('min_area') or empty}",
            f"📏 Макс. площа: {current_filters.get('max_area') or empty}",
        ],
        [
            f"💰 Мін. ціна: {current_filters.get('min_price') or empty}",
            f"💰 Макс. ціна: {current_filters.get('max_price') or empty}",
        ],
        ["🔑 Ключові слова", "🚫 Стоп-слова"],
        ["🧹 Очистити числові фільтри"],
        ["⬅️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def load_city_ads(source_code=DEFAULT_SOURCE):
    ensure_ads_storage()
    return ADS_STORAGE.load_city_ads(source_code)


def cities_menu(source_code=DEFAULT_SOURCE):
    city_ads = load_city_ads(source_code)

    if not city_ads:
        return ReplyKeyboardMarkup([["⬅️ Назад"]], resize_keyboard=True, is_persistent=True)

    keyboard = []
    row = []

    for city, ads in sorted(city_ads.items()):
        row.append(f"🏙️ {city} ({len(ads)})")

        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append(["⬅️ Назад"])

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def find_city_ads(city_key, source_code=DEFAULT_SOURCE):
    for city, ads in load_city_ads(source_code).items():
        if city_callback_key(city) == city_key:
            return city, ads

    return None, []


def build_city_ads_text(city, ads, limit=None):
    if not ads:
        return "У цьому містечку ще немає збережених оголошень."

    shown_ads = ads if limit is None else ads[-limit:]
    latest_ads = list(reversed(shown_ads))
    text = f"🏙️ {city}\nЗбережених оголошень: {len(ads)}\n\n"

    for index, ad in enumerate(latest_ads, start=1):
        title = ad.get("title", "Без назви")
        url = ad.get("url", "")
        area = ad.get("area")
        price = ad.get("price")
        found_at = ad.get("found_at", "")

        text += f"{index}. {title}\n"
        if area:
            text += f"   📏 {area}\n"
        if price:
            text += f"   💰 {price}\n"
        if found_at:
            text += f"   🕒 {found_at}\n"
        if url:
            text += f"   🔗 {url}\n"
        text += "\n"

    if limit is not None and len(ads) > limit:
        text += f"Показано останні {limit} оголошень."

    if len(text) > 3900:
        text = text[:3850].rsplit("\n", 1)[0] + "\n\nПоказано скорочений список."

    return text.strip()


def build_ad_text(ad, index=None):
    title = ad.get("title", "Без назви")
    url = ad.get("url", "")
    area = ad.get("area")
    price = ad.get("price")
    city = ad.get("city")
    found_at = ad.get("found_at")
    category = ad.get("search_name")

    prefix = f"{index}. " if index is not None else ""
    text = f"{prefix}{title}\n"

    if category:
        text += f"🔎 {category}\n"
    if city:
        text += f"📍 {city}\n"
    if area:
        text += f"📏 Площа: {area}\n"
    if price:
        text += f"💰 Ціна: {price}\n"
    if found_at:
        text += f"🕒 Знайдено: {found_at}\n"
    if url:
        text += f"\n🔗 {url}"

    return text.strip()


def favorite_markup(ad):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("☆ Зберегти в обране", callback_data=f"fav:{ad_key(ad)}")]]
    )


async def delete_tracked_messages(context, chat_id):
    message_ids = context.user_data.get("shown_ad_message_ids", [])
    context.user_data["shown_ad_message_ids"] = []

    for message_id in message_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except BadRequest:
            pass


async def send_city_ads(update, context, city, ads, limit=20):
    chat_id = update.effective_chat.id
    await delete_tracked_messages(context, chat_id)

    if not ads:
        message = await update.message.reply_text(
            "У цьому містечку ще немає збережених оголошень.",
            reply_markup=city_detail_menu(),
        )
        context.user_data["shown_ad_message_ids"] = [message.message_id]
        return

    shown_ads = ads if limit is None else ads[-limit:]
    latest_ads = list(reversed(shown_ads))
    sent_ids = []

    header = await update.message.reply_text(
        f"🏙️ {city}\nЗбережених оголошень: {len(ads)}\nПоказую всі: {len(latest_ads)}.",
        reply_markup=city_detail_menu(),
    )
    await asyncio.sleep(0.4)
    sent_ids.append(header.message_id)

    for index, ad in enumerate(latest_ads, start=1):
        message = await update.message.reply_text(
            
            build_ad_text(ad, index),
            reply_markup=favorite_markup(ad),
            disable_web_page_preview=True,
        )
        await asyncio.sleep(0.4)
        sent_ids.append(message.message_id)

    context.user_data["shown_ad_message_ids"] = sent_ids


def extract_number(text):
    cleaned = re.sub(r"[^\d]", "", text)
    return int(cleaned) if cleaned else None


def parse_compact_number(value):
    value = (value or "").replace("\xa0", " ")
    value = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", value)
    value = value.replace(",", ".")
    value = re.sub(r"[^\d.]", "", value)
    if not value:
        return None

    try:
        number = float(value)
    except ValueError:
        return None

    return int(number) if number.is_integer() else number


def extract_area(text):
    text_lower = text.lower()
    patterns = [
        r"(?:загальна\s+площа|площа(?:\s+ділянки)?)\D{0,20}(\d[\d\s]*(?:[.,]\d+)?)\s*(?:м²|м2|кв\.?\s*м|кв м)",
        r"(\d[\d\s]*(?:[.,]\d+)?)\s*(?:м²|м2|кв\.?\s*м|кв м)",
        r"(\d[\d\s]*(?:[.,]\d+)?)\s*(?:сот|соток|сотки)",
        r"(\d[\d\s]*(?:[.,]\d+)?)\s*(?:га|гектар)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            return parse_compact_number(match.group(1))

    return None


def extract_price(text):
    text_lower = text.lower().replace("\xa0", " ")
    patterns = [
        r"(\d[\d\s]*)\s*(?:\$|usd|дол)",
        r"(?:\$|usd)\s*(\d[\d\s]*)",
        r"(\d[\d\s]*)\s*(?:грн|uah)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            value = parse_compact_number(match.group(1))
            return int(value) if value is not None else None

    return None


def matches_filters(text, filters_config):
    text_lower = text.lower()
    include_keywords = filters_config.get("include_keywords") or []
    exclude_keywords = filters_config.get("exclude_keywords") or []

    if include_keywords and not any(word.lower() in text_lower for word in include_keywords):
        return False

    if exclude_keywords and any(word.lower() in text_lower for word in exclude_keywords):
        return False

    area = extract_area(text)
    if area is not None:
        min_area = filters_config.get("min_area")
        max_area = filters_config.get("max_area")

        if min_area is not None and area < min_area:
            return False
        if max_area is not None and area > max_area:
            return False

    price = extract_price(text)
    if price is not None:
        min_price = filters_config.get("min_price")
        max_price = filters_config.get("max_price")

        if min_price is not None and price < min_price:
            return False
        if max_price is not None and price > max_price:
            return False

    return True


def should_apply_text_filters(ad):
    return (ad.get("source") or DEFAULT_SOURCE) != "domria"


def is_tracked_city(city):
    return city in TRACKED_CITIES


def create_http_session():
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def parse_olx(search, session=None):
    session = session or create_http_session()
    ads = []
    used_keys = set()

    for page in range(1, OLX_MAX_PAGES + 1):
        response = session.get(add_page_param(search["url"], page), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        page_new = 0
        page_candidates = 0

        for link in soup.find_all("a", href=True):
            href = link["href"]
            title = normalize_space(link.get_text(" ", strip=True))

            if "/obyavlenie/" not in href or len(title) < 10:
                continue

            url = clean_url(urljoin("https://m.olx.ua", href))
            ad_identity = canonical_ad_identity("olx", url)
            page_candidates += 1
            if ad_identity in used_keys:
                continue
            if ADS_STORAGE.has_ad("olx", ad_identity):
                used_keys.add(ad_identity)
                continue

            card = link
            for _ in range(4):
                if card.parent:
                    card = card.parent
            card_text = normalize_space(card.get_text(" ", strip=True))
            listing_location = extract_location_from_text(card_text, "olx")

            ads.append(
                {
                    "title": title,
                    "url": url,
                    "ad_id": ad_identity,
                    "search_name": search["name"],
                    "source": "olx",
                    "location": listing_location,
                    "city_hint": detect_city_from_location(listing_location),
                    "area": extract_area(card_text),
                    "price": extract_price(card_text),
                }
            )
            used_keys.add(ad_identity)
            page_new += 1

        if page_candidates == 0 or page_new == 0:
            break

        time.sleep(0.1)

    return ads




def is_domria_ad_url(url):
    parsed = urlparse(url)
    if "dom.ria.com" not in parsed.netloc:
        return False

    path = parsed.path
    return path.startswith("/uk/realty-") and path.endswith(".html")


def build_domria_title(link_text, card_text, search_name=None):
    link_text = normalize_space(link_text)
    title_keywords = r"(продаж|продається|продаю|оренда|здається|купити|орендувати|приміщення|офіс|склад|будинок|ділянк)"
    address_like = re.match(r"^(вул\.|бул\.|просп\.|пров\.|пл\.|рн\b|район\b)", link_text, flags=re.IGNORECASE)

    if (
        len(link_text) >= 10
        and not address_like
        and re.search(title_keywords, link_text, flags=re.IGNORECASE)
        and not re.fullmatch(r"[\d\s$€₴грн]+", link_text, flags=re.IGNORECASE)
    ):
        return link_text

    keyword_match = re.search(
        rf"\b{title_keywords}\b.{10,180}?(?:\.|$)",
        card_text,
        flags=re.IGNORECASE,
    )
    if keyword_match:
        return normalize_space(keyword_match.group(0)).rstrip(".")

    sentences = re.split(r"(?<=[.!?])\s+|\s{2,}", card_text)
    for sentence in sentences:
        sentence = normalize_space(sentence)
        bad_start = ("додати", "перевірено", "топ", "обране")
        bad_content = re.search(r"\d[\d\s]*\s*\$\s+\d[\d\s]*\s*\$", sentence)
        if 20 <= len(sentence) <= 160 and not bad_content and not sentence.lower().startswith(bad_start):
            return sentence

    if link_text and not re.fullmatch(r"[\d\s$€₴грн]+", link_text, flags=re.IGNORECASE):
        prefix = search_name or "Оголошення DOM.RIA"
        return f"{prefix}: {link_text}"

    return link_text or "Оголошення DOM.RIA"


def parse_domria_city(search, category_path, city_name, city_slug):
    session = create_http_session()
    ads = []
    used_keys = set()

    for page in range(1, DOMRIA_MAX_PAGES + 1):
        base_url = f"https://dom.ria.com/uk/{category_path}/{city_slug}/"
        url = add_page_param(base_url, page)

        response = None
        for attempt in range(3):
            try:
                response = session.get(url, timeout=REQUEST_TIMEOUT)
                if response.status_code == 404:
                    return ads
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    delay = int(retry_after) if retry_after and retry_after.isdigit() else 8 + attempt * 8
                    print(f"DOM.RIA: 429 для {city_name}, пауза {delay} c")
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                break
            except Exception as error:
                if attempt == 2:
                    print(f"DOM.RIA: помилка {city_name} {url}: {error}")
                    return ads
                time.sleep(1 + attempt)

        if response is None or response.status_code >= 400:
            status = response.status_code if response is not None else "без відповіді"
            print(f"DOM.RIA: пропускаю {city_name} {url}, статус {status}")
            return ads

        html = response.text
        html = re.split(r"Рекомендовані пропозиції|Ви переглянули всі пропозиції", html, maxsplit=1)[0]
        soup = BeautifulSoup(html, "html.parser")
        page_new = 0
        page_candidates = 0
        page_unknown_candidates = 0

        for link in soup.find_all("a", href=True):
            href = link["href"]
            ad_url = clean_url(urljoin("https://dom.ria.com", href))

            if not is_domria_ad_url(ad_url):
                continue

            page_candidates += 1
            ad_identity = canonical_ad_identity("domria", ad_url)

            if ad_identity in used_keys:
                continue
            if ADS_STORAGE.has_ad("domria", ad_identity):
                used_keys.add(ad_identity)
                continue
            page_unknown_candidates += 1

            card = link
            for _ in range(5):
                if card.parent:
                    card = card.parent

            card_text = normalize_space(card.get_text(" ", strip=True))
            location = extract_location_from_text(card_text, "domria") or city_name
            detected_city = detect_city_from_location(location) or city_name

            title = build_domria_title(link.get_text(" ", strip=True), card_text, search["name"])
            category_keywords = DOMRIA_CATEGORY_KEYWORDS.get(search.get("domria_category")) or []
            if category_keywords:
                keyword_text = f"{title} {card_text} {ad_url}".lower()
                if not any(keyword in keyword_text for keyword in category_keywords):
                    used_keys.add(ad_identity)
                    continue

            ads.append(
                {
                    "title": title,
                    "url": ad_url,
                    "ad_id": ad_identity,
                    "search_name": f"{search['name']} — {detected_city}",
                    "source": "domria",
                    "city_hint": detected_city,
                    "location": location,
                    "area": extract_area(card_text),
                    "price": extract_price(card_text),
                }
            )
            used_keys.add(ad_identity)
            page_new += 1

        if page_candidates == 0 or page_unknown_candidates == 0:
            break

        time.sleep(0.2)

    if ads:
        print(f"DOM.RIA / {search['name']} / {city_name}: {len(ads)} оголошень")

    return ads


def parse_domria(search, session=None):
    ads = []
    used_keys = set()
    search_cache = load_search_cache()
    cache_changed = False
    existing_domria_ads = ADS_STORAGE.load_city_ads("domria")

    category_key = search.get("domria_category")
    category_path = DOMRIA_CATEGORY_PATHS.get(category_key)

    if not category_path:
        return ads

    cities = []
    used_slugs = set()
    for city_name, city_slug in DOMRIA_CITIES.items():
        if city_slug in used_slugs:
            continue
        if city_name not in existing_domria_ads and is_search_cache_active(search_cache, search, city_name):
            continue
        cities.append((city_name, city_slug))
        used_slugs.add(city_slug)

    with ThreadPoolExecutor(max_workers=CITY_WORKERS) as executor:
        futures = {
            executor.submit(parse_domria_city, search, category_path, city_name, city_slug): city_name
            for city_name, city_slug in cities
        }

        for future in as_completed(futures):
            try:
                city_ads = future.result()
            except Exception as error:
                city_name = futures[future]
                print(f"DOM.RIA: помилка обробки {city_name}: {error}")
                continue

            city_name = futures[future]
            if city_ads:
                clear_search_cache(search_cache, search, city_name)
                cache_changed = True
            else:
                if city_name not in existing_domria_ads:
                    set_empty_search_cache(search_cache, search, city_name)
                    cache_changed = True

            for ad in city_ads:
                ad_identity = ad.get("ad_id") or canonical_ad_identity("domria", ad.get("url"))
                if ad_identity in used_keys:
                    continue
                ads.append(ad)
                used_keys.add(ad_identity)

    if cache_changed:
        save_search_cache(search_cache)

    return ads


def parse_search_ads(search):
    source_code = search_source(search)
    session = create_http_session()

    if source_code == "domria":
        return parse_domria(search, session)

    return parse_olx(search, session)

def parse_ad_details(url):
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception:
        return {"description": "", "area": None, "price": None, "location": None, "city": None}

    soup = BeautifulSoup(response.text, "html.parser")
    text = normalize_space(soup.get_text(" ", strip=True))
    location = extract_location_from_text(text)
    city = detect_city_from_location(location)

    return {
        "description": text[:1000],
        "area": extract_area(text),
        "price": extract_price(text),
        "location": location,
        "city": city,
    }


async def check_ads(context: ContextTypes.DEFAULT_TYPE, notify_if_empty=False, source_code=None):
    ensure_ads_storage()
    config = load_config()
    seen = load_seen()
    filters_config = config.get("filters", {})
    new_ads_by_source = {source: [] for source in SOURCE_ORDER}
    seen_this_run = set()
    content_seen_this_run = set()

    sources_to_check = [source_code] if source_code else SOURCE_ORDER

    removed_duplicates = ADS_STORAGE.deactivate_duplicate_content(ad_content_key)
    if removed_duplicates:
        print(f"Видалено дублів оголошень за змістом: {removed_duplicates}")

    removed_inactive = remove_inactive_saved_ads(source_code, max_checks=8)
    if removed_inactive:
        print(f"Видалено неактуальних оголошень: {removed_inactive}")

    for current_source in sources_to_check:
        for search in config["searches"]:
            if search_source(search) != current_source:
                continue
            if not search.get("enabled", False):
                continue

            try:
                ads = parse_search_ads(search)
                print(f"{get_source_name(current_source)} / {search['name']}: знайдено на сайті {len(ads)} оголошень")
            except Exception as error:
                await send_to_all(
                    context,
                    f"⚠️ Помилка при перевірці «{get_source_name(current_source)} / {search['name']}»:\n{error}",
                )
                continue

            fresh_ads = []
            queued_this_search = set()
            for ad in ads:
                ad_source = ad.get("source") or current_source
                ad_identity = ad.get("ad_id") or canonical_ad_identity(ad_source, ad.get("url"))
                ad["ad_id"] = ad_identity
                seen_key = seen_value(ad_source, ad["url"])

                if (
                    ADS_STORAGE.has_ad(ad_source, ad_identity)
                    or seen_key in seen
                    or seen_key in seen_this_run
                    or seen_key in queued_this_search
                    or ad["url"] in seen
                ):
                    continue

                fresh_ads.append(ad)
                queued_this_search.add(seen_key)

            if not fresh_ads:
                continue

            details_by_url = {}
            ads_needing_details = [
                ad
                for ad in fresh_ads
                if (ad.get("source") or current_source) != "domria"
            ]

            for ad in fresh_ads:
                if ad not in ads_needing_details:
                    details_by_url[ad["url"]] = {
                        "description": "",
                        "area": ad.get("area"),
                        "price": ad.get("price"),
                        "location": ad.get("location"),
                        "city": ad.get("city_hint"),
                    }

            with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
                futures = {executor.submit(parse_ad_details, ad["url"]): ad for ad in ads_needing_details}

                for future in as_completed(futures):
                    ad = futures[future]
                    try:
                        details_by_url[ad["url"]] = future.result()
                    except Exception:
                        details_by_url[ad["url"]] = {"description": "", "area": None, "price": None, "location": None, "city": None}

            for ad in fresh_ads:
                ad_source = ad.get("source") or current_source
                seen_key = seen_value(ad_source, ad["url"])
                details = details_by_url.get(ad["url"], {})
                full_text = f"{ad['title']} {details.get('description', '')}"

                if should_apply_text_filters(ad) and not matches_filters(full_text, filters_config):
                    continue

                location = details.get("location") or ad.get("location")
                if ad_source == "domria":
                    detected_city = ad.get("city_hint") or details.get("city") or detect_city_from_location(location)
                else:
                    detected_city = details.get("city") or detect_city_from_location(location)

                if not detected_city and ad.get("city_hint"):
                    detected_city = ad["city_hint"]

                if not detected_city and ad_source != "olx":
                    full_text_city = detect_city(full_text)
                    detected_city = None if full_text_city == "Інше" else full_text_city

                ad["area"] = details.get("area") or ad.get("area")
                ad["price"] = details.get("price") or ad.get("price")
                ad["description"] = details.get("description", "")
                ad["location"] = location
                if ad_source == "domria" and not is_tracked_city(detected_city):
                    continue

                ad["city"] = detected_city or "Інше"
                ad["active"] = True
                ad["found_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                ad["content_key"] = ad_content_key(ad)

                if ad["content_key"] and (
                    ad["content_key"] in content_seen_this_run
                    or ADS_STORAGE.has_content_key(ad_source, ad["content_key"])
                ):
                    seen.add(seen_key)
                    seen_this_run.add(seen_key)
                    continue

                saved_new = save_ad_to_city(ad)
                seen.add(seen_key)
                seen_this_run.add(seen_key)
                if not saved_new:
                    continue
                if ad["content_key"]:
                    content_seen_this_run.add(ad["content_key"])
                new_ads_by_source.setdefault(ad_source, []).append(ad)

    save_seen(seen)

    total_new = sum(len(ads) for ads in new_ads_by_source.values())

    if total_new == 0:
        if notify_if_empty:
            if source_code:
                await send_to_all(context, f"🤖 {get_source_name(source_code)}: нових оголошень немає.")
            else:
                await send_to_all(context, "🤖 Перевірив усі джерела. Нових оголошень немає.")
        return {"new": 0, "removed": removed_inactive}

    for current_source in sources_to_check:
        source_ads = new_ads_by_source.get(current_source, [])
        if not source_ads:
            continue

        await send_to_all(
            context,
            f"🤖 {get_source_name(current_source)}: знайдено нових оголошень: {len(source_ads)}",
        )

        for ad in source_ads:
            area = ad.get("area") or extract_area(ad["title"])
            price = ad.get("price") or extract_price(ad["title"])

            message = (
                f"🏢 Нове оголошення {get_source_name(current_source)}\n\n"
                f"🔎 Категорія: {ad['search_name']}\n"
                f"📍 Населений пункт: {ad.get('city', 'Інше')}\n"
                f"📌 {ad['title']}\n"
            )

            if area:
                message += f"📏 Площа: {area}\n"
            if price:
                message += f"💰 Ціна: {price}\n"

            message += f"\n🔗 {ad['url']}"
            await send_to_all(context, message)
            await asyncio.sleep(0.2)

    return {"new": total_new, "removed": removed_inactive}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_chat.id)

    await update.message.reply_text(
        "Привіт 👋\nКористуйтесь головним меню нижче.",
        reply_markup=main_menu(),
    )


async def favorite_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    add_user(query.message.chat_id)

    data = query.data or ""
    if not data.startswith("fav:"):
        return

    key = data.split(":", 1)[1]
    ad = find_ad_by_key(key)

    if not ad:
        await query.answer("Оголошення не знайдено.", show_alert=True)
        return

    added = add_favorite(query.message.chat_id, ad)
    if added:
        await query.answer("Збережено в обране.")
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("✓ В обраному", callback_data=f"fav:{key}")]]
                )
            )
        except BadRequest:
            pass
    else:
        await query.answer("Вже є в обраному.")


def build_status_text(config, source_code=None):
    if source_code:
        text = f"📊 Активні налаштування {get_source_name(source_code)}:\n\n"
    else:
        text = "📊 Активні налаштування:\n\n"

    for search in config["searches"]:
        if source_code and search_source(search) != source_code:
            continue
        icon = "✅" if search.get("enabled") else "⬜"
        text += f"{icon} {search['name']}\n"

    current_filters = config.get("filters", {})
    empty = "не задано"

    text += "\n⚙️ Фільтри:\n"
    text += f"📏 Мін. площа: {current_filters.get('min_area') or empty}\n"
    text += f"📏 Макс. площа: {current_filters.get('max_area') or empty}\n"
    text += f"💰 Мін. ціна: {current_filters.get('min_price') or empty}\n"
    text += f"💰 Макс. ціна: {current_filters.get('max_price') or empty}\n"
    text += "\n🔑 Ключові слова:\n"
    text += ", ".join(current_filters.get("include_keywords") or []) or empty
    text += "\n\n🚫 Стоп-слова:\n"
    text += ", ".join(current_filters.get("exclude_keywords") or []) or empty

    return text


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update.effective_chat.id)
    text = update.message.text.strip()
    config = load_config()
    current_source = get_current_source(context)

    filter_name = context.user_data.get("waiting_for_filter")

    if text == "⬅️ До містечок":
        context.user_data["waiting_for_filter"] = None
        await delete_tracked_messages(context, update.effective_chat.id)
        city_ads = load_city_ads(current_source)
        message = (
            "🏙️ Оберіть містечко зі збереженими оголошеннями:"
            if city_ads
            else "🏙️ Поки що немає збережених оголошень по містечках."
        )
        await update.message.reply_text(message, reply_markup=cities_menu(current_source))
        return

    if text == "🏠 Головне меню":
        context.user_data["waiting_for_filter"] = None
        context.user_data["current_source"] = None
        await delete_tracked_messages(context, update.effective_chat.id)
        await update.message.reply_text("Головне меню джерел:", reply_markup=main_menu())
        return

    if text == "⬅️ Назад":
        context.user_data["waiting_for_filter"] = None
        await delete_tracked_messages(context, update.effective_chat.id)

        current_source = context.user_data.get("current_source")

        if current_source:
            await update.message.reply_text(
                f"{get_source_button_title(current_source)}: меню оголошень",
                reply_markup=source_menu(current_source),
            )
        else:
            await update.message.reply_text(
                "Головне меню джерел:",
                reply_markup=main_menu(),
            )

        return

    if not filter_name:
        for source_key, source in SOURCES.items():
            if text == source["button"]:
                context.user_data["current_source"] = source_key
                await update.message.reply_text(
                    f"{source['name']}: меню оголошень",
                    reply_markup=source_menu(source_key),
                )
                return

        if text == "🌐 Інші джерела":
            await update.message.reply_text(
                "Можна додати Rieltor.ua або Flatfy.",
                reply_markup=main_menu(),
            )
            return

        current_source = get_current_source(context)

        if text == "🔎 Перевірити зараз":
            status_message = await update.message.reply_text(
                f"⏳ Оновлення {get_source_name(current_source)}...\nПошук триває, зачекайте.",
                reply_markup=source_menu(current_source),
            )
            try:
                result = await check_ads(context, notify_if_empty=False, source_code=current_source)
                await status_message.edit_text(
                    "✅ Оновлення завершено.\n"
                    f"Нових оголошень: {result.get('new', 0)}\n"
                    f"Видалено неактуальних: {result.get('removed', 0)}"
                )
            except Exception as error:
                await status_message.edit_text(f"❌ Оновлення не завершилось:\n{error}")
            return

        if text == "📂 Категорії":
            await update.message.reply_text(
                "📂 Оберіть категорію, щоб увімкнути або вимкнути її:",
                reply_markup=categories_menu(config, current_source),
            )
            return

        if text == "🏙️ Містечка":
            await delete_tracked_messages(context, update.effective_chat.id)
            city_ads = load_city_ads(current_source)
            message = (
                "🏙️ Оберіть містечко зі збереженими оголошеннями:"
                if city_ads
                else "🏙️ Поки що немає збережених оголошень по містечках."
            )
            await update.message.reply_text(message, reply_markup=cities_menu(current_source))
            return

        if text == "⭐ Обране":
            await delete_tracked_messages(context, update.effective_chat.id)
            favorites = get_user_favorites(update.effective_chat.id)
            if context.user_data.get("current_source"):
                favorites = [ad for ad in favorites if ad.get("source", DEFAULT_SOURCE) == current_source]

            if not favorites:
                await update.message.reply_text(
                    "⭐ В обраному поки що немає оголошень.",
                    reply_markup=source_menu(current_source) if context.user_data.get("current_source") else main_menu(),
                )
                return

            sent_ids = []
            header = await update.message.reply_text(
                f"⭐ Обране\nЗбережених оголошень: {len(favorites)}",
                reply_markup=main_menu(),
            )
            sent_ids.append(header.message_id)

            for index, ad in enumerate(reversed(favorites[-10:]), start=1):
                message = await update.message.reply_text(
                    build_ad_text(ad, index),
                    disable_web_page_preview=True,
                )
                sent_ids.append(message.message_id)

            context.user_data["shown_ad_message_ids"] = sent_ids
            return

        if text == "⚙️ Фільтри":
            await update.message.reply_text(
                "⚙️ Налаштування фільтрів:",
                reply_markup=filters_menu(config),
            )
            return

        if text == "📊 Статус":
            await update.message.reply_text(
                build_status_text(config, current_source),
                reply_markup=source_menu(current_source),
            )
            return

        category_match = re.match(r"^[✅⬜]\s*(\d+)\.", text)
        if category_match:
            index = int(category_match.group(1)) - 1
            source_searches = [search for search in config["searches"] if search_source(search) == current_source]

            if 0 <= index < len(source_searches):
                selected_id = source_searches[index].get("id")
                search = next((item for item in config["searches"] if item.get("id") == selected_id), None)

                if search:
                    search["enabled"] = not search.get("enabled", False)
                    save_config(config)
                    state = "увімкнено" if search["enabled"] else "вимкнено"
                    await update.message.reply_text(
                        f"✅ «{search['name']}» {state}.",
                        reply_markup=categories_menu(config, current_source),
                    )
                return

            await update.message.reply_text(
                "Не знайшов таку категорію.",
                reply_markup=categories_menu(config, current_source),
            )
            return

        if text.startswith("🏙️ ") and "(" in text and text.endswith(")"):
            city_name = text[3:].rsplit(" (", 1)[0].strip()
            city_key = city_callback_key(city_name)
            city, ads = find_city_ads(city_key, current_source)
            await send_city_ads(update, context, city or city_name, ads)
            return

        filter_prompts = {
            "📏 Мін. площа": ("min_area", "Введіть мінімальну площу. Наприклад: 50"),
            "📏 Макс. площа": ("max_area", "Введіть максимальну площу. Наприклад: 200"),
            "💰 Мін. ціна": ("min_price", "Введіть мінімальну ціну. Наприклад: 10000"),
            "💰 Макс. ціна": ("max_price", "Введіть максимальну ціну. Наприклад: 50000"),
            "🔑 Ключові слова": (
                "include_keywords",
                "Введіть ключові слова через кому.\nНаприклад: магазин, склад, фасад, офіс",
            ),
            "🚫 Стоп-слова": (
                "exclude_keywords",
                "Введіть стоп-слова через кому.\nНаприклад: гараж, паркомісце",
            ),
        }

        for prefix, (name, prompt) in filter_prompts.items():
            if text.startswith(prefix):
                context.user_data["waiting_for_filter"] = name
                await update.message.reply_text(prompt, reply_markup=filters_menu(config))
                return

        if text == "🧹 Очистити числові фільтри":
            config["filters"]["min_area"] = None
            config["filters"]["max_area"] = None
            config["filters"]["min_price"] = None
            config["filters"]["max_price"] = None
            save_config(config)
            await update.message.reply_text(
                "Числові фільтри очищено.",
                reply_markup=filters_menu(config),
            )
            return

        await update.message.reply_text(
            "Оберіть дію на клавіатурі знизу:",
            reply_markup=source_menu(current_source) if context.user_data.get("current_source") else main_menu(),
        )
        return

    if filter_name in ["min_area", "max_area", "min_price", "max_price"]:
        number = extract_number(text)

        if number is None:
            await update.message.reply_text("Введіть число. Наприклад: 50")
            return

        config["filters"][filter_name] = number

    elif filter_name in ["include_keywords", "exclude_keywords"]:
        words = [word.strip().lower() for word in text.split(",") if word.strip()]
        config["filters"][filter_name] = words

    save_config(config)
    context.user_data["waiting_for_filter"] = None

    await update.message.reply_text(
        "✅ Фільтр збережено.",
        reply_markup=filters_menu(config),
    )


async def auto_check(context: ContextTypes.DEFAULT_TYPE):
    status_messages = await send_status_to_all(
        context,
        "⏳ Планове оновлення...\nБот перевіряє нові оголошення, зачекайте.",
    )

    try:
        result = await check_ads(context, notify_if_empty=False)
        await edit_status_messages(
            status_messages,
            "✅ Планове оновлення завершено.\n"
            f"Нових оголошень: {result.get('new', 0)}\n"
            f"Видалено неактуальних: {result.get('removed', 0)}",
        )
        await refresh_user_menus(context)
    except Exception as error:
        await edit_status_messages(status_messages, f"❌ Планове оновлення не завершилось:\n{error}")
        await send_to_all(context, f"❌ Помилка автоперевірки:\n{error}")


async def refresh_user_menus(context: ContextTypes.DEFAULT_TYPE):
    users = load_users()

    for chat_id in users:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="🔄 Бот оновлено. Меню актуалізовано.",
                reply_markup=main_menu(),
            )
            await asyncio.sleep(0.5)
        except Exception as error:
            print(f"Не вдалося оновити меню для {chat_id}: {error}")


def main():
    if not BOT_TOKEN:
        raise ValueError("Не знайдено TELEGRAM_BOT_TOKEN у .env")

    ensure_ads_storage()

    app = Application.builder().token(BOT_TOKEN).build()

    if app.job_queue is None:
        print('JobQueue не встановлено. Виконайте: pip install "python-telegram-bot[job-queue]"')
    else:
        app.job_queue.run_once(refresh_user_menus, when=3)
        app.job_queue.run_repeating(auto_check, interval=3600, first=3600)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(favorite_button_handler, pattern=r"^fav:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Бот запущений. Відкрийте Telegram і напишіть /start")
    app.run_polling()


if __name__ == "__main__":
    main()

