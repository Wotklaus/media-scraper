import os
from pathlib import Path

from pymongo import MongoClient


ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_mongodb_config():
    """Read MongoDB configuration from the local .env file."""
    if not ENV_FILE.is_file():
        raise RuntimeError("No se encontró backend/.env")

    config = {}

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        key, separator, value = line.partition("=")

        if separator:
            config[key.strip()] = value.strip().strip('"').strip("'")

    uri = config.get("MONGODB_URI") or os.getenv("MONGODB_URI")
    database_name = config.get("MONGODB_DB", "media_scraper")

    if not uri:
        raise RuntimeError("MONGODB_URI no está configurada")

    return uri, database_name


def get_database():
    """Connect to MongoDB Atlas and return the database."""
    uri, database_name = load_mongodb_config()

    client = MongoClient(
        uri,
        serverSelectionTimeoutMS=10000,
        connectTimeoutMS=10000,
        socketTimeoutMS=10000,
    )

    try:
        client.admin.command("ping")
        return client[database_name]
    except BaseException:
        client.close()
        raise
