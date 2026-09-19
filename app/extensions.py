"""The extension objects, on their own so models and the app factory can both
import them without importing each other."""

from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()

# Rejects any POST that does not carry a valid token. Every form in
# app/templates includes one; the counting screen sends it as an X-CSRFToken
# header from entry.js.
csrf = CSRFProtect()
