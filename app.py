"""
app.py — «ПостМастер»: генератор постов для товара.

Как это работает:
1. Пользователь заполняет форму на сайте (название, описание, цена, настроение).
2. Flask получает данные формы и вызывает функцию build_post().
3. build_post() собирает текст по шаблону — правила берутся из файла voice.md.
4. Готовый пост возвращается на страницу в блок «Готовый пост».

Никаких API и баз данных: только Flask, Python и файл настроек voice.md.
Запуск: python app.py  →  http://127.0.0.1:5000
"""

import re
from pathlib import Path

from flask import Flask, render_template, request

app = Flask(__name__)

# ============================================================
# 1. ПУТИ И ЗНАЧЕНИЯ ПО УМОЛЧАНИЮ
# ============================================================

# Папка, в которой лежит app.py (нужна, чтобы найти voice.md при любом запуске).
BASE_DIR = Path(__file__).resolve().parent
VOICE_FILE = BASE_DIR / "voice.md"

# Настройки по умолчанию. Используются, если в voice.md чего-то не хватает.
# Менять стиль постов лучше в voice.md — там всё по-человечески описано.
DEFAULT_VOICE = {
    "тон": "дружелюбный",
    "длина": "средняя",
    "эмодзи": "4",
    "стиль заголовка": "эмодзи + название",
    "вступление": "",
    "хэштеги": "",
}

# Настроения, которые показываются, если voice.md не найден или пуст.
DEFAULT_MOODS = ["Радостное", "Деловое", "Дерзкое", "Заботливое"]

# Эмодзи для заголовка — по названию настроения.
MOOD_EMOJI = {
    "радостное": "🎉",
    "деловое": "📈",
    "дерзкое": "🔥",
    "заботливое": "🤗",
}

# Финальная фраза-подпись поста. Ключ — часть значения «тон» из voice.md.
# Например, тон «дружелюбный» содержит «дружелюб» → берём первую фразу.
TONE_SIGNS = (
    ("дружелюб", "😊 Будем рады, если заглянете!"),
    ("уверен", "✅ Качество проверено — уверенно рекомендуем."),
    ("дерзк", "😎 Хватит думать — берите, пока есть."),
    ("заботл", "🤗 Если появятся вопросы — напишите, с радостью поможем."),
)
DEFAULT_SIGN = "💬 Будем рады вашему заказу!"


# ============================================================
# 2. ЧТЕНИЕ ФАЙЛА voice.md
# ============================================================

def load_voice():
    """
    Читает voice.md и возвращает два словаря:
      * общие настройки (блок «## Общие настройки»);
      * настройки для каждого настроения (блоки «## Настроение: Радостное»).

    Формат строки внутри блока: "ключ: значение".
    Строки, которые начинаются с #, >, -, | или <!--, считаются подсказками
    и программа их пропускает.
    """
    global_settings = {}
    moods = {}

    if not VOICE_FILE.exists():
        return global_settings, moods

    current = None  # куда складывать прочитанные строки

    for raw_line in VOICE_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        # Заголовок блока — решаем, что читаем дальше
        if line.startswith("## "):
            title = line[3:].strip()
            title_low = title.lower()
            if title_low.startswith("настроение:"):
                # Пример: "## Настроение: Радостное" → название "Радостное"
                mood_name = title.split(":", 1)[1].strip()
                moods.setdefault(mood_name, {})
                current = moods[mood_name]
            elif "общ" in title_low:
                current = global_settings
            else:
                current = None  # какой-то другой раздел — пропускаем
            continue

        # Всё, что вне нужного блока, не читаем
        if current is None:
            continue

        # Подсказки, разделители и пустые строки пропускаем
        if not line or line[0] in "#>-|<" or line.startswith("```"):
            continue

        # Строка настроек должна содержать двоеточие: "тон: дружелюбный"
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        current[key.strip().lower()] = value.strip()

    return global_settings, moods


def voice_settings(mood):
    """
    Собирает итоговые настройки для одного настроения:
    значения по умолчанию → общие настройки из voice.md → блок настроения.
    """
    global_settings, moods = load_voice()

    settings = dict(DEFAULT_VOICE)        # 1. база
    settings.update(global_settings)      # 2. общие настройки из voice.md
    settings.update(moods.get(mood, {}))  # 3. конкретное настроение

    return settings


def mood_options():
    """Список настроений для формы: [{'name': 'Радостное', 'emoji': '🎉'}, ...]."""
    _, moods = load_voice()
    names = list(moods.keys()) or DEFAULT_MOODS

    return [
        {"name": name, "emoji": MOOD_EMOJI.get(name.lower(), "✨")}
        for name in names
    ]


# Регулярное выражение для эмодзи (картинки + смайлики-символы).
# Нужно, чтобы аккуратно ограничить количество эмодзи в посте.
EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF]\uFE0F?"
)

# ============================================================
# 3. МЕЛКИЕ ПОМОЩНИКИ ДЛЯ ТЕКСТА
# ============================================================

def clean_text(text):
    """Убирает лишние пробелы и переносы строк."""
    return " ".join(text.split())


def as_sentence(text):
    """Делает из строки красивое предложение: с большой буквы и точкой в конце."""
    text = text.strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?…":
        text += "."
    return text


def truncate(text, limit):
    """Обрезает текст по границе слова и добавляет многоточие."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:—–-")
    return cut + "…"


def normalize_length(value):
    """Приводит значение настройки «длина» к одному из трёх вариантов."""
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


def limit_emoji(text, limit):
    """Оставляет в тексте только первые `limit` эмодзи (остальные удаляет)."""
    seen = [0]

    def replace(match):
        seen[0] += 1
        return match.group(0) if seen[0] <= limit else ""

    return EMOJI_RE.sub(replace, text)



# ============================================================
# 4. СБОРКА ПОСТА ПО ШАБЛОНУ
# ============================================================

def build_heading(name, style, emoji):
    """Первая строка поста. Оформление выбирает настройка «стиль заголовка»."""
    title = name or "Новая находка"
    style = str(style).lower()

    if "вопрос" in style:
        return f"Ищете: {title}?" if name else "Ищете что-то особенное?"
    if "капс" in style:
        return title.upper()
    if "эмодзи" in style:
        return f"{emoji} {title}"
    return title  # стиль «просто»


def build_price_line(price):
    """Строка про цену или выгоду. Если поле пустое — строки не будет."""
    price = clean_text(price)
    if not price:
        return ""

    # Слова, которые говорят о том, что это не цена, а выгода или акция
    benefit_words = ("скидк", "акци", "выгод", "подар", "бесплат", "%")

    has_digit = re.search(r"\d", price)
    is_benefit = any(word in price.lower() for word in benefit_words)

    if has_digit and not is_benefit:
        return f"💰 Цена: {price}"
    return f"🎁 Выгода: {price}"


def tone_sign(tone):
    """Финальная фраза поста — выбирается по настройке «тон»."""
    tone = str(tone).lower()
    for key, sign in TONE_SIGNS:
        if key in tone:
            return sign
    return DEFAULT_SIGN


def build_post(name, description, price, mood):
    """
    Главная функция: собирает готовый пост из блоков.

    Порядок блоков:
      заголовок → вступление → описание → цена/выгода → финальная фраза → хэштеги.
    Какие блоки попадут в пост, решают настройки из voice.md.
    """
    settings = voice_settings(mood)
    length = normalize_length(settings["длина"])
    emoji_count = parse_emoji(settings["эмодзи"])
    emoji = MOOD_EMOJI.get(str(mood).lower(), "✨")

    parts = []

    # 1. Заголовок
    parts.append(build_heading(name, settings["стиль заголовка"], emoji))

    # 2. Вступление — живая фраза из voice.md (в коротком посте не нужна)
    if length != "короткая" and settings.get("вступление"):
        parts.append(as_sentence(settings["вступление"]))

    # 3. Описание товара — главный блок
    body = clean_text(description)
    if length == "короткая":
        body = truncate(body, 180)  # короткий пост — обрезаем описание
    parts.append(as_sentence(body))

    # 4. Цена или выгода
    price_line = build_price_line(price)
    if price_line:
        parts.append(price_line)

    # 5. Финальная фраза-подпись (по настройке «тон»)
    if length != "короткая":
        parts.append(tone_sign(settings["тон"]))

    # 6. Хэштеги — только в длинном посте
    if length == "длинная" and settings.get("хэштеги"):
        parts.append(settings["хэштеги"])

    post = "\n\n".join(part for part in parts if part)

    # Ограничиваем количество эмодзи и убираем лишние пробелы после чистки
    post = limit_emoji(post, emoji_count)
    post = re.sub(r"[ \t]{2,}", " ", post)
    post = re.sub(r"[ \t]+\n", "\n", post)
    post = re.sub(r"\n{3,}", "\n\n", post)

    return post.strip(), settings


def settings_for_screen(settings):
    """Короткая подпись настроек для блока «Готовый пост» — видно, что взято из voice.md."""
    return [
        ("Тон", settings["тон"]),
        ("Длина", normalize_length(settings["длина"])),
        ("Эмодзи", str(parse_emoji(settings["эмодзи"]))),
        ("Заголовок", settings["стиль заголовка"]),
    ]


# ============================================================
# 5. МАРШРУТ САЙТА
# ============================================================

@app.route("/", methods=["GET", "POST"])
def index():
    """Главная страница: показывает форму и (если получилось) готовый пост."""
    moods = mood_options()
    form = {"name": "", "description": "", "price": "", "mood": moods[0]["name"]}
    post = ""
    warning = ""

    if request.method == "POST":
        # Забираем данные из формы
        form["name"] = request.form.get("name", "").strip()
        form["description"] = request.form.get("description", "").strip()
        form["price"] = request.form.get("price", "").strip()

        chosen = request.form.get("mood", "").strip()
        known = [mood["name"] for mood in moods]
        form["mood"] = chosen if chosen in known else moods[0]["name"]

        # Проверка обязательного поля: без описания пост не собрать
        if not form["description"]:
            warning = (
                "Заполните описание товара — это обязательное поле, "
                "без него пост не собрать."
            )
        else:
            post, _ = build_post(
                form["name"], form["description"], form["price"], form["mood"]
            )

    settings = voice_settings(form["mood"])

    return render_template(
        "index.html",
        form=form,
        moods=moods,
        post=post,
        warning=warning,
        voice_view=settings_for_screen(settings),
    )


# Запуск сервера: python app.py → http://127.0.0.1:5000
if __name__ == "__main__":
    app.run(debug=True)

