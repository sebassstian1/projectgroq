from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from collections import defaultdict
from datetime import date
from dotenv import load_dotenv
import httpx, time, logging, os

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get("SECRET_KEY", "fallback_key_for_dev")

GROQ_KEY = os.environ.get("GROQ_KEY")
RECAPTCHA_SECRET = os.environ.get("RECAPTCHA_SECRET")

USERS = {
    os.environ.get("ADMIN_USER", "admin"): os.environ.get("ADMIN_PASS", ""),
    os.environ.get("FRIEND_USER", "friend"): os.environ.get("FRIEND_PASS", "")
}

DAILY_LIMIT = 20

daily_usage = defaultdict(lambda: {"date": None, "count": 0})

logging.basicConfig(
    filename='requests.log',
    level=logging.INFO,
    format='%(asctime)s — %(message)s'
)

@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        captcha = request.form.get("g-recaptcha-response", "")

        if not captcha:
            error = "Пройдите капчу"
        else:
            verify = httpx.post(
                "https://www.google.com/recaptcha/api/siteverify",
                data={
                    "secret": RECAPTCHA_SECRET,
                    "response": captcha
                }
            )
            if not verify.json().get("success"):
                error = "Капча не пройдена"
            elif username in USERS and USERS[username] == password:
                session["logged_in"] = True
                session["username"] = username
                return redirect(url_for("index"))
            else:
                error = "Неверный логин или пароль"

    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/summarize", methods=["POST"])
def summarize():
    if not session.get("logged_in"):
        return jsonify({"result": "Нет доступа"}), 401

    user = session.get("username", "admin")
    today = str(date.today())

    if daily_usage[user]["date"] != today:
        daily_usage[user] = {"date": today, "count": 0}

    if daily_usage[user]["count"] >= DAILY_LIMIT:
        return jsonify({"result": f"Лимит {DAILY_LIMIT} запросов в день исчерпан. Возвращайся в Кыргыстан."})

    data = request.json
    text = data.get("text", "")
    model = data.get("model", "llama-3.3-70b-versatile")
    style = data.get("style", "brief")
    t0 = time.time()

    style_instructions = {
        "brief":    "Напиши краткое резюме в 3-5 предложениях. Только самое главное.",
        "detailed": "Напиши подробный анализ: все ключевые идеи, факты, аргументы и выводы. Структурируй по разделам.",
        "bullets":  "Оформи резюме в виде маркированного списка (буллеты). Каждый пункт — отдельная идея.",
        "eli5":     "Объясни содержание текста простым языком, как будто читатель — школьник. Никакого жаргона.",
    }
    style_text = style_instructions.get(style, style_instructions["brief"])

    prompt = f"""Ты эксперт по анализу и извлечению смысла из текстов.

Стиль резюме: {style_text}

Общие правила:
- Сохрани все ключевые идеи, факты и выводы
- Убери воду, повторения и второстепенные детали
- Пиши на русском языке
- Если в тексте есть числа, даты или имена — обязательно сохрани их

Текст для анализа:
{text}"""

    try:
        response = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1024
            },
            timeout=30
        )
        response.raise_for_status()
        result = response.json()["choices"][0]["message"]["content"]
        daily_usage[user]["count"] += 1
        logging.info(f"пользователь: {user} | модель: {model} | стиль: {style} | символов: {len(text)} | время: {round(time.time() - t0, 2)}s | запросов сегодня: {daily_usage[user]['count']}/{DAILY_LIMIT}")
        return jsonify({"result": result})

    except httpx.HTTPStatusError as e:
        logging.error(f"Groq HTTP {e.response.status_code}: {e.response.text[:200]}")
        return jsonify({"result": f"Groq API вернул ошибку {e.response.status_code}. Попробуй позже."})
    except Exception as e:
        logging.error(f"ошибка: {str(e)}")
        return jsonify({"result": "ОШИБКА: " + str(e)})