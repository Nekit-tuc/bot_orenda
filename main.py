import json
import hashlib
import os
import re
import time
from copy import deepcopy
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
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
ALWAYS_VISIBLE_CITIES = ["Житомир"]

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}

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

CITY_ALIASES = {
    "Житомир": [
        "Житомир",
        "Житомира",
        "Житомирі",
        "Житомиру",
        "Житомиром",
        "м. Житомир",
        "місто Житомир",
    ],
}

DEFAULT_CONFIG = {
    "searches": [
        {
            "id": "sale_commercial",
            "name": "Продаж комерції",
            "url": "https://m.olx.ua/uk/nedvizhimost/kommercheskaya-nedvizhimost/prodazha-kommercheskoy-nedvizhimosti/zht/",
            "enabled": True,
        },
        {
            "id": "sale_apartments",
            "name": "Продаж квартир",
            "url": "https://m.olx.ua/uk/nedvizhimost/kvartiry/prodazha-kvartir/zht/",
            "enabled": False,
        },
        {
            "id": "sale_houses",
            "name": "Продаж будинків",
            "url": "https://m.olx.ua/uk/nedvizhimost/doma/prodazha-domov/zht/",
            "enabled": True,
        },
        {
            "id": "sale_maf",
            "name": "Продаж МАФів / кіосків",
            "url": "https://m.olx.ua/uk/nedvizhimost/kommercheskaya-nedvizhimost/prodazha-kommercheskoy-nedvizhimosti/zht/q-%D0%BC%D0%B0%D1%84/",
            "enabled": True,
        },
        {
            "id": "rent_commercial",
            "name": "Оренда комерції",
            "url": "https://m.olx.ua/uk/nedvizhimost/kommercheskaya-nedvizhimost/arenda-kommercheskoy-nedvizhimosti/zht/",
            "enabled": False,
        },
        {
            "id": "rent_houses",
            "name": "Оренда будинків",
            "url": "https://m.olx.ua/uk/nedvizhimost/doma/arenda-domov/zht/",
            "enabled": False,
        },
        {
            "id": "rent_maf",
            "name": "Оренда МАФів / кіосків",
            "url": "https://m.olx.ua/uk/nedvizhimost/kommercheskaya-nedvizhimost/arenda-kommercheskoy-nedvizhimosti/zht/q-%D0%BC%D0%B0%D1%84/",
            "enabled": False,
        },
        {
            "id": "rent_apartments",
            "name": "Оренда квартир",
            "url": "https://m.olx.ua/uk/nedvizhimost/kvartiry/arenda-kvartir/zht/",
            "enabled": False,
        },
        {
            "id": "sale_land",
            "name": "Продаж земельних ділянок",
            "url": "https://m.olx.ua/uk/nedvizhimost/zemlya/prodazha-zemli/zht/",
            "enabled": False,
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


def save_json_file(path, data):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_config():
    config = load_json_file(CONFIG_FILE, DEFAULT_CONFIG)

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

    for key, value in DEFAULT_CONFIG["filters"].items():
        config["filters"].setdefault(key, deepcopy(value))

    save_config(config)
    return config


def save_config(config):
    save_json_file(CONFIG_FILE, config)


def load_seen():
    return set(load_json_file(SEEN_FILE, []))


def save_seen(seen):
    save_json_file(SEEN_FILE, sorted(seen))


def load_users():
    return set(str(user) for user in load_json_file(USERS_FILE, []))


def save_users(users):
    save_json_file(USERS_FILE, sorted(users))


def add_user(chat_id):
    users = load_users()
    users.add(str(chat_id))
    save_users(users)


def load_favorites():
    favorites = load_json_file(FAVORITES_FILE, {})
    return favorites if isinstance(favorites, dict) else {}


def save_favorites(favorites):
    save_json_file(FAVORITES_FILE, favorites)


def ad_key(ad):
    value = ad.get("url") or ad.get("title", "")
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
    for ads in load_city_ads().values():
        for ad in ads:
            if ad_key(ad) == key:
                return ad

    for ads in load_favorites().values():
        for ad in ads:
            if ad.get("key") == key or ad_key(ad) == key:
                return ad

    return None


def normalize_filename(name):
    safe_name = re.sub(r"[^А-Яа-яІіЇїЄєҐґA-Za-z0-9_ -]", "", name)
    return safe_name.strip().replace(" ", "_") or "Інше"


def city_callback_key(city):
    normalized = normalize_filename(city).lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def detect_city(text):
    letters = "А-Яа-яІіЇїЄєҐґA-Za-z"

    for city in sorted(set(CITIES), key=len, reverse=True):
        aliases = CITY_ALIASES.get(city, [city])

        for alias in aliases:
            pattern = rf"(?<![{letters}]){re.escape(alias)}(?![{letters}])"
            if re.search(pattern, text, flags=re.IGNORECASE):
                return "смт Гришківці" if city == "Гришківці" else city

    return "Інше"


def save_ad_to_city(ad):
    os.makedirs(ADS_DIR, exist_ok=True)

    city = ad.get("city") or "Інше"
    path = os.path.join(ADS_DIR, f"{normalize_filename(city)}.json")
    ads = load_json_file(path, [])

    if not any(item.get("url") == ad.get("url") for item in ads):
        ads.append(ad)
        save_json_file(path, ads)


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


def main_menu():
    keyboard = [
        ["🔎 Перевірити зараз", "📂 Категорії"],
        ["🏙️ Містечка", "⭐ Обране"],
        ["⚙️ Фільтри"],
        ["📊 Статус"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def city_detail_menu():
    keyboard = [["⬅️ До містечок"], ["🏠 Головне меню"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def categories_menu(config):
    keyboard = []
    row = []

    for index, search in enumerate(config["searches"], start=1):
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


def load_city_ads():
    city_ads = {city: [] for city in ALWAYS_VISIBLE_CITIES}

    if not os.path.isdir(ADS_DIR):
        return city_ads


    for filename in sorted(os.listdir(ADS_DIR)):
        if not filename.endswith(".json"):
            continue

        path = os.path.join(ADS_DIR, filename)
        ads = load_json_file(path, [])

        if not ads:
            continue

        city = ads[0].get("city") or os.path.splitext(filename)[0].replace("_", " ")
        city_ads[city] = ads

    return city_ads


def cities_menu():
    city_ads = load_city_ads()

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


def find_city_ads(city_key):
    for city, ads in load_city_ads().items():
        if city_callback_key(city) == city_key:
            return city, ads

    return None, []


def build_city_ads_text(city, ads, limit=10):
    if not ads:
        return "У цьому містечку ще немає збережених оголошень."

    latest_ads = list(reversed(ads[-limit:]))
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

    if len(ads) > limit:
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


async def send_city_ads(update, context, city, ads, limit=10):
    chat_id = update.effective_chat.id
    await delete_tracked_messages(context, chat_id)

    if not ads:
        message = await update.message.reply_text(
            "У цьому містечку ще немає збережених оголошень.",
            reply_markup=city_detail_menu(),
        )
        context.user_data["shown_ad_message_ids"] = [message.message_id]
        return

    latest_ads = list(reversed(ads[-limit:]))
    sent_ids = []

    header = await update.message.reply_text(
        f"🏙️ {city}\nЗбережених оголошень: {len(ads)}\nПоказую останні {len(latest_ads)}.",
        reply_markup=city_detail_menu(),
    )
    sent_ids.append(header.message_id)

    for index, ad in enumerate(latest_ads, start=1):
        message = await update.message.reply_text(
            build_ad_text(ad, index),
            reply_markup=favorite_markup(ad),
            disable_web_page_preview=True,
        )
        sent_ids.append(message.message_id)

    context.user_data["shown_ad_message_ids"] = sent_ids


def extract_number(text):
    cleaned = re.sub(r"[^\d]", "", text)
    return int(cleaned) if cleaned else None


def extract_area(text):
    text_lower = text.lower()
    patterns = [
        r"(\d+(?:[.,]\d+)?)\s*(?:м²|м2|кв\.?\s*м|кв м)",
        r"(\d+(?:[.,]\d+)?)\s*(?:сот|соток|сотки)",
        r"(\d+(?:[.,]\d+)?)\s*(?:га|гектар)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            return float(match.group(1).replace(",", "."))

    return None


def extract_price(text):
    text_lower = text.lower().replace(" ", "")
    patterns = [
        r"(\d+)\$",
        r"\$(\d+)",
        r"(\d+)(?:грн|uah)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            return int(match.group(1))

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


def parse_olx(search):
    response = requests.get(search["url"], headers=REQUEST_HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    ads = []
    used_urls = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        title = link.get_text(" ", strip=True)

        if "/obyavlenie/" not in href or len(title) < 10:
            continue

        url = urljoin("https://m.olx.ua", href)
        if url in used_urls:
            continue

        ads.append(
            {
                "title": title,
                "url": url,
                "search_name": search["name"],
            }
        )
        used_urls.add(url)

    return ads


def parse_ad_details(url):
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
        response.raise_for_status()
    except Exception:
        return {"description": "", "area": None, "price": None}

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    return {
        "description": text[:1000],
        "area": extract_area(text),
        "price": extract_price(text),
    }


async def check_ads(context: ContextTypes.DEFAULT_TYPE, notify_if_empty=False):
    config = load_config()
    seen = load_seen()
    filters_config = config.get("filters", {})
    all_new_ads = []

    for search in config["searches"]:
        if not search.get("enabled", False):
            continue

        try:
            ads = parse_olx(search)
        except Exception as error:
            await send_to_all(
                context,
                f"⚠️ Помилка при перевірці «{search['name']}»:\n{error}",
            )
            continue

        for ad in ads:
            if ad["url"] in seen:
                continue

            seen.add(ad["url"])
            details = parse_ad_details(ad["url"])
            full_text = f"{ad['title']} {details.get('description', '')}"

            if not matches_filters(full_text, filters_config):
                continue

            ad["area"] = details.get("area")
            ad["price"] = details.get("price")
            ad["description"] = details.get("description", "")
            ad["city"] = detect_city(full_text)
            ad["active"] = True
            ad["found_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

            save_ad_to_city(ad)
            all_new_ads.append(ad)
            time.sleep(1)

    save_seen(seen)

    if not all_new_ads:
        if notify_if_empty:
            await send_to_all(context, "🤖 Перевірив. Нових оголошень немає.")
        return

    await send_to_all(
        context,
        f"🤖 Перевірив пошук.\nЗнайдено нових оголошень: {len(all_new_ads)}",
    )

    for ad in all_new_ads:
        area = ad.get("area") or extract_area(ad["title"])
        price = ad.get("price") or extract_price(ad["title"])

        message = (
            "🏢 Нове оголошення\n\n"
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
        time.sleep(1)


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


def build_status_text(config):
    text = "📊 Активні налаштування:\n\n"

    for search in config["searches"]:
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

    filter_name = context.user_data.get("waiting_for_filter")

    if text == "⬅️ До містечок":
        context.user_data["waiting_for_filter"] = None
        await delete_tracked_messages(context, update.effective_chat.id)
        city_ads = load_city_ads()
        message = (
            "🏙️ Оберіть містечко зі збереженими оголошеннями:"
            if city_ads
            else "🏙️ Поки що немає збережених оголошень по містечках."
        )
        await update.message.reply_text(message, reply_markup=cities_menu())
        return

    if text == "🏠 Головне меню":
        context.user_data["waiting_for_filter"] = None
        await delete_tracked_messages(context, update.effective_chat.id)
        await update.message.reply_text("Головне меню:", reply_markup=main_menu())
        return

    if text == "⬅️ Назад":
        context.user_data["waiting_for_filter"] = None
        await delete_tracked_messages(context, update.effective_chat.id)
        await update.message.reply_text(
            "Головне меню:",
            reply_markup=main_menu(),
        )
        return

    if not filter_name:
        if text == "🔎 Перевірити зараз":
            await update.message.reply_text(
                "🔎 Перевіряю нові оголошення...",
                reply_markup=main_menu(),
            )
            await check_ads(context, notify_if_empty=True)
            return

        if text == "📂 Категорії":
            await update.message.reply_text(
                "📂 Оберіть категорію, щоб увімкнути або вимкнути її:",
                reply_markup=categories_menu(config),
            )
            return

        if text == "🏙️ Містечка":
            await delete_tracked_messages(context, update.effective_chat.id)
            city_ads = load_city_ads()
            message = (
                "🏙️ Оберіть містечко зі збереженими оголошеннями:"
                if city_ads
                else "🏙️ Поки що немає збережених оголошень по містечках."
            )
            await update.message.reply_text(message, reply_markup=cities_menu())
            return

        if text == "⭐ Обране":
            await delete_tracked_messages(context, update.effective_chat.id)
            favorites = get_user_favorites(update.effective_chat.id)

            if not favorites:
                await update.message.reply_text(
                    "⭐ В обраному поки що немає оголошень.",
                    reply_markup=main_menu(),
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
                build_status_text(config),
                reply_markup=main_menu(),
            )
            return

        category_match = re.match(r"^[✅⬜]\s*(\d+)\.", text)
        if category_match:
            index = int(category_match.group(1)) - 1

            if 0 <= index < len(config["searches"]):
                search = config["searches"][index]
                search["enabled"] = not search.get("enabled", False)
                save_config(config)
                state = "увімкнено" if search["enabled"] else "вимкнено"
                await update.message.reply_text(
                    f"✅ «{search['name']}» {state}.",
                    reply_markup=categories_menu(config),
                )
            else:
                await update.message.reply_text(
                    "Не знайшов таку категорію.",
                    reply_markup=categories_menu(config),
                )
            return

        if text.startswith("🏙️ ") and "(" in text and text.endswith(")"):
            city_name = text[3:].rsplit(" (", 1)[0].strip()
            city_key = city_callback_key(city_name)
            city, ads = find_city_ads(city_key)
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
            reply_markup=main_menu(),
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
    try:
        await check_ads(context, notify_if_empty=False)
    except Exception as error:
        await send_to_all(context, f"❌ Помилка автоперевірки:\n{error}")


async def refresh_user_menus(context: ContextTypes.DEFAULT_TYPE):
    users = load_users()

    for chat_id in users:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Меню оновлено.",
                reply_markup=main_menu(),
            )
        except Exception as error:
            print(f"Не вдалося оновити меню для {chat_id}: {error}")


def main():
    if not BOT_TOKEN:
        raise ValueError("Не знайдено TELEGRAM_BOT_TOKEN у .env")

    app = Application.builder().token(BOT_TOKEN).build()

    if app.job_queue is None:
        print('JobQueue не встановлено. Виконайте: pip install "python-telegram-bot[job-queue]"')
    else:
        app.job_queue.run_once(refresh_user_menus, when=3)
        app.job_queue.run_repeating(auto_check, interval=3600, first=30)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(favorite_button_handler, pattern=r"^fav:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Бот запущений. Відкрийте Telegram і напишіть /start")
    app.run_polling()


if __name__ == "__main__":
    main()
