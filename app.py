import os
import secrets
from dotenv import load_dotenv
load_dotenv()  # ← loads your .env file

from openai import OpenAI
from flask import Flask, render_template, request, redirect, session, jsonify
import sqlite3
import hashlib

# ---------------- OPENAI CLIENT ----------------
# ✅ Load API key from environment variable — never hardcode!
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# ---------------- FLASK APP ----------------
app = Flask(__name__)
# ✅ Use a strong random secret key (generate once and store in env)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

# ---------------- PRODUCTS ----------------
products = []
for i in range(1, 101):
    products.append({
        "id": i,
        "name": f"Product {i}",
        "price": 1000 + i * 50,
        "image": "https://via.placeholder.com/200?text=Product"
    })

# ---------------- USER TRACKING ----------------
user_history = {}

# ---------------- HELPERS ----------------
def hash_password(password: str) -> str:
    """✅ Hash passwords with SHA-256 before storing."""
    return hashlib.sha256(password.encode()).hexdigest()

# ---------------- AI FEATURES ----------------
def recommend(user):
    viewed = user_history.get(user, [])
    return [p for p in products if p["id"] not in viewed][:5]

def chatbot_fallback(msg):
    """Simple rule-based fallback when OpenAI is unavailable."""
    msg = msg.lower()
    if any(word in msg for word in ["hi", "hello", "hey"]):
        return "Hi 👋 Welcome to ShopEase! How can I help you?"
    if "phone" in msg:
        return "📱 We have great phones starting from ₹1100!"
    if "laptop" in msg:
        return "💻 Check out our laptops collection!"
    if "headphone" in msg:
        return "🎧 Amazing headphones at low prices!"
    if "cheap" in msg or "low price" in msg:
        return "💸 Check products under ₹1500!"
    if "expensive" in msg:
        return "💎 Premium products above ₹5000!"
    if "cart" in msg:
        return "🛒 You can add items to cart and checkout easily!"
    if "suggest" in msg or "recommend" in msg:
        return "⭐ I recommend trending products on homepage!"
    return "🤖 Try asking: 'cheap phone', 'laptop', 'recommend products'"

def analyze_sentiment_with_ai(review_text: str) -> str:
    """✅ Use OpenAI for real sentiment analysis instead of naive keyword match."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a sentiment analysis tool. "
                        "Respond ONLY with one word: Positive, Negative, or Neutral."
                    )
                },
                {"role": "user", "content": review_text}
            ],
            max_tokens=5
        )
        result = response.choices[0].message.content.strip()
        if result in ("Positive", "Negative", "Neutral"):
            return result
        return "Neutral"
    except Exception:
        # Fallback: simple heuristic
        positive_words = {"good", "great", "excellent", "love", "amazing", "best", "happy", "fantastic"}
        negative_words = {"bad", "terrible", "awful", "hate", "worst", "poor", "horrible", "disappointing"}
        words = set(review_text.lower().split())
        pos = len(words & positive_words)
        neg = len(words & negative_words)
        if pos > neg:
            return "Positive"
        if neg > pos:
            return "Negative"
        return "Neutral"

# ---------------- DATABASE ----------------
def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users "
        "(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT)"
    )
    conn.close()

init_db()

# ---------------- ROUTES ----------------

@app.route("/")
def home():
    user = session.get("user")
    recommended = recommend(user) if user else products[:5]
    return render_template("index.html", products=products, rec=recommended, session=session)

@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        if not username or not password:
            error = "Username and password are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            try:
                conn = get_db()
                # ✅ Store hashed password, never plaintext
                conn.execute(
                    "INSERT INTO users (username, password) VALUES (?, ?)",
                    (username, hash_password(password))
                )
                conn.commit()
                conn.close()
                return redirect("/login")
            except sqlite3.IntegrityError:
                error = "Username already taken."
    return render_template("register.html", error=error)

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        conn = get_db()
        # ✅ Compare against hashed password
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, hash_password(password))
        ).fetchone()
        conn.close()
        if user:
            session["user"] = username
            return redirect("/")
        error = "Invalid username or password."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/chat", methods=["POST"])
def chat():
    msg = request.json.get("msg", "").strip()
    if not msg:
        return jsonify({"reply": "Please type a message."})
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are an AI shopping assistant for ShopEase, an e-commerce website. Help users find products, answer questions about pricing, and make recommendations. Be friendly and concise."
                },
                {"role": "user", "content": msg}
            ],
            max_tokens=200
        )
        reply = response.choices[0].message.content
    except Exception:
        reply = chatbot_fallback(msg)
    return jsonify({"reply": reply})

@app.route("/review", methods=["POST"])
def review():
    review_text = request.form.get("review", "").strip()
    if not review_text:
        return jsonify({"sentiment": "Neutral", "message": "No review text provided."})
    sentiment = analyze_sentiment_with_ai(review_text)
    emoji = {"Positive": "😊", "Negative": "😞", "Neutral": "😐"}.get(sentiment, "😐")
    return jsonify({"sentiment": sentiment, "emoji": emoji})

@app.route("/add/<int:id>")
def add(id):
    # ✅ Validate product exists
    if not any(p["id"] == id for p in products):
        return redirect("/")
    cart = session.get("cart", [])
    cart.append(id)
    session["cart"] = cart
    if "user" in session:
        user_history.setdefault(session["user"], []).append(id)
    return redirect("/")

@app.route("/cart")
def view_cart():
    cart_ids = session.get("cart", [])
    cart_items = [p for p in products if p["id"] in cart_ids]
    total = sum(p["price"] for p in cart_items)
    return render_template("cart.html", cart_items=cart_items, total=total)

@app.route("/remove/<int:id>")
def remove(id):
    cart = session.get("cart", [])
    if id in cart:
        cart.remove(id)
    session["cart"] = cart
    return redirect("/cart")

@app.route("/place_order")
def place_order():
    user = session.get("user")
    if not user:
        return redirect("/login")
    cart_ids = session.get("cart", [])
    if not cart_ids:
        return redirect("/cart")
    order_items = [p for p in products if p["id"] in cart_ids]
    orders = [(p["name"], p["price"]) for p in order_items]
    session["cart"] = []
    existing = session.get("orders", [])
    existing.extend(orders)
    session["orders"] = existing
    return render_template("orders.html", orders=session["orders"])

# ---------------- RUN ----------------
if __name__ == "__main__":
    # ✅ Never run with debug=True in production
    app.run(debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
