"""
app.py — «ПостМастер AI»: генератор постов о товаре с помощью нейросети.

Как это работает:
1. Пользователь вставляет ссылку на товар с маркетплейса (Ozon, Wildberries,
   Яндекс Маркет или любой другой магазин).
2. Сайт скачивает страницу товара и достаёт из неё название, описание
   и главную картинку (Open Graph-разметка или JSON-LD).
3. Данные товара и настройки стиля из файла voice.md уходят в OpenRouter
   (модель openrouter/free — бесплатный роутер моделей, Free Models Router).
4. Нейросеть возвращает готовый пост, сайт показывает его в блоке «Готовый пост».

Ключ API лежит в отдельном файле секретов .env — он не попадает в репозиторий.
Запуск: python app.py → http://127.0.0.1:5000
"""

import html as html_module
import json
import random
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Flask, redirect, render_template, request, url_for

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
VOICE_FILE = BASE_DIR / "voice.md"
SECRETS_FILE = BASE_DIR / ".env"
FAVORITES_FILE = BASE_DIR / "data" / "favorites.json"  # «база» избранного — обычный JSON


# ============================================================
# 1. СЕКРЕТЫ (файл .env) И НАСТРОЙКИ ПРИЛОЖЕНИЯ
# ============================================================

def load_secrets():
    """Читает файл .env и возвращает словарь с ключами и настройками.

    Формат файла — по одной настройке в строке: ИМЯ=значение.
    Пустые строки и строки, которые начинаются с #, пропускаются.
    """
    secrets = {}
    if not SECRETS_FILE.exists():
        return secrets

    for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        secrets[key.strip()] = value.strip().strip('"').strip("'")

    return secrets


# Значения по умолчанию, если в .env чего-то не хватает
DEFAULT_MODEL = "openrouter/free"
DEFAULT_API_URL = "https://openrouter.ai/api/v1/chat/completions"


def openrouter_config():
    """Возвращает настройки OpenRouter из файла .env.

    Файл читается при каждом запросе, поэтому после вставки ключа
    сайт не нужно перезапускать — достаточно обновить страницу.
    """
    secrets = load_secrets()

    return {
        "key": secrets.get("OPENROUTER_API_KEY", ""),
        "model": secrets.get("OPENROUTER_MODEL") or DEFAULT_MODEL,
        "url": secrets.get("OPENROUTER_BASE_URL") or DEFAULT_API_URL,
        "app_url": secrets.get("APP_URL") or "http://127.0.0.1:5000",
        "app_title": secrets.get("APP_TITLE") or "PostMaster AI",
    }


def vk_config():
    """Возвращает настройки ВКонтакте из файла .env."""
    secrets = load_secrets()

    return {
        "token": secrets.get("VK_ACCESS_TOKEN", ""),
        "group_id": re.sub(r"\D", "", secrets.get("VK_GROUP_ID", "")),  # только цифры
    }


def ascii_header(value, fallback="PostMaster AI"):
    """HTTP-заголовки могут содержать только латиницу — лишние символы убираем."""
    text = str(value).encode("ascii", "ignore").decode("ascii").strip()
    return text or fallback


# Заголовки «как у браузера»: некоторые магазины не отдают страницу роботам
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


# ============================================================
# 2. НАСТРОЙКИ ГОЛОСА ИЗ ФАЙЛА voice.md
# ============================================================

# Если в voice.md чего-то не хватает — берутся эти значения
DEFAULT_VOICE = {
    "тон": "дружелюбно и живо, как будто советуешь находку другу",
    "длина": "средняя",
    "эмодзи": "4",
    "стиль заголовка": "эмодзи + название",
    "хэштеги": "да",
}

# Настроения, которые показываются, если voice.md не найден или пуст
DEFAULT_MOODS = ["Радостное", "Деловое", "Дерзкое", "Заботливое"]

# Эмодзи для кнопок выбора настроения
MOOD_EMOJI = {
    "радостное": "🎉",
    "деловое": "📈",
    "дерзкое": "🔥",
    "заботливое": "🤗",
}


def load_voice():
    """
    Читает voice.md и возвращает два словаря:
      * общие настройки (блок «## Общие настройки»);
      * настройки каждого настроения (блоки «## Настроение: Радостное»).

    Внутри блока настройки записаны строками вида «ключ: значение».
    Строки, которые начинаются с #, >, -, | или <!--, — подсказки, их пропускаем.
    """
    global_settings = {}
    moods = {}

    if not VOICE_FILE.exists():
        return global_settings, moods

    current = None  # куда складывать прочитанные строки

    for raw_line in VOICE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if line.startswith("## "):
            title = line[3:].strip()
            title_low = title.lower()
            if title_low.startswith("настроение:"):
                # Пример: «## Настроение: Радостное» → название «Радостное»
                mood_name = title.split(":", 1)[1].strip()
                moods.setdefault(mood_name, {})
                current = moods[mood_name]
            elif "общ" in title_low:
                current = global_settings
            else:
                current = None  # другой раздел — пропускаем
            continue

        if current is None:
            continue

        if not line or line[0] in "#>-|<" or line.startswith("```"):
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        current[key.strip().lower()] = value.strip()

    return global_settings, moods


def voice_settings(mood):
    """Итоговые настройки настроения: по умолчанию → общие → блок настроения."""
    global_settings, moods = load_voice()

    settings = dict(DEFAULT_VOICE)
    settings.update(global_settings)
    settings.update(moods.get(mood, {}))

    return settings


def mood_options():
    """Список настроений для формы: [{'name': 'Радостное', 'emoji': '🎉'}, ...]."""
    _, moods = load_voice()
    names = list(moods.keys()) or DEFAULT_MOODS

    return [
        {"name": name, "emoji": MOOD_EMOJI.get(name.lower(), "✨")}
        for name in names
    ]


def normalize_length(value):
    """Приводит настройку «длина» к одному из трёх вариантов."""
    value = str(value).lower()
    if "корот" in value:
        return "короткая"
    if "длин" in value:
        return "длинная"
    return "средняя"


def parse_emoji(value):
    """Достаёт число эмодзи из настройки. Если числа нет — берём 4."""
    digits = re.search(r"\d+", str(value))
    return int(digits.group()) if digits else 4


# ============================================================
# 3. ДАННЫЕ ТОВАРА ПО ССЫЛКЕ
# ============================================================

def normalize_url(raw):
    """Приводит ссылку к виду https://... (если пользователь забыл протокол)."""
    url = (raw or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url.lstrip("/")
    return url


def is_valid_url(url):
    """Проверяет, что это похоже на адрес сайта."""
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and "." in parsed.netloc


def name_from_url(url):
    """Пытается вытащить название товара из адреса страницы.

    Например: /product/keramicheskaya-kruzhka-utro-123456/ → «keramicheskaya kruzhka utro».
    """
    parts = [part for part in urlparse(url).path.split("/") if part]
    if not parts:
        return ""

    slug = max(parts, key=len)  # самый длинный кусок адреса — обычно название
    slug = re.sub(r"\.(html?|aspx|php)$", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"[-_+]+", " ", slug)   # дефисы и подчёркивания → пробелы
    slug = re.sub(r"\d{2,}", " ", slug)   # убираем длинные числа (артикулы)
    slug = re.sub(r"\s+", " ", slug).strip()

    if not re.search(r"[a-zA-Zа-яА-Я]", slug):
        return ""
    return slug[:80]


def _meta_content(html, key):
    """Достаёт значение <meta property="og:title" content="...">.

    Атрибуты могут идти в любом порядке, поэтому проверяем два варианта.
    """
    patterns = (
        rf'<meta[^>]+(?:property|name)=["\']{key}["\'][^>]*content=["\']([^"\']*)["\']',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{key}["\']',
    )
    for pattern in patterns:
        found = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if found:
            return html_module.unescape(found.group(1)).strip()
    return ""


def _find_product_in_json(data):
    """Рекурсивно ищет в JSON-LD словарь с типом Product."""
    if isinstance(data, list):
        for item in data:
            found = _find_product_in_json(item)
            if found:
                return found
        return None

    if isinstance(data, dict):
        types = data.get("@type")
        if types == "Product" or (isinstance(types, list) and "Product" in types):
            return data
        for value in data.values():
            found = _find_product_in_json(value)
            if found:
                return found

    return None


def _jsonld_product(html):
    """Ищет данные товара в блоках <script type="application/ld+json">."""
    blocks = re.findall(
        r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    )

    for block in blocks:
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue

        product = _find_product_in_json(data)
        if not product:
            continue

        image = product.get("image")
        if isinstance(image, list):
            image = image[0] if image else ""
        if isinstance(image, dict):
            image = image.get("url", "")

        return {
            "name": str(product.get("name") or "").strip(),
            "description": str(product.get("description") or "").strip(),
            "image": str(image or "").strip(),
        }

    return {"name": "", "description": "", "image": ""}


def load_product(url):
    """
    Скачивает страницу товара и достаёт название, описание и главную картинку.

    Возвращает словарь:
      name        — название товара;
      description — описание со страницы;
      image       — ссылка на главную картинку;
      read_ok     — True, если страницу удалось прочитать;
      note        — пояснение для пользователя (что получилось, а что нет).
    """
    product = {"name": "", "description": "", "image": "", "read_ok": False, "note": ""}

    try:
        response = requests.get(
            url,
            headers=BROWSER_HEADERS,
            timeout=15,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        # Маркетплейсы часто закрывают доступ роботам — это нормально,
        # поэтому работаем дальше: название возьмём из адреса ссылки.
        product["name"] = name_from_url(url)
        status = getattr(getattr(error, "response", None), "status_code", None)
        if status == 404:
            product["note"] = (
                "Страница не найдена (404). Проверьте ссылку — возможно, товар уже снят с продажи."
            )
        else:
            product["note"] = (
                "Магазин не отдал страницу роботу (так бывает у Ozon и Wildberries). "
                "Нейросеть соберёт пост по ссылке и названию из адреса."
            )
        return product

    page = page_text(response)
    product["read_ok"] = True

    # 1. Пробуем Open Graph-разметку и JSON-LD — их используют почти все магазины
    jsonld = _jsonld_product(page)
    name = _meta_content(page, "og:title") or jsonld["name"]
    description = _meta_content(page, "og:description") or jsonld["description"]
    image = _meta_content(page, "og:image") or jsonld["image"]

    # 2. Запасные варианты: <title> и обычный description
    if not name:
        title = re.search(r"<title[^>]*>(.*?)</title>", page, re.IGNORECASE | re.DOTALL)
        if title:
            name = html_module.unescape(title.group(1)).strip()
    if not description:
        description = _meta_content(page, "description")

    product["name"] = name[:300]
    product["description"] = description[:1500]
    product["image"] = _image_url(image)

    if not product["name"]:
        product["name"] = name_from_url(url)
        product["note"] = "На странице не нашлось названия — взяли его из адреса ссылки."
    if not product["image"]:
        product["note"] = (
            product["note"] or "Главную картинку найти не удалось, но название и описание есть."
        )

    return product


def _image_url(image):
    """Приводит ссылку на картинку к полному адресу (https://...)."""
    image = (image or "").strip()
    if image.startswith("//"):
        return "https:" + image
    if image.startswith("/"):
        return ""  # относительные ссылки без домена не покажем
    return image[:500]


def page_text(response):
    """Возвращает HTML страницы в правильной кодировке.

    Если магазин не указал кодировку в заголовках, requests по умолчанию
    считает её latin-1 — тогда русский текст превращается в «кракозябры».
    Поэтому кодировку определяем по содержимому страницы.
    """
    encoding = (response.encoding or "").lower()
    if encoding in ("", "iso-8859-1", "ascii"):
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


# ============================================================
# 4. ЗАПРОС К НЕЙРОСЕТИ ЧЕРЕЗ OPENROUTER
# ============================================================

SYSTEM_PROMPT = """Ты — креативный копирайтер и SMM-специалист.
Ты пишешь живые посты о товарах для социальных сетей (ВКонтакте, Telegram) на русском языке.

Жёсткие правила:
1. Пиши только по-русски. Никаких английских слов, латиницы и транслита
   (исключение — название товара, если оно само написано латиницей).
2. Не выдумывай факты: цены, скидки, характеристики, сроки доставки и гарантии.
   Если данных нет — пиши эмоционально и образно, но без конкретных цифр.
3. Избегай шаблонных рекламных фраз: «не упустите возможность», «идеальное решение»,
   «качественный товар», «широкий ассортимент», «спешите заказать».
4. Не вставляй в текст ссылки и адреса сайтов — читатель получит их отдельно.
5. Не используй markdown: никаких **звёздочек**, ## заголовков и списков с тире.
6. В ответе — только текст поста. Без пояснений, без подписей «Хэштеги:»,
   без комментариев о том, что ты сделал.
"""

# Творческие приёмы: каждый раз выбирается случайный,
# поэтому два поста по одной ссылке получаются разными
CREATIVE_ANGLES = (
    "личная история «как я искал(а) такой товар»",
    "неожиданное сравнение с чем-то из быта",
    "вопрос-крючок в первой строке",
    "мини-сценка из жизни покупателя",
    "короткий дружеский совет",
    "лёгкая самоирония и юмор",
    "честный разбор «кому подойдёт, а кому нет»",
    "неожиданный факт о пользе такого товара",
)

LENGTH_HINTS = {
    "короткая": "2–4 коротких предложения, без списков",
    "средняя": "5–8 предложений в 1–2 абзаца",
    "длинная": "10–14 предложений в 2–3 абзаца",
}


class AiError(Exception):
    """Ошибка при обращении к нейросети — с понятным текстом для пользователя."""


def style_instructions(settings):
    """Превращает настройки из voice.md в инструкции для нейросети."""
    length = normalize_length(settings["длина"])
    emoji_count = parse_emoji(settings["эмодзи"])
    heading = str(settings["стиль заголовка"]).lower()
    hashtags = str(settings.get("хэштеги", "")).lower()

    if "вопрос" in heading:
        heading_rule = "первая строка — короткий вопрос к читателю (до 8 слов)"
    elif "капс" in heading:
        heading_rule = "первая строка — заголовок КАПСЛОКОМ, до 5 слов"
    elif "эмодзи" in heading:
        heading_rule = "первая строка — короткий заголовок, который начинается с одного эмодзи"
    else:
        heading_rule = "первая строка — короткий заголовок без эмодзи"

    if emoji_count <= 0:
        emoji_rule = "эмодзи не используй совсем"
    else:
        emoji_rule = f"не больше {emoji_count} эмодзи во всём тексте"

    if hashtags.startswith("нет") or hashtags == "no":
        hashtag_rule = "хэштеги в конце не добавляй"
    else:
        hashtag_rule = "в конце добавь 3–5 коротких хэштегов в одну строку"

    return "\n".join(
        (
            f"- Эмоция поста: {settings['тон']}",
            f"- Длина: {LENGTH_HINTS[length]}",
            f"- Эмодзи: {emoji_rule}",
            f"- Заголовок: {heading_rule}",
            f"- Хэштеги: {hashtag_rule}",
        )
    )


def build_user_prompt(product, url, note, mood, angle, settings):
    """Собирает запрос для нейросети из данных товара и настроек стиля."""
    lines = [f"Напиши один пост о товаре. Настроение поста: {mood}.", "", "Данные о товаре:"]
    lines.append(f"- Ссылка: {url}")
    lines.append(f"- Название: {product['name'] or 'неизвестно (определи по ссылке)'}")

    if product["description"]:
        lines.append(f"- Описание со страницы: {product['description']}")
    else:
        lines.append("- Описание со страницы: недоступно (не выдумывай характеристики)")

    if note:
        lines.append(f"- Пожелание автора: {note}")

    lines += ["", "Настройки стиля (из файла voice.md):", style_instructions(settings)]
    lines += ["", f"Творческий приём для этого варианта: {angle}."]
    lines.append("Сделай текст живым, интересным и непохожим на обычную рекламу.")

    return "\n".join(lines)


def clean_ai_text(text):
    """Убирает кавычки, markdown, ссылки и служебные подписи вокруг ответа модели."""
    text = (text or "").strip()

    # 1. Обёртки вида ```текст``` и подписи «Готовый пост:»
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(
        r"^(готовый пост|текст поста|пост|вариант поста)\s*[:\-]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # 2. Ссылки внутри поста не нужны — они и так есть в карточке товара
    text = re.sub(r"https?://\S+", "", text)

    # 2а. Управляющие символы: некоторые провайдеры добавляют в ответ
    # «мусорные» нули и другие невидимые символы — вырезаем их
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = text.replace("\t", " ")

    # 3. Остатки markdown: **жирный**, ## заголовки, подпись «Хэштеги:»
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)  # «## Заголовок» → «Заголовок», но «#хэштег» не трогаем
    text = re.sub(r"(?mi)^(хэштеги|теги)\s*:\s*", "", text)

    # 4. Лишние пробелы и пустые строки
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+([.,!?…])", r"\1", text)  # «слово .» → «слово.»

    # 5. Кавычки вокруг всего текста
    if len(text) > 1 and text[0] in "«\"“" and text[-1] in "»\"”":
        text = text[1:-1].strip()

    return text.strip()


# Бесплатные модели иногда «думают» и возвращают пустой текст,
# поэтому запрос повторяется. Роутер каждый раз выбирает другую модель.
MAX_ATTEMPTS = 3


def clean_edited_text(text):
    """Аккуратно причёсывает текст, который пользователь правил вручную.

    Здесь минимум вмешательства: убираем лишние пробелы в конце строк
    и лишние пустые строки, чтобы пост выглядел опрятно в ленте.
    """
    text = (text or "").replace("\r\n", "\n").strip()
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def ask_model(user_prompt):
    """Отправляет запрос в OpenRouter. Возвращает (текст поста, название модели)."""
    config = openrouter_config()

    if not config["key"]:
        raise AiError(
            "Не найден ключ OpenRouter. Откройте файл .env в папке проекта, "
            "вставьте ключ в строку OPENROUTER_API_KEY=... и обновите страницу."
        )

    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.9,  # выше значение — разнообразнее и креативнее тексты
        "max_tokens": 1200,  # запас токенов: часть моделей тратит их на «размышления»
        "reasoning": {"effort": "low"},  # просим модели не растекаться мыслью
    }

    headers = {
        "Authorization": f"Bearer {config['key']}",
        "Content-Type": "application/json",
        "HTTP-Referer": ascii_header(config["app_url"], "http://127.0.0.1:5000"),
        "X-Title": ascii_header(config["app_title"]),  # необязательно, название приложения
    }

    for _ in range(MAX_ATTEMPTS):
        content, model_name = _send_request(config["url"], headers, payload)
        post = clean_ai_text(content)

        if post:
            return post, model_name
        # Пустой ответ (модель потратила лимит на размышления) — пробуем ещё раз

    raise AiError(
        "Бесплатные модели не смогли ответить с первого раза. "
        "Нажмите «Сформировать пост» ещё раз."
    )


def _send_request(url, headers, payload):
    """Один запрос к OpenRouter. Возвращает (текст ответа, название модели)."""
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=90)
    except requests.exceptions.Timeout:
        raise AiError("Нейросеть не ответила за 90 секунд. Попробуйте ещё раз.")
    except (requests.exceptions.RequestException, UnicodeError) as error:
        raise AiError(f"Не удалось связаться с OpenRouter: {error}")

    # Понятные подсказки для частых ошибок
    if response.status_code == 401:
        raise AiError("OpenRouter не принял ключ (ошибка 401). Проверьте ключ в файле .env.")
    if response.status_code == 402:
        raise AiError("На счёте OpenRouter закончились кредиты (ошибка 402).")
    if response.status_code == 429:
        raise AiError(
            "Слишком много запросов к бесплатным моделям (ошибка 429). "
            "Подождите минуту и попробуйте снова."
        )
    if response.status_code != 200:
        raise AiError(f"OpenRouter вернул ошибку {response.status_code}. Попробуйте ещё раз.")

    try:
        data = response.json()
        message = data["choices"][0]["message"]
        content = message.get("content") or ""  # у «думающих» моделей тут может быть null
        model_name = data.get("model", payload["model"])
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise AiError("Ответ нейросети пришёл в неожиданном формате. Попробуйте ещё раз.")

    return content, model_name


# ============================================================
# 5. ПУБЛИКАЦИЯ В СООБЩЕСТВЕ ВКОНТАКТЕ
# ============================================================

VK_API_URL = "https://api.vk.com/method/wall.post"
VK_API_VERSION = "5.199"  # версия API ВКонтакте

# Минимальный запас времени для отложенного поста (в секундах)
MIN_SCHEDULE_DELAY = 120

# Понятные пояснения к ошибкам ВКонтакте
VK_ERRORS = {
    5: "ВКонтакте не принял токен (ошибка 5). Проверьте VK_ACCESS_TOKEN в файле .env.",
    6: "Слишком много запросов к ВКонтакте. Подождите минуту.",
    9: "Слишком много одинаковых запросов. Подождите немного и повторите.",
    15: (
        "Нет прав на публикацию (ошибка 15). Включите у ключа права «Доступ к стене» "
        "и «Управление сообществом»."
    ),
    100: "Неверные параметры запроса (ошибка 100). Проверьте VK_GROUP_ID — нужны только цифры.",
    214: "Публикация на стене сообщества запрещена (ошибка 214). Проверьте настройки стены.",
    150: "Стена сообщества закрыта (ошибка 150). Разрешите публикацию в настройках сообщества.",
}


class VkError(Exception):
    """Ошибка публикации — с понятным текстом для пользователя."""


def publish_to_vk(text, publish_at=None):
    """Публикует пост на стене сообщества.

    text       — текст поста;
    publish_at — время публикации (unix-время). Если не указано — пост выходит сразу.

    Возвращает (post_id, ссылка_на_пост).
    """
    config = vk_config()

    if not config["token"] or not config["group_id"]:
        raise VkError(
            "ВКонтакте не подключён. Добавьте VK_ACCESS_TOKEN и VK_GROUP_ID в файл .env "
            "и обновите страницу."
        )

    params = {
        "owner_id": f"-{config['group_id']}",  # минус = публикация от имени сообщества
        "from_group": 1,
        "message": text,
        "access_token": config["token"],
        "v": VK_API_VERSION,
    }
    if publish_at:
        params["publish_date"] = publish_at  # ВКонтакте сам опубликует пост в это время

    try:
        response = requests.post(VK_API_URL, data=params, timeout=30)
    except requests.exceptions.Timeout:
        raise VkError("ВКонтакте не ответил за 30 секунд. Попробуйте ещё раз.")
    except requests.exceptions.RequestException as error:
        raise VkError(f"Не удалось связаться с ВКонтакте: {error}")

    try:
        data = response.json()
    except ValueError:
        raise VkError("ВКонтакте вернул непонятный ответ. Попробуйте ещё раз.")

    if "error" in data:
        code = data["error"].get("error_code")
        text_error = data["error"].get("error_msg", "")
        raise VkError(VK_ERRORS.get(code, f"ВКонтакте вернул ошибку {code}: {text_error}"))

    post_id = data.get("response", {}).get("post_id")
    if not post_id:
        raise VkError("ВКонтакте не вернул номер поста. Попробуйте ещё раз.")

    link = f"https://vk.com/wall-{config['group_id']}_{post_id}"
    return post_id, link


def parse_publish_time(value):
    """Превращает значение поля «дата и время» в отметку времени (unix).

    Возвращает (timestamp, datetime) или бросает VkError с подсказкой.
    """
    try:
        moment = datetime.strptime((value or "").strip(), "%Y-%m-%dT%H:%M")
    except ValueError:
        raise VkError("Не получилось прочитать дату и время. Выберите время в календаре заново.")

    timestamp = int(moment.timestamp())
    if timestamp < time.time() + MIN_SCHEDULE_DELAY:
        raise VkError(
            "Время публикации должно быть хотя бы на 2 минуты позже текущего. "
            "Выберите время ещё раз."
        )

    return timestamp, moment


def plural(count, one, few, many):
    """Русское склонение: 1 пост, 2 поста, 5 постов."""
    if count % 10 == 1 and count % 100 != 11:
        return one
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return few
    return many


def min_schedule_value():
    """Самая ранняя дата для календаря (через 2 минуты) в формате поля datetime-local."""
    earliest = datetime.fromtimestamp(time.time() + MIN_SCHEDULE_DELAY)
    return earliest.strftime("%Y-%m-%dT%H:%M")


# ============================================================
# 6. ИЗБРАННОЕ (хранится в JSON-файле, без базы данных)
# ============================================================

def load_favorites():
    """Читает список сохранённых постов из data/favorites.json."""
    if not FAVORITES_FILE.exists():
        return []

    try:
        data = json.loads(FAVORITES_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []

    return data if isinstance(data, list) else []


def save_favorites(items):
    """Записывает список избранного в файл (папку создаём при необходимости)."""
    FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    FAVORITES_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_favorite(text, title="", url="", mood=""):
    """Добавляет пост в избранное. Возвращает True, если пост действительно новый."""
    text = (text or "").strip()
    if not text:
        return False

    items = load_favorites()
    if any(item.get("text") == text for item in items):  # такой пост уже есть
        return False

    items.insert(
        0,
        {
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "title": (title or "Пост из ПостМастера")[:120],
            "url": url,
            "mood": mood,
            "created": datetime.now().strftime("%d.%m.%Y %H:%M"),
        },
    )
    save_favorites(items)
    return True


def delete_favorite(favorite_id):
    """Удаляет пост из избранного по его id."""
    items = load_favorites()
    remaining = [item for item in items if item.get("id") != favorite_id]
    save_favorites(remaining)
    return len(remaining) != len(items)



def settings_for_screen(settings):
    """Короткая подпись настроек для панели «Голос поста (из voice.md)»."""
    tone = str(settings["тон"])
    if len(tone) > 44:  # длинное описание тона аккуратно сокращаем
        tone = tone[:44].rstrip() + "…"

    return [
        ("Тон", tone),
        ("Длина", normalize_length(settings["длина"])),
        ("Эмодзи", str(parse_emoji(settings["эмодзи"]))),
        ("Заголовок", settings["стиль заголовка"]),
    ]


@app.route("/", methods=["GET", "POST"])
def index():
    """Главная страница: генерация поста, публикация в ВК и избранное.

    Одна страница обрабатывает четыре действия (поле формы action):
      generate       — сгенерировать пост по ссылке (нейросеть);
      favorite       — сохранить готовый пост в избранное;
      publish_now    — опубликовать пост в сообществе прямо сейчас;
      publish_later  — отложить публикацию на выбранное время.
    """
    moods = mood_options()
    form = {"url": "", "note": "", "mood": moods[0]["name"]}

    post = ""
    warning = ""       # подсказка про пустую или неправильную ссылку
    error_text = ""    # ошибка нейросети или ВКонтакте
    message = ""       # сообщение об успехе (избранное / публикация)
    message_link = ""  # ссылка на опубликованный пост в ВК
    message_type = ""
    product = None
    product_name = ""
    product_url = ""
    model_name = ""
    angle = ""

    if request.method == "POST":
        action = request.form.get("action", "generate")

        # Общие поля формы (они есть в каждом действии)
        form["url"] = request.form.get("url", "").strip()
        form["note"] = request.form.get("note", "").strip()[:300]

        chosen = request.form.get("mood", "").strip()
        known = [mood["name"] for mood in moods]
        form["mood"] = chosen if chosen in known else moods[0]["name"]

        product_name = request.form.get("product_name", "").strip()[:200]
        product_url = normalize_url(form["url"]) if form["url"] else ""

        if action == "save_edit":
            # Пользователь отредактировал пост вручную и нажал «Сохранить»
            post = clean_edited_text(request.form.get("post", ""))

            if not post:
                error_text = "Пост не может быть пустым. Напишите текст и сохраните ещё раз."
            else:
                message = "Изменения сохранены. Теперь пост можно опубликовать или отложить."
                message_type = "success"
        elif action in ("favorite", "publish_now", "publish_later"):
            # Эти действия работают с уже готовым текстом поста
            post = request.form.get("post", "").strip()

            if not post:
                error_text = "Текст поста потерялся. Сформируйте пост заново."
            elif action == "favorite":
                if add_favorite(post, product_name, product_url, form["mood"]):
                    message = "Пост сохранён в избранное."
                    message_type = "success"
                else:
                    message = "Такой пост уже есть в избранном."
                    message_type = "info"
            elif action == "publish_now":
                try:
                    _, link = publish_to_vk(post)
                    message = "Пост опубликован в сообществе ВКонтакте."
                    message_link = link
                    message_type = "success"
                except VkError as vk_error:
                    error_text = str(vk_error)
            else:  # publish_later
                try:
                    timestamp, moment = parse_publish_time(
                        request.form.get("publish_at", "")
                    )
                    _, link = publish_to_vk(post, publish_at=timestamp)
                    message = (
                        "Пост отложен: он появится в сообществе "
                        f"{moment.strftime('%d.%m.%Y в %H:%M')}."
                    )
                    message_link = link
                    message_type = "success"
                except VkError as vk_error:
                    error_text = str(vk_error)
        else:
            # action == "generate" — обычная генерация поста по ссылке
            url = normalize_url(form["url"])

            if not form["url"]:
                warning = "Вставьте ссылку на товар — без неё нейросети нечего обрабатывать."
            elif not is_valid_url(url):
                warning = (
                    "Это не похоже на ссылку. Пример: "
                    "https://www.ozon.ru/product/keramicheskaya-kruzhka-123456/"
                )
            else:
                settings = voice_settings(form["mood"])
                angle = random.choice(CREATIVE_ANGLES)  # каждый пост получается другим

                # 1. Достаём данные товара со страницы
                product = load_product(url)

                # 2. Просим нейросеть написать пост
                prompt = build_user_prompt(
                    product, url, form["note"], form["mood"], angle, settings
                )
                try:
                    post, model_name = ask_model(prompt)
                    product_name = product["name"]
                    product_url = url
                except AiError as ai_error:
                    error_text = str(ai_error)

    settings = voice_settings(form["mood"])
    config = openrouter_config()
    vk = vk_config()

    return render_template(
        "index.html",
        form=form,
        moods=moods,
        post=post,
        warning=warning,
        error_text=error_text,
        message=message,
        message_link=message_link,
        message_type=message_type,
        product=product,
        product_name=product_name,
        product_url=product_url,
        model_name=model_name,
        angle=angle,
        voice_view=settings_for_screen(settings),
        ai_model=config["model"],
        has_key=bool(config["key"]),
        vk_ready=bool(vk["token"] and vk["group_id"]),
        min_schedule=min_schedule_value(),
        favorites=load_favorites(),
        favorites_word=plural(len(load_favorites()), "пост", "поста", "постов"),
    )


@app.route("/favorites/delete", methods=["POST"])
def favorites_delete():
    """Удаляет пост из избранного и возвращает на главную страницу."""
    delete_favorite(request.form.get("favorite_id", ""))
    return redirect(url_for("index"))


# Запуск сервера: python app.py → http://127.0.0.1:5000
if __name__ == "__main__":
    if not openrouter_config()["key"]:
        print("=" * 60)
        print("⚠️  Ключ OpenRouter не найден.")
        print("   Откройте файл .env и вставьте ключ в строку OPENROUTER_API_KEY=")
        print("   Ключ можно создать здесь: https://openrouter.ai/keys")
        print("=" * 60)

    app.run(debug=True)
