import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from google import genai
from google.genai import errors, types

import chatbot_config as cfg

# Loads .env for local use. On platforms such as Render, the API_KEY
# environment variable is set in the dashboard and is read the same way.
load_dotenv()

API_KEY = os.getenv("API_KEY")
MODEL_NAME = "gemini-3.1-flash-lite"

MAX_MESSAGE_LENGTH = 4000
MAX_HISTORY_ITEMS = 20
NO_KEY_MESSAGE = (
    "Gemini API key is not configured. "
    "Please set the API_KEY environment variable."
)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

_client = None


def key_is_configured():
    return bool(API_KEY) and API_KEY.strip() not in ("", "YOUR_API_KEY")


def get_client():
    """Create the Gemini client only when a valid API key is available."""
    global _client
    if _client is None and key_is_configured():
        _client = genai.Client(api_key=API_KEY.strip())
    return _client


def error_response(message, status):
    return jsonify({"error": message}), status


def build_contents(history, message):
    contents = []
    if isinstance(history, list):
        for item in history[-MAX_HISTORY_ITEMS:]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            role = "user" if item.get("role") == "user" else "model"
            contents.append(
                types.Content(role=role, parts=[types.Part.from_text(text=text[:MAX_MESSAGE_LENGTH])])
            )
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))
    return contents


@app.route("/")
def index():
    return render_template(
        "index.html",
        name=cfg.CHATBOT_NAME,
        domain=cfg.DOMAIN,
        emoji=cfg.EMOJI,
        tagline=cfg.TAGLINE,
        welcome=cfg.WELCOME_MESSAGE,
        topics=cfg.TOPICS,
        suggestions=cfg.SUGGESTIONS,
        configured=key_is_configured(),
        no_key_message=NO_KEY_MESSAGE,
    )


@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return error_response("Invalid request. Please try again.", 400)

        message = str(data.get("message") or "").strip()
        if not message:
            return error_response("Please type a message before sending.", 400)
        if len(message) > MAX_MESSAGE_LENGTH:
            return error_response("Your message is too long. Please shorten it and try again.", 400)

        client = get_client()
        if client is None:
            return error_response(NO_KEY_MESSAGE, 503)

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=build_contents(data.get("history"), message),
            config=types.GenerateContentConfig(
                system_instruction=cfg.SYSTEM_PROMPT,
                temperature=0.5,
            ),
        )

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            return error_response("The AI returned an empty response. Please try again.", 502)

        return jsonify({"response": text})

    except errors.APIError as exc:
        code = getattr(exc, "code", None)
        app.logger.error("Gemini API error (code: %s)", code)
        if code in (400, 401, 403):
            return error_response(
                "The Gemini API rejected the request. Please check that your API key is valid.", 502
            )
        if code == 429:
            return error_response(
                "The Gemini API rate limit or quota was reached. Please wait a moment and try again.", 429
            )
        return error_response(
            "The Gemini service is temporarily unavailable. Please try again shortly.", 502
        )
    except Exception as exc:
        app.logger.error("Unexpected error: %s", type(exc).__name__)
        return error_response(
            "Something went wrong while contacting the AI service. Please try again.", 500
        )


@app.errorhandler(500)
def internal_error(_):
    return error_response("Something went wrong. Please try again.", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
