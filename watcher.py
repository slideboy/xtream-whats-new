#!/usr/bin/env python3
import json
import os
import re
import sqlite3
import smtplib
import ssl
import threading
import time
import traceback
import unicodedata
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage

HISTORY_RETENTION_DAYS = 45
DB_MAINTENANCE_INTERVAL_HOURS = 24
INACTIVE_ITEM_RETENTION_DAYS = 365
IDENTITY_HISTORY_RETENTION_DAYS = 730
VACUUM_MIN_FREE_BYTES = 32 * 1024 * 1024
VACUUM_MIN_FREE_RATIO = 0.25
VACUUM_MIN_INTERVAL_DAYS = 30
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import html

BASE = Path("/data")
ASSET_DIR = Path("/app/assets")
CONFIG_PATH = BASE / "config.json"
DB_PATH = BASE / "nouveautes.sqlite3"
BACKUP_DIR = BASE / "backups"
BACKUP_CHECK_SECONDS = 20
SCAN_CHECK_SECONDS = 5
EMAIL_CHECK_SECONDS = 15
EMAIL_RETRY_MINUTES = 10

APP_NAME = "Xtream What's New"
APP_VERSION = "1.0.8"
APP_USER_AGENT = f"Mozilla/5.0 Xtream-Whats-New/{APP_VERSION}"

def utc_now():
    return datetime.now(timezone.utc)

def iso_now():
    return utc_now().isoformat()

def parse_epoch(value):
    if value is None or value == "":
        return None
    try:
        n = float(value)
        if n > 10_000_000_000:
            n /= 1000.0
        return datetime.fromtimestamp(n, tz=timezone.utc)
    except Exception:
        return None

def safe_text(v):
    return "" if v is None else str(v)


def env_text(name, default=""):
    """Lit une variable d'environnement sans jamais l'afficher dans les logs."""
    return safe_text(os.environ.get(name, default))


SUPPORTED_UI_LANGUAGES = ("fr", "en")

COUNTRY_LABELS = {
    "fr": {
        "FR": "France", "BE": "Belgique", "CH": "Suisse", "DE": "Allemagne",
        "IT": "Italie", "ES": "Espagne", "PT": "Portugal", "GB": "Royaume-Uni",
        "IE": "Irlande", "NL": "Pays-Bas", "LU": "Luxembourg", "AT": "Autriche",
        "DK": "Danemark", "SE": "Suède", "NO": "Norvège", "FI": "Finlande",
        "PL": "Pologne", "CZ": "Tchéquie", "SK": "Slovaquie", "HU": "Hongrie",
        "RO": "Roumanie", "BG": "Bulgarie", "GR": "Grèce", "HR": "Croatie",
        "RS": "Serbie", "BA": "Bosnie-Herzégovine", "AL": "Albanie", "TR": "Turquie",
        "US": "États-Unis", "CA": "Canada", "MX": "Mexique", "BR": "Brésil",
        "AR": "Arabe", "ARG": "Argentine", "MA": "Maroc", "DZ": "Algérie", "TN": "Tunisie",
        "EG": "Égypte", "SA": "Arabie saoudite", "AE": "Émirats arabes unis",
        "IN": "Inde", "JP": "Japon", "KR": "Corée du Sud", "CN": "Chine",
        "OTHER": "Autres / non détecté",
    },
    "en": {
        "FR": "France", "BE": "Belgium", "CH": "Switzerland", "DE": "Germany",
        "IT": "Italy", "ES": "Spain", "PT": "Portugal", "GB": "United Kingdom",
        "IE": "Ireland", "NL": "Netherlands", "LU": "Luxembourg", "AT": "Austria",
        "DK": "Denmark", "SE": "Sweden", "NO": "Norway", "FI": "Finland",
        "PL": "Poland", "CZ": "Czechia", "SK": "Slovakia", "HU": "Hungary",
        "RO": "Romania", "BG": "Bulgaria", "GR": "Greece", "HR": "Croatia",
        "RS": "Serbia", "BA": "Bosnia and Herzegovina", "AL": "Albania", "TR": "Turkey",
        "US": "United States", "CA": "Canada", "MX": "Mexico", "BR": "Brazil",
        "AR": "Arabic", "ARG": "Argentina", "MA": "Morocco", "DZ": "Algeria", "TN": "Tunisia",
        "EG": "Egypt", "SA": "Saudi Arabia", "AE": "United Arab Emirates",
        "IN": "India", "JP": "Japan", "KR": "South Korea", "CN": "China",
        "OTHER": "Other / undetected",
    },
}


def normalize_ui_language(value):
    value = safe_text(value).strip().lower()
    return value if value in SUPPORTED_UI_LANGUAGES else "fr"


def ui_text(lang, fr, en):
    return en if normalize_ui_language(lang) == "en" else fr

COUNTRY_ALIASES = {
    "FRA": "FR", "FRANCE": "FR", "FRENCH": "FR",
    "BEL": "BE", "BELGIUM": "BE", "BELGIQUE": "BE",
    "DEU": "DE", "GER": "DE", "GERMANY": "DE", "ALLEMAGNE": "DE",
    "ITA": "IT", "ITALY": "IT", "ITALIE": "IT",
    "ESP": "ES", "SPAIN": "ES", "ESPAGNE": "ES",
    "PRT": "PT", "PORTUGAL": "PT",
    "UK": "GB", "GBR": "GB", "EN": "GB", "ENGLISH": "GB",
    "TUR": "TR", "TURKEY": "TR", "TURQUIE": "TR",
    "USA": "US", "UNITEDSTATES": "US",
    "CAN": "CA", "CANADA": "CA",
    "ARABIC": "AR", "ARABE": "AR", "ARAB": "AR",
    "ARG": "ARG", "ARGENTINA": "ARG", "ARGENTINE": "ARG",
    "MAR": "MA", "MOROCCO": "MA", "MAROC": "MA",
    "DZA": "DZ", "ALGERIA": "DZ", "ALGERIE": "DZ",
    "TUN": "TN", "TUNISIA": "TN", "TUNISIE": "TN",
}

FLAG_TO_COUNTRY = {
    "🇫🇷": "FR", "🇧🇪": "BE", "🇨🇭": "CH", "🇩🇪": "DE", "🇮🇹": "IT",
    "🇪🇸": "ES", "🇵🇹": "PT", "🇬🇧": "GB", "🇮🇪": "IE", "🇳🇱": "NL",
    "🇹🇷": "TR", "🇺🇸": "US", "🇨🇦": "CA", "🇲🇦": "MA", "🇩🇿": "DZ",
    "🇹🇳": "TN", "🇧🇷": "BR", "🇦🇷": "ARG", "🇮🇳": "IN", "🇯🇵": "JP",
}


def normalize_category_name(value):
    value = safe_text(value).strip().upper()
    value = " ".join(value.split())
    value = re.sub(r"^\[([A-Z]{2,3})\]", r"|\1|", value)
    value = re.sub(r"^\(([A-Z]{2,3})\)", r"|\1|", value)
    return value


def normalize_country_code(token):
    token = re.sub(r"[^A-Z]", "", safe_text(token).upper())
    if not token:
        return "OTHER"
    token = COUNTRY_ALIASES.get(token, token)
    if len(token) == 2:
        return token
    return COUNTRY_ALIASES.get(token, "OTHER")


def detect_country(name):
    text = safe_text(name).strip()
    upper = text.upper()
    for flag, code in FLAG_TO_COUNTRY.items():
        if text.startswith(flag):
            return code
    m = re.match(r"^[\s]*[|\[({<]\s*([A-Z]{2,3})\s*[|\])}>]", upper)
    if m:
        return normalize_country_code(m.group(1))
    m = re.match(r"^[\s]*([A-Z]{2,3})(?:\s*[-:|/•·]|\s+)", upper)
    if m:
        return normalize_country_code(m.group(1))
    words = re.sub(r"[^A-ZÀ-ÖØ-Þ]+", "", upper)
    for alias, code in COUNTRY_ALIASES.items():
        if len(alias) > 3 and words.startswith(alias):
            return code
    return "OTHER"


def country_label(code, lang="fr"):
    code = safe_text(code).upper() or "OTHER"
    labels = COUNTRY_LABELS.get(normalize_ui_language(lang), COUNTRY_LABELS["fr"])
    return labels.get(code, code)

def load_config():
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Configuration absente: {CONFIG_PATH}")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    # Les identifiants du fournisseur sont des secrets et proviennent
    # exclusivement du fichier .env injecté dans le conteneur.
    secret_env = {
        "provider_url": "XTREAM_PROVIDER_URL",
        "username": "XTREAM_USERNAME",
        "password": "XTREAM_PASSWORD",
    }
    missing = []
    for key, env_name in secret_env.items():
        env_value = env_text(env_name)
        if not env_value.strip():
            missing.append(env_name)
            continue
        cfg[key] = env_value.strip() if key != "password" else env_value

    if missing:
        raise SystemExit(
            "Variable(s) obligatoire(s) manquante(s) dans .env: " + ", ".join(missing)
        )

    cfg.setdefault("interval_minutes", 15)
    # La rétention de l'historique est fixée par HISTORY_RETENTION_DAYS.
    cfg.setdefault("deletion_confirmation_scans", 2)
    cfg.setdefault("max_series_detail_fetches_per_run", 25)
    cfg.setdefault("series_fetch_delay_seconds", 0.7)
    cfg.setdefault("request_timeout_seconds", 25)
    cfg.setdefault("port", 36401)
    cfg.setdefault("timezone", "Europe/Paris")
    cfg.setdefault("user_agent", APP_USER_AGENT)

    cfg["provider_url"] = cfg["provider_url"].rstrip("/")
    return cfg

CFG = load_config()
TZ = ZoneInfo(CFG["timezone"])
LOCK = threading.RLock()
BACKUP_LOCK = threading.Lock()
SCAN_RUN_LOCK = threading.Lock()
SCAN_WAKE = threading.Event()
EMAIL_WAKE = threading.Event()
EMAIL_SEND_LOCK = threading.Lock()
SCAN_STATE_LOCK = threading.RLock()
SCAN_STATE = {"running": False, "trigger": "", "started_at": ""}

# Erreurs du scan courant : mémoire uniquement, jamais enregistrées en base.
ERROR_LOCK = threading.RLock()
CURRENT_WATCHER_ERRORS = []
MAX_WATCHER_ERRORS = 10

def sanitize_watcher_error(message):
    """Retire les informations sensibles avant affichage."""
    msg = safe_text(message)
    sensitive_values = (
        safe_text(CFG.get("password")),
        safe_text(CFG.get("username")),
        safe_text(CFG.get("provider_url")),
    )
    for value in sensitive_values:
        if value:
            msg = msg.replace(value, "***")
    return msg

def add_scan_error(target, message):
    item = {
        "at": iso_now(),
        "message": sanitize_watcher_error(message),
    }
    target.append(item)
    if len(target) > MAX_WATCHER_ERRORS:
        del target[:-MAX_WATCHER_ERRORS]

def publish_watcher_errors(items):
    global CURRENT_WATCHER_ERRORS
    with ERROR_LOCK:
        CURRENT_WATCHER_ERRORS = [dict(x) for x in items[-MAX_WATCHER_ERRORS:]]

def get_watcher_errors():
    with ERROR_LOCK:
        return [dict(x) for x in CURRENT_WATCHER_ERRORS]

def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def ensure_column(conn, table, column, definition):
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# Movie Identity V1
# -----------------
# Le stream_id Xtream reste l'identifiant fournisseur. Ces helpers ajoutent une
# identité secondaire, volontairement conservatrice, pour éviter qu'un simple
# changement de stream_id ne soit annoncé comme un nouveau film.
def _movie_dict_sources(item):
    sources = [item] if isinstance(item, dict) else []
    if isinstance(item, dict) and isinstance(item.get("info"), dict):
        sources.append(item["info"])
    return sources


def _first_movie_value(item, keys):
    for source in _movie_dict_sources(item):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return None


def normalize_tmdb_id(value):
    text = safe_text(value).strip()
    if not text:
        return ""
    if re.fullmatch(r"\d+", text):
        # "0" est fréquemment utilisé comme valeur "inconnue" par les panels.
        value_int = int(text)
        return str(value_int) if value_int > 0 else ""
    m = re.search(r"(?:movie/|tv/|tmdb[:=/\s-]*)(\d{1,12})", text, re.IGNORECASE)
    return str(int(m.group(1))) if m else ""


def normalize_imdb_id(value):
    text = safe_text(value).strip()
    if not text:
        return ""
    m = re.search(r"\btt\d{5,12}\b", text, re.IGNORECASE)
    return m.group(0).lower() if m else ""


def movie_year_from_item(item, name=""):
    # On privilégie les champs structurés du fournisseur.
    raw = _first_movie_value(
        item,
        ("year", "release_year", "releaseDate", "release_date", "releasedate", "released"),
    )
    if raw not in (None, ""):
        m = re.search(r"\b(19\d{2}|20\d{2})\b", safe_text(raw))
        if m:
            return int(m.group(1))

    # Repli prudent : uniquement une année explicitement délimitée dans le nom.
    # Un film réellement intitulé "1917" n'est donc jamais interprété comme
    # "titre vide + année 1917".
    title = safe_text(name).strip()
    patterns = (
        r"[\(\[\{]\s*(19\d{2}|20\d{2})\s*[\)\]\}]\s*$",
        r"\s[-–—]\s*(19\d{2}|20\d{2})\s*$",
    )
    for pattern in patterns:
        m = re.search(pattern, title)
        if m:
            return int(m.group(1))
    return None


def normalize_movie_title(name, year=None):
    text = unicodedata.normalize("NFKC", safe_text(name)).casefold().strip()
    if year:
        y = re.escape(str(year))
        text = re.sub(rf"[\(\[\{{]\s*{y}\s*[\)\]\}}]", " ", text)
        text = re.sub(rf"\s[-–—]\s*{y}\s*$", " ", text)
    # Normalisation légère : ponctuation/espaces seulement. V1 ne fait pas de
    # fuzzy matching et ne supprime pas les tags 4K/FHD afin de rester prudente.
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def movie_identity_from_item(item, name=""):
    year = movie_year_from_item(item, name)
    tmdb_id = normalize_tmdb_id(
        _first_movie_value(item, ("tmdb_id", "tmdb", "tmdbid"))
    )
    imdb_id = normalize_imdb_id(
        _first_movie_value(item, ("imdb_id", "imdb", "imdbid"))
    )
    return {
        "tmdb_id": tmdb_id or None,
        "imdb_id": imdb_id or None,
        "year": year,
        "normalized_name": normalize_movie_title(name, year),
    }



def _movie_category_compatible(old_category, new_category, monitored_category_norms):
    old_norm = normalize_category_name(old_category)
    new_norm = normalize_category_name(new_category)
    if old_norm == new_norm:
        return True

    # Si les deux catégories sont surveillées, un déplacement interne au
    # périmètre ne doit pas transformer le film en nouveauté. En revanche, un
    # passage depuis une ancienne catégorie non surveillée conserve la logique
    # existante "entre dans le périmètre = nouveauté".
    monitored = set(monitored_category_norms or ())
    return bool(old_norm and new_norm and old_norm in monitored and new_norm in monitored)


def find_movie_reassociation_candidate(
    conn,
    new_id,
    identity,
    new_category,
    provider_movie_ids,
    monitored_category_norms,
):
    """Retourne (ancienne_ligne, méthode) uniquement pour une correspondance unique."""
    provider_movie_ids = {safe_text(x) for x in provider_movie_ids}

    def eligible(rows, require_same_category=False):
        out = []
        new_category_norm = normalize_category_name(new_category)
        for row in rows:
            old_id = safe_text(row["id"])
            if old_id in provider_movie_ids:
                # Les deux IDs coexistent chez le fournisseur : surtout ne pas fusionner.
                continue
            if require_same_category:
                if normalize_category_name(row["category"]) != new_category_norm:
                    continue
            elif not _movie_category_compatible(
                row["category"], new_category, monitored_category_norms
            ):
                continue
            out.append(row)
        return out

    def unique(rows, matched_by, require_same_category=False):
        rows = eligible(rows, require_same_category=require_same_category)
        if len(rows) == 1:
            return rows[0], matched_by
        # Ambiguïté = aucune fusion automatique.
        return None, None

    tmdb = safe_text(identity.get("tmdb_id")).strip()
    if tmdb:
        rows = conn.execute("""
            SELECT * FROM movies
            WHERE active=1 AND id<>? AND tmdb_id=?
        """, (safe_text(new_id), tmdb)).fetchall()
        if rows:
            row, method = unique(rows, "tmdb")
            if row is not None or len(eligible(rows)) > 1:
                return row, method

    imdb = safe_text(identity.get("imdb_id")).strip()
    if imdb:
        rows = conn.execute("""
            SELECT * FROM movies
            WHERE active=1 AND id<>? AND imdb_id=?
        """, (safe_text(new_id), imdb)).fetchall()
        if rows:
            row, method = unique(rows, "imdb")
            if row is not None or len(eligible(rows)) > 1:
                return row, method

    normalized = safe_text(identity.get("normalized_name")).strip()
    year = identity.get("year")
    if normalized and year:
        rows = conn.execute("""
            SELECT * FROM movies
            WHERE active=1 AND id<>? AND normalized_name=? AND year=?
        """, (safe_text(new_id), normalized, int(year))).fetchall()
        # Le repli titre+année est volontairement plus strict qu'un identifiant
        # externe exact : même catégorie obligatoire en V1.
        return unique(rows, "title_year", require_same_category=True)

    return None, None


def reassociate_movie_id(
    conn,
    old_row,
    new_id,
    name,
    category,
    provider_added,
    identity,
    now,
    matched_by,
):
    """Transfère la ligne vers le nouvel ID sans créer d'événement utilisateur."""
    old_id = safe_text(old_row["id"])
    new_id = safe_text(new_id)
    conn.execute("""
        UPDATE movies SET
            id=?,
            name=?,
            category=?,
            provider_added=COALESCE(?,provider_added),
            normalized_name=?,
            year=COALESCE(?,year),
            tmdb_id=COALESCE(?,tmdb_id),
            imdb_id=COALESCE(?,imdb_id),
            last_seen=?,
            active=1,
            missing_count=0
        WHERE id=?
    """, (
        new_id,
        safe_text(name),
        safe_text(category),
        provider_added,
        safe_text(identity.get("normalized_name")) or None,
        identity.get("year"),
        safe_text(identity.get("tmdb_id")) or None,
        safe_text(identity.get("imdb_id")) or None,
        now,
        old_id,
    ))
    conn.execute("""
        INSERT INTO movie_id_changes(
            old_id,new_id,matched_by,detected_at,name,category
        ) VALUES(?,?,?,?,?,?)
    """, (
        old_id,
        new_id,
        safe_text(matched_by),
        now,
        safe_text(name),
        safe_text(category),
    ))
    print(
        f"[INFO] Movie Identity V1: film réassocié {old_id} -> {new_id} "
        f"({matched_by}, {safe_text(name)})",
        flush=True,
    )


# Series Identity V1
# ------------------
# Le series_id Xtream reste l'identifiant fournisseur. L'identité secondaire est
# volontairement très stricte car un même TMDB peut coexister en FR/VOST/UHD/etc.
def series_identity_from_item(item, name=""):
    year = movie_year_from_item(item, name)
    tmdb_id = normalize_tmdb_id(
        _first_movie_value(item, ("tmdb_id", "tmdb", "tmdbid"))
    )
    return {
        "tmdb_id": tmdb_id or None,
        "year": year,
        "normalized_name": normalize_movie_title(name, year),
    }


def find_series_reassociation_candidate(
    conn,
    new_id,
    identity,
    new_category,
    provider_series_ids,
):
    """Correspondance unique seulement; aucune fusion de variantes coexistantes."""
    provider_series_ids = {safe_text(x) for x in provider_series_ids}
    new_norm = safe_text(identity.get("normalized_name")).strip()
    new_category_norm = normalize_category_name(new_category)

    def eligible(rows):
        out = []
        for row in rows:
            old_id = safe_text(row["id"])
            if old_id in provider_series_ids:
                # Ancien et nouvel ID coexistent : ce sont deux entrées distinctes.
                continue
            if normalize_category_name(row["category"]) != new_category_norm:
                continue
            old_norm = safe_text(row["normalized_name"]).strip()
            if not old_norm:
                old_year = row["year"] if "year" in row.keys() else None
                old_norm = normalize_movie_title(row["name"], old_year)
            if not new_norm or old_norm != new_norm:
                continue
            out.append(row)
        return out

    tmdb = safe_text(identity.get("tmdb_id")).strip()
    if tmdb:
        rows = conn.execute("""
            SELECT * FROM series
            WHERE active=1 AND id<>? AND tmdb_id=?
        """, (safe_text(new_id), tmdb)).fetchall()
        candidates = eligible(rows)
        if len(candidates) == 1:
            return candidates[0], "tmdb_title"
        if len(candidates) > 1:
            return None, None

    year = identity.get("year")
    if new_norm and year:
        rows = conn.execute("""
            SELECT * FROM series
            WHERE active=1 AND id<>? AND normalized_name=? AND year=?
        """, (safe_text(new_id), new_norm, int(year))).fetchall()
        candidates = eligible(rows)
        if len(candidates) == 1:
            return candidates[0], "title_year"

    return None, None


def reassociate_series_id(
    conn,
    old_row,
    new_id,
    name,
    category,
    last_modified,
    identity,
    now,
    matched_by,
):
    """Transfère série + cache épisodes vers le nouvel ID sans événement utilisateur."""
    old_id = safe_text(old_row["id"])
    new_id = safe_text(new_id)

    # Garde supplémentaire contre un éventuel cache orphelin sous le nouvel ID.
    if conn.execute(
        "SELECT 1 FROM episodes WHERE series_id=? LIMIT 1", (new_id,)
    ).fetchone():
        return False

    conn.execute("UPDATE episodes SET series_id=? WHERE series_id=?", (new_id, old_id))
    conn.execute("""
        UPDATE series SET
            id=?,name=?,category=?,
            seen_last_modified=COALESCE(NULLIF(?,''),seen_last_modified),
            normalized_name=?,year=COALESCE(?,year),tmdb_id=COALESCE(?,tmdb_id),
            last_seen=?,active=1,missing_count=0
        WHERE id=?
    """, (
        new_id,
        safe_text(name),
        safe_text(category),
        safe_text(last_modified),
        safe_text(identity.get("normalized_name")) or None,
        identity.get("year"),
        safe_text(identity.get("tmdb_id")) or None,
        now,
        old_id,
    ))
    conn.execute("""
        INSERT INTO series_id_changes(
            old_id,new_id,matched_by,detected_at,name,category
        ) VALUES(?,?,?,?,?,?)
    """, (
        old_id,new_id,safe_text(matched_by),now,safe_text(name),safe_text(category)
    ))
    print(
        f"[INFO] Series Identity V1: série réassociée {old_id} -> {new_id} "
        f"({matched_by}, {safe_text(name)})",
        flush=True,
    )
    return True


def episode_identity_key(row):
    """Identité fonctionnelle V1 : saison + numéro, si le numéro est exploitable."""
    try:
        season = int(row["season"] if isinstance(row, sqlite3.Row) else row.get("season"))
        epnum = int(row["episode_num"] if isinstance(row, sqlite3.Row) else row.get("episode_num"))
    except Exception:
        return None
    if season < 0 or epnum <= 0:
        return None
    return season, epnum


def reassociate_episode_ids(conn, series_id, current_eps, now):
    """Réassocie les episode_id changés quand SxxExx reste unique des deux côtés."""
    old_rows = conn.execute(
        "SELECT * FROM episodes WHERE series_id=?", (safe_text(series_id),)
    ).fetchall()
    if not old_rows:
        return 0

    old_ids = {safe_text(r["episode_id"]) for r in old_rows}
    current_ids = {safe_text(e.get("episode_id")) for e in current_eps}

    old_by_key = {}
    old_dupes = set()
    for row in old_rows:
        key = episode_identity_key(row)
        if key is None:
            continue
        if key in old_by_key:
            old_dupes.add(key)
        else:
            old_by_key[key] = row

    current_by_key = {}
    current_dupes = set()
    for e in current_eps:
        key = episode_identity_key(e)
        if key is None:
            continue
        if key in current_by_key:
            current_dupes.add(key)
        else:
            current_by_key[key] = e

    changed = 0
    for key, e in current_by_key.items():
        if key in current_dupes or key in old_dupes:
            continue
        new_eid = safe_text(e.get("episode_id"))
        if not new_eid or new_eid in old_ids:
            continue
        old = old_by_key.get(key)
        if old is None:
            continue
        old_eid = safe_text(old["episode_id"])
        if old_eid in current_ids:
            # Les deux IDs coexistent : surtout ne pas fusionner.
            continue

        conn.execute("""
            UPDATE episodes SET
                episode_id=?,title=?,provider_added=COALESCE(?,provider_added)
            WHERE series_id=? AND episode_id=?
        """, (
            new_eid,
            safe_text(e.get("title")),
            e.get("provider_added"),
            safe_text(series_id),
            old_eid,
        ))
        conn.execute("""
            INSERT INTO episode_id_changes(
                series_id,old_id,new_id,season,episode_num,detected_at,title
            ) VALUES(?,?,?,?,?,?,?)
        """, (
            safe_text(series_id),old_eid,new_eid,key[0],key[1],now,safe_text(e.get("title"))
        ))
        print(
            f"[INFO] Episode Identity V1: {series_id} S{key[0]:02d}E{key[1]:02d} "
            f"réassocié {old_eid} -> {new_eid}",
            flush=True,
        )
        changed += 1

    return changed


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS movies (
            id TEXT PRIMARY KEY,
            name TEXT,
            category TEXT,
            provider_added TEXT,
            first_seen TEXT,
            last_seen TEXT
        );

        CREATE TABLE IF NOT EXISTS series (
            id TEXT PRIMARY KEY,
            name TEXT,
            category TEXT,
            seen_last_modified TEXT,
            fetched_last_modified TEXT,
            first_seen TEXT,
            last_seen TEXT,
            pending INTEGER NOT NULL DEFAULT 0,
            pending_since TEXT,
            is_new INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS episodes (
            series_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            season INTEGER,
            episode_num INTEGER,
            title TEXT,
            provider_added TEXT,
            PRIMARY KEY(series_id, episode_id)
        );

        CREATE TABLE IF NOT EXISTS categories (
            kind TEXT NOT NULL,
            category_id TEXT NOT NULL,
            name TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            PRIMARY KEY(kind, category_id)
        );

        CREATE TABLE IF NOT EXISTS available_categories (
            kind TEXT NOT NULL,
            category_id TEXT NOT NULL,
            name TEXT NOT NULL,
            country_code TEXT NOT NULL DEFAULT 'OTHER',
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(kind, category_id)
        );

        CREATE TABLE IF NOT EXISTS country_preferences (
            country_code TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS category_preferences (
            kind TEXT NOT NULL,
            category_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(kind, category_id)
        );

        CREATE TABLE IF NOT EXISTS events (
            event_key TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            item_id TEXT,
            title TEXT NOT NULL,
            subtitle TEXT,
            category TEXT,
            detected_at TEXT NOT NULL,
            provider_added TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_events_detected ON events(detected_at DESC);

        CREATE TABLE IF NOT EXISTS movie_id_changes (
            change_id INTEGER PRIMARY KEY AUTOINCREMENT,
            old_id TEXT NOT NULL,
            new_id TEXT NOT NULL,
            matched_by TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            name TEXT,
            category TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_movie_id_changes_time
            ON movie_id_changes(detected_at DESC);

        CREATE TABLE IF NOT EXISTS series_id_changes (
            change_id INTEGER PRIMARY KEY AUTOINCREMENT,
            old_id TEXT NOT NULL,
            new_id TEXT NOT NULL,
            matched_by TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            name TEXT,
            category TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_series_id_changes_time
            ON series_id_changes(detected_at DESC);

        CREATE TABLE IF NOT EXISTS episode_id_changes (
            change_id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id TEXT NOT NULL,
            old_id TEXT NOT NULL,
            new_id TEXT NOT NULL,
            season INTEGER,
            episode_num INTEGER,
            detected_at TEXT NOT NULL,
            title TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_episode_id_changes_time
            ON episode_id_changes(detected_at DESC);

        CREATE TABLE IF NOT EXISTS email_digest_queue (
            event_key TEXT PRIMARY KEY,
            queued_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_email_digest_queue_time ON email_digest_queue(queued_at ASC);

        CREATE INDEX IF NOT EXISTS idx_series_pending ON series(pending, pending_since);
        CREATE INDEX IF NOT EXISTS idx_categories_kind ON categories(kind);
        """)

        # Migrations non destructives pour une base v2/v3 existante.
        ensure_column(c, "movies", "active", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(c, "movies", "missing_count", "INTEGER NOT NULL DEFAULT 0")
        # Movie Identity V1 : identité secondaire, additive et non destructive.
        ensure_column(c, "movies", "normalized_name", "TEXT")
        ensure_column(c, "movies", "year", "INTEGER")
        ensure_column(c, "movies", "tmdb_id", "TEXT")
        ensure_column(c, "movies", "imdb_id", "TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_movies_tmdb_id ON movies(tmdb_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_movies_imdb_id ON movies(imdb_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_movies_title_year ON movies(normalized_name,year)")

        # Backfill léger des anciennes lignes : aucune requête réseau. Il permet
        # au premier scan après mise à niveau de reconnaître déjà un changement
        # d'ID via "titre normalisé + année" lorsque l'année est dans le nom.
        movie_rows_to_backfill = c.execute("""
            SELECT id,name,normalized_name,year
            FROM movies
            WHERE normalized_name IS NULL OR normalized_name=''
        """).fetchall()
        for movie_row in movie_rows_to_backfill:
            inferred_year = movie_year_from_item({}, movie_row["name"])
            c.execute("""
                UPDATE movies SET normalized_name=?, year=COALESCE(year,?)
                WHERE id=?
            """, (
                normalize_movie_title(movie_row["name"], inferred_year),
                inferred_year,
                movie_row["id"],
            ))

        ensure_column(c, "series", "active", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(c, "series", "missing_count", "INTEGER NOT NULL DEFAULT 0")
        # Series Identity V1 : TMDB + titre normalisé + année, sans appel réseau.
        ensure_column(c, "series", "normalized_name", "TEXT")
        ensure_column(c, "series", "year", "INTEGER")
        ensure_column(c, "series", "tmdb_id", "TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_series_tmdb_id ON series(tmdb_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_series_title_year ON series(normalized_name,year)")

        series_rows_to_backfill = c.execute("""
            SELECT id,name,normalized_name,year
            FROM series
            WHERE normalized_name IS NULL OR normalized_name=''
        """).fetchall()
        for series_row in series_rows_to_backfill:
            inferred_year = movie_year_from_item({}, series_row["name"])
            c.execute("""
                UPDATE series SET normalized_name=?, year=COALESCE(year,?)
                WHERE id=?
            """, (
                normalize_movie_title(series_row["name"], inferred_year),
                inferred_year,
                series_row["id"],
            ))

        ensure_column(c, "categories", "active", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(c, "categories", "missing_count", "INTEGER NOT NULL DEFAULT 0")
        # Une catégorie nouvellement activée doit d'abord être absorbée comme
        # état de référence, sans transformer tout son catalogue en nouveautés.
        ensure_column(c, "category_preferences", "baseline_pending", "INTEGER NOT NULL DEFAULT 0")

        # Réglages de sauvegarde intégrés à l'application. Désactivés par
        # défaut afin de ne pas doubler un éventuel cron déjà présent sur la VM.
        # Langue de l'interface et des emails. Le français reste la valeur par
        # défaut pour préserver le comportement des installations existantes.
        c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('ui_language','fr')")

        backup_defaults = {
            "backup_enabled": "0",
            "backup_frequency": "daily",
            "backup_time": "03:15",
            "backup_keep": "14",
            # Date de la dernière modification du planning. Elle permet de
            # reprogrammer une sauvegarde le jour même après un changement
            # d'heure/fréquence, même si une auto a déjà eu lieu plus tôt.
            "backup_schedule_changed_at": "",
        }
        for key, value in backup_defaults.items():
            c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES(?,?)", (key, value))

        # Périodicité de scan gérée dans l'application. La valeur du
        # config.json sert uniquement de valeur initiale lors de la migration.
        try:
            initial_scan_interval = int(round(float(CFG.get("interval_minutes", 15))))
        except Exception:
            initial_scan_interval = 15
        initial_scan_interval = max(5, min(1440, initial_scan_interval))
        scan_defaults = {
            "scan_interval_minutes": str(initial_scan_interval),
            "scan_schedule_changed_at": "",
            "scan_last_attempt": "",
            "scan_last_trigger": "",
        }
        for key, value in scan_defaults.items():
            c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES(?,?)", (key, value))

        # Réglages email fonctionnels dans SQLite. Les identifiants SMTP
        # restent exclusivement dans .env et ne sont jamais stockés en base.
        email_defaults = {
            "email_enabled": "0",
            "email_smtp_host": "",
            "email_smtp_port": "587",
            "email_security": "starttls",
            "email_from": "",
            "email_to": "",
            "email_notify_movies": "1",
            "email_notify_series": "1",
            "email_notify_episodes": "1",
            "email_notify_categories": "0",
            "email_notify_removals": "1",
            "email_notify_scan_errors": "1",
            "email_notify_backup_errors": "1",
            "email_max_items": "25",
            # 0 = immédiat ; sinon récapitulatif toutes les N heures.
            # Pour une installation existante, 2 h devient le choix par défaut.
            "email_digest_hours": "2",
            "email_digest_last_sent": "",
            "email_digest_last_attempt": "",
            "scan_consecutive_failures": "0",
            "email_last_scan_error_alert": "",
            "email_last_success": "",
            "email_last_error": "",
        }
        for key, value in email_defaults.items():
            c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES(?,?)", (key, value))

        # Nettoyage définitif des anciennes clés de migration SMTP. Une base
        # existante peut encore les contenir ; elles sont supprimées au démarrage.
        c.execute("DELETE FROM meta WHERE key IN ('email_username','email_password')")

        c.commit()

def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def set_meta(conn, key, value):
    conn.execute("""
        INSERT INTO meta(key,value) VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, safe_text(value)))


def get_ui_language(conn=None):
    if conn is not None:
        return normalize_ui_language(get_meta(conn, "ui_language", "fr"))
    try:
        with db() as c:
            return normalize_ui_language(get_meta(c, "ui_language", "fr"))
    except Exception:
        return "fr"


def save_ui_language(conn, form):
    current = get_ui_language(conn)
    requested = normalize_ui_language(form.get("ui_language", [current])[0])
    set_meta(conn, "ui_language", requested)
    return requested, requested != current


def get_backup_settings(conn):
    def meta_value(key, default):
        value = get_meta(conn, key, default)
        return safe_text(value).strip() or default

    enabled = meta_value("backup_enabled", "0") == "1"
    frequency = meta_value("backup_frequency", "daily")
    if frequency not in ("daily", "2days", "weekly"):
        frequency = "daily"

    backup_time = meta_value("backup_time", "03:15")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", backup_time):
        backup_time = "03:15"

    try:
        keep = int(meta_value("backup_keep", "14"))
    except Exception:
        keep = 14
    keep = max(1, min(365, keep))

    return {
        "enabled": enabled,
        "frequency": frequency,
        "time": backup_time,
        "keep": keep,
        "last_auto": get_meta(conn, "backup_last_auto", ""),
        "schedule_changed_at": get_meta(conn, "backup_schedule_changed_at", ""),
        "last_success": get_meta(conn, "backup_last_success", ""),
        "last_error": get_meta(conn, "backup_last_error", ""),
    }


def save_backup_settings(conn, form):
    # Lire l'ancien planning avant de l'écraser permet de savoir si
    # l'utilisateur vient réellement de le modifier.
    old_settings = get_backup_settings(conn)

    enabled = "1" if "backup_enabled" in form else "0"
    frequency = safe_text(form.get("backup_frequency", ["daily"])[0]).strip()
    if frequency not in ("daily", "2days", "weekly"):
        frequency = "daily"

    backup_time = safe_text(form.get("backup_time", ["03:15"])[0]).strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", backup_time):
        backup_time = "03:15"

    try:
        keep = int(form.get("backup_keep", ["14"])[0])
    except Exception:
        keep = 14
    keep = max(1, min(365, keep))

    schedule_changed = (
        old_settings.get("enabled") != (enabled == "1")
        or old_settings.get("frequency") != frequency
        or old_settings.get("time") != backup_time
    )

    set_meta(conn, "backup_enabled", enabled)
    set_meta(conn, "backup_frequency", frequency)
    set_meta(conn, "backup_time", backup_time)
    set_meta(conn, "backup_keep", str(keep))
    if schedule_changed:
        set_meta(conn, "backup_schedule_changed_at", iso_now())


def _email_bool(value):
    return safe_text(value).strip() == "1"


def get_email_settings(conn, include_password=False):
    def value(key, default=""):
        return safe_text(get_meta(conn, key, default))

    try:
        port = int(value("email_smtp_port", "587") or "587")
    except Exception:
        port = 587
    port = max(1, min(65535, port))

    security = value("email_security", "starttls").lower().strip()
    if security not in ("starttls", "ssl", "none"):
        security = "starttls"

    try:
        max_items = int(value("email_max_items", "25") or "25")
    except Exception:
        max_items = 25
    max_items = max(5, min(100, max_items))

    try:
        digest_hours = int(value("email_digest_hours", "2") or "2")
    except Exception:
        digest_hours = 2
    if digest_hours not in (0, 1, 2, 3, 6):
        digest_hours = 2

    username = env_text("SMTP_USERNAME").strip()
    password = env_text("SMTP_PASSWORD")

    out = {
        "enabled": _email_bool(value("email_enabled", "0")),
        "smtp_host": value("email_smtp_host", "").strip(),
        "smtp_port": port,
        "security": security,
        "username": username,
        "from_addr": value("email_from", "").strip(),
        "to_addr": value("email_to", "").strip(),
        "notify_movies": _email_bool(value("email_notify_movies", "1")),
        "notify_series": _email_bool(value("email_notify_series", "1")),
        "notify_episodes": _email_bool(value("email_notify_episodes", "1")),
        "notify_categories": _email_bool(value("email_notify_categories", "0")),
        "notify_removals": _email_bool(value("email_notify_removals", "1")),
        "notify_scan_errors": _email_bool(value("email_notify_scan_errors", "1")),
        "notify_backup_errors": _email_bool(value("email_notify_backup_errors", "1")),
        "digest_hours": digest_hours,
        "max_items": max_items,
        "smtp_username_configured": bool(username),
        "smtp_password_configured": bool(password.strip()),
        "language": get_ui_language(conn),
        "last_success": value("email_last_success", ""),
        "last_error": value("email_last_error", ""),
    }
    if include_password:
        out["password"] = password
    return out


def email_settings_from_form(conn, form):
    current = get_email_settings(conn, include_password=True)

    try:
        port = int(safe_text(form.get("email_smtp_port", [current["smtp_port"]])[0]))
    except Exception:
        port = current["smtp_port"]
    port = max(1, min(65535, port))

    security = safe_text(form.get("email_security", [current["security"]])[0]).lower().strip()
    if security not in ("starttls", "ssl", "none"):
        security = "starttls"

    try:
        digest_hours = int(safe_text(form.get("email_digest_hours", [current.get("digest_hours", 2)])[0]))
    except Exception:
        digest_hours = current.get("digest_hours", 2)
    if digest_hours not in (0, 1, 2, 3, 6):
        digest_hours = 2

    return {
        "enabled": "email_enabled" in form,
        "smtp_host": safe_text(form.get("email_smtp_host", [current["smtp_host"]])[0]).strip(),
        "smtp_port": port,
        "security": security,
        "username": env_text("SMTP_USERNAME").strip(),
        "password": env_text("SMTP_PASSWORD"),
        "from_addr": safe_text(form.get("email_from", [current["from_addr"]])[0]).strip(),
        "to_addr": safe_text(form.get("email_to", [current["to_addr"]])[0]).strip(),
        "notify_movies": "email_notify_movies" in form,
        "notify_series": "email_notify_series" in form,
        "notify_episodes": "email_notify_episodes" in form,
        "notify_categories": "email_notify_categories" in form,
        "notify_removals": "email_notify_removals" in form,
        "notify_scan_errors": "email_notify_scan_errors" in form,
        "notify_backup_errors": "email_notify_backup_errors" in form,
        "digest_hours": digest_hours,
        "max_items": current.get("max_items", 25),
        "language": normalize_ui_language(form.get("ui_language", [current.get("language", get_ui_language(conn))])[0]),
    }


def save_email_settings(conn, form):
    old = get_email_settings(conn, include_password=False)
    settings = email_settings_from_form(conn, form)
    values = {
        "email_enabled": "1" if settings["enabled"] else "0",
        "email_smtp_host": settings["smtp_host"],
        "email_smtp_port": str(settings["smtp_port"]),
        "email_security": settings["security"],
        "email_from": settings["from_addr"],
        "email_to": settings["to_addr"],
        "email_notify_movies": "1" if settings["notify_movies"] else "0",
        "email_notify_series": "1" if settings["notify_series"] else "0",
        "email_notify_episodes": "1" if settings["notify_episodes"] else "0",
        "email_notify_categories": "1" if settings["notify_categories"] else "0",
        "email_notify_removals": "1" if settings["notify_removals"] else "0",
        "email_notify_scan_errors": "1" if settings["notify_scan_errors"] else "0",
        "email_notify_backup_errors": "1" if settings["notify_backup_errors"] else "0",
        "email_digest_hours": str(settings["digest_hours"]),
    }
    for key, value in values.items():
        set_meta(conn, key, value)

    # Ces clés n'ont plus aucune utilité et ne doivent jamais réapparaître.
    conn.execute("DELETE FROM meta WHERE key IN ('email_username','email_password')")

    digest_schedule_changed = (
        old.get("enabled") != settings.get("enabled")
        or old.get("digest_hours") != settings.get("digest_hours")
    )

    # Si les notifications sont coupées, les changements en attente ne doivent
    # pas ressortir plusieurs heures/jours plus tard lors d'une réactivation.
    if not settings.get("enabled"):
        conn.execute("DELETE FROM email_digest_queue")

    return settings, digest_schedule_changed

def parse_email_recipients(value):
    parts = re.split(r"[;,]", safe_text(value))
    return [x.strip() for x in parts if x.strip()]


def validate_email_settings(settings):
    lang = normalize_ui_language(settings.get("language", "fr"))
    if not safe_text(settings.get("smtp_host")).strip():
        raise ValueError(ui_text(lang, "Serveur SMTP manquant", "SMTP server is missing"))
    recipients = parse_email_recipients(settings.get("to_addr"))
    if not recipients:
        raise ValueError(ui_text(lang, "Destinataire manquant", "Recipient is missing"))
    sender = safe_text(settings.get("from_addr")).strip() or safe_text(settings.get("username")).strip()
    if not sender:
        raise ValueError(ui_text(lang, "Adresse expéditeur manquante", "Sender address is missing"))
    return sender, recipients


def _email_html_from_text(subject, body, lang="fr"):
    """Construit le rendu HTML d'un email à partir de son contenu texte."""
    lang = normalize_ui_language(lang)
    raw_body = safe_text(body)
    automatic_label = ui_text(lang, "Notification automatique", "Automated notification")
    country_heading = ui_text(lang, "Par pays / zone", "By country / zone")
    lines = raw_body.splitlines()
    digest_headers = {
        f"{APP_NAME} — Récapitulatif".lower(),
        f"{APP_NAME} — Digest".lower(),
    }
    digest_mode = any(
        safe_text(line).strip().lower() in digest_headers
        for line in lines[:6]
    )

    safe_subject = html.escape(safe_text(subject))
    safe_app = html.escape(APP_NAME)
    safe_version = html.escape(APP_VERSION)

    if not digest_mode:
        safe_body = html.escape(raw_body)
        return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0b1220;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#0b1220;padding:24px 10px;">
<tr><td align="center">
<table role="presentation" width="640" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:640px;background:#ffffff;border-radius:16px;overflow:hidden;">
<tr><td style="background:#111827;padding:26px 28px;font-family:Arial,sans-serif;">
<div style="font-size:22px;font-weight:800;color:#ffffff;">📡 {safe_app}</div>
<div style="font-size:13px;color:#cbd5e1;margin-top:7px;">{safe_subject}</div>
</td></tr>
<tr><td style="padding:26px 28px;font-family:Arial,sans-serif;font-size:14px;line-height:1.65;color:#1f2937;white-space:pre-wrap;">{safe_body}</td></tr>
<tr><td style="background:#f8fafc;border-top:1px solid #e5e7eb;padding:14px 28px;font-family:Arial,sans-serif;font-size:11px;color:#64748b;">
{safe_app} · v{safe_version} · {html.escape(automatic_label)}
</td></tr>
</table>
</td></tr></table>
</body></html>"""

    labels = {
        "films": ("🎬", "Films"),
        "movies": ("🎬", "Movies"),
        "séries": ("📺", "Séries"),
        "series": ("📺", "Series"),
        "épisodes": ("▶️", "Épisodes"),
        "episodes": ("▶️", "Episodes"),
        "catégories": ("📂", "Catégories"),
        "categories": ("📂", "Categories"),
        "suppressions": ("❌", "Suppressions"),
        "removals": ("❌", "Removals"),
    }

    section_icons = {
        "FILMS": "🎬",
        "MOVIES": "🎬",
        "SÉRIES": "📺",
        "SERIES": "📺",
        "ÉPISODES": "▶️",
        "EPISODES": "▶️",
        "CATÉGORIES": "📂",
        "CATEGORIES": "📂",
        "SUPPRESSIONS": "❌",
        "REMOVALS": "❌",
    }

    stats = []
    period = ""
    countries = []
    sections = []
    current_section = None
    latest_scan = ""
    notes = []

    for raw in lines:
        line = safe_text(raw).strip()
        if not line:
            continue

        lower = line.lower()
        upper = line.upper()

        if lower in digest_headers:
            continue

        if lower.startswith("période") or lower.startswith("period"):
            period = line
            continue

        stat_match = re.match(
            r"^(films|movies|séries|series|épisodes|episodes|catégories|categories|suppressions|removals)\s*:\s*(\d+)\s*$",
            line,
            re.IGNORECASE,
        )
        if stat_match:
            key = stat_match.group(1).lower()
            icon, label = labels[key]
            stats.append((icon, label, stat_match.group(2)))
            continue

        if lower.startswith("par pays") or lower.startswith("by country"):
            current_section = "__countries__"
            continue

        if upper in section_icons:
            current_section = upper
            sections.append([upper, []])
            continue

        if lower.startswith("dernier scan") or lower.startswith("latest scan"):
            latest_scan = line
            continue

        if line.startswith("• "):
            item = line[2:].strip()
            if current_section == "__countries__":
                countries.append(item)
            elif current_section and sections:
                sections[-1][1].append(item)
            continue

        if line.startswith("…") or line.startswith("..."):
            notes.append(line)

    stat_bg = ("#eff6ff", "#f5f3ff", "#ecfdf5", "#fff7ed", "#fff1f2")
    stat_fg = ("#1d4ed8", "#6d28d9", "#047857", "#c2410c", "#be123c")

    stat_cells = []
    for idx, (icon, label, value) in enumerate(stats[:5]):
        stat_cells.append(
            f'<td width="20%" valign="top" style="padding:4px;">'
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">'
            f'<tr><td align="center" style="background:{stat_bg[idx]};border-radius:12px;padding:14px 6px;">'
            f'<div style="font-size:25px;font-weight:800;color:{stat_fg[idx]};line-height:1;">{html.escape(value)}</div>'
            f'<div style="font-size:11px;color:#475569;margin-top:7px;">{icon} {html.escape(label)}</div>'
            f'</td></tr></table></td>'
        )

    stats_html = ""
    if stat_cells:
        stats_html = (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:14px 0 20px;">'
            '<tr>' + "".join(stat_cells) + '</tr></table>'
        )

    period_html = ""
    if period:
        period_html = (
            '<div style="font-size:13px;color:#64748b;margin-bottom:4px;">'
            + html.escape(period) + '</div>'
        )

    countries_html = ""
    if countries:
        chips = "".join(
            '<span style="display:inline-block;background:#eef2ff;color:#374151;'
            'border-radius:999px;padding:7px 10px;margin:0 6px 7px 0;font-size:12px;">'
            + html.escape(item) + '</span>'
            for item in countries
        )
        countries_html = (
            '<div style="margin-top:22px;">'
            f'<div style="font-size:16px;font-weight:800;color:#111827;margin-bottom:10px;">🌍 {html.escape(country_heading)}</div>'
            + chips + '</div>'
        )

    sections_html_parts = []

    for name, items in sections:
        if not items:
            continue

        icon = section_icons.get(name, "•")
        title = name.title()

        rows = "".join(
            '<tr><td style="padding:10px 0;border-bottom:1px solid #e5e7eb;'
            'font-size:14px;line-height:1.45;color:#1f2937;">'
            + html.escape(item) + '</td></tr>'
            for item in items
        )

        sections_html_parts.append(
            '<div style="margin-top:24px;">'
            f'<div style="font-size:17px;font-weight:800;color:#111827;margin-bottom:6px;">{icon} {html.escape(title)}</div>'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">'
            + rows + '</table></div>'
        )

    sections_html = "".join(sections_html_parts)

    notes_html = "".join(
        '<div style="margin-top:14px;padding:10px 12px;background:#f8fafc;border-radius:10px;'
        'font-size:12px;color:#64748b;">' + html.escape(note) + '</div>'
        for note in notes
    )

    latest_html = (
        html.escape(latest_scan)
        if latest_scan
        else datetime.now(TZ).strftime("%d/%m/%Y %H:%M")
    )

    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0b1220;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#0b1220;padding:24px 10px;">
<tr><td align="center">

<table role="presentation" width="640" cellspacing="0" cellpadding="0" border="0"
style="width:100%;max-width:640px;background:#ffffff;border-radius:16px;overflow:hidden;">

<tr>
<td style="background:#111827;padding:26px 28px;font-family:Arial,sans-serif;">
<div style="font-size:22px;font-weight:800;color:#ffffff;">📡 {safe_app}</div>
<div style="font-size:13px;color:#cbd5e1;margin-top:7px;">{safe_subject}</div>
</td>
</tr>

<tr>
<td style="padding:24px 28px 30px;font-family:Arial,sans-serif;">
{period_html}
{stats_html}
{countries_html}
{sections_html}
{notes_html}
</td>
</tr>

<tr>
<td style="background:#f8fafc;border-top:1px solid #e5e7eb;padding:14px 28px;
font-family:Arial,sans-serif;font-size:11px;line-height:1.5;color:#64748b;">
{latest_html}<br>
{safe_app} · v{safe_version} · {html.escape(automatic_label)}
</td>
</tr>

</table>
</td></tr></table>
</body>
</html>"""


def smtp_send(settings, subject, body):
    sender, recipients = validate_email_settings(settings)
    host = safe_text(settings.get("smtp_host")).strip()
    port = int(settings.get("smtp_port", 587))
    security = safe_text(settings.get("security", "starttls")).lower()
    username = safe_text(settings.get("username")).strip()
    password = safe_text(settings.get("password"))

    msg = EmailMessage()
    msg["Subject"] = safe_text(subject)
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    # Toujours conserver une version texte.
    plain_body = safe_text(body).rstrip()
    plain_body += f"\n\n{APP_NAME} · v{APP_VERSION}"
    msg.set_content(plain_body)

    # Version HTML pour les clients compatibles.
    msg.add_alternative(
        _email_html_from_text(subject, body, settings.get("language", "fr")),
        subtype="html",
    )

    context = ssl.create_default_context()

    if security == "ssl":
        client = smtplib.SMTP_SSL(host, port, timeout=20, context=context)
    else:
        client = smtplib.SMTP(host, port, timeout=20)

    with client:
        client.ehlo()

        if security == "starttls":
            client.starttls(context=context)
            client.ehlo()

        if username:
            client.login(username, password)

        client.send_message(msg)


def record_email_result(ok, error=""):
    try:
        with db() as conn:
            if ok:
                set_meta(conn, "email_last_success", iso_now())
                set_meta(conn, "email_last_error", "")
            else:
                set_meta(conn, "email_last_error", sanitize_watcher_error(error)[:500])
            conn.commit()
    except Exception:
        pass


def email_event_kind_enabled(kind, settings):
    return (
        (kind == "movie" and settings.get("notify_movies"))
        or (kind == "series" and settings.get("notify_series"))
        or (kind == "episode" and settings.get("notify_episodes"))
        or (kind in ("vod_category", "series_category") and settings.get("notify_categories"))
        or (
            kind in (
                "movie_removed",
                "series_removed",
                "episode_removed",
                "vod_category_removed",
                "series_category_removed",
            )
            and settings.get("notify_removals")
        )
    )


def _format_email_dt(value):
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(safe_text(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return safe_text(value)


def _episode_code(event):
    text = f"{safe_text(event['subtitle'])} {safe_text(event['title'])}"
    m = re.search(r"\bS(\d{1,2})E(\d{1,3})\b", text, re.IGNORECASE)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _episode_summary(title, items, lang="fr"):
    codes = [c for c in (_episode_code(e) for e in items) if c]
    if len(items) == 1:
        if codes:
            season, ep = codes[0]
            return f"• {title} — S{season:02d}E{ep:02d}"
        subtitle = safe_text(items[0]["subtitle"]).strip()
        return f"• {title}" + (f" — {subtitle}" if subtitle else "")

    suffix = f"{len(items)} {ui_text(lang, 'épisodes', 'episodes')}"
    if len(codes) == len(items):
        ordered = sorted(set(codes))
        seasons = {season for season, _ in ordered}
        if len(seasons) == 1:
            season = ordered[0][0]
            eps = [ep for _, ep in ordered]
            if len(eps) == 1:
                suffix += f" · S{season:02d}E{eps[0]:02d}"
            elif eps == list(range(min(eps), max(eps) + 1)):
                connector = ui_text(lang, "à", "to")
                suffix += f" · S{season:02d}E{min(eps):02d} {connector} S{season:02d}E{max(eps):02d}"
            else:
                suffix += " · " + ", ".join(f"S{season:02d}E{ep:02d}" for ep in eps[:8])
                if len(eps) > 8:
                    suffix += f"… (+{len(eps)-8})"
        else:
            code_text = ", ".join(f"S{s:02d}E{e:02d}" for s, e in ordered[:8])
            suffix += f" · {code_text}"
            if len(ordered) > 8:
                suffix += f"… (+{len(ordered)-8})"
    return f"• {title} — {suffix}"


def build_email_digest(events, settings, period_start=None, period_end=None):
    lang = normalize_ui_language(settings.get("language", "fr"))
    selected = [e for e in events if email_event_kind_enabled(safe_text(e["kind"]), settings)]
    if not selected:
        return None

    counts = {
        "movie": sum(1 for e in selected if e["kind"] == "movie"),
        "series": sum(1 for e in selected if e["kind"] == "series"),
        "episode": sum(1 for e in selected if e["kind"] == "episode"),
        "category": sum(1 for e in selected if e["kind"] in ("vod_category", "series_category")),
        "removal": sum(
            1 for e in selected
            if e["kind"] in (
                "movie_removed",
                "series_removed",
                "episode_removed",
                "vod_category_removed",
                "series_category_removed",
            )
        ),
    }
    total = sum(counts.values())
    if lang == "en":
        subject = f"{APP_NAME} — Digest: {total} change{'s' if total != 1 else ''}"
        lines = [f"{APP_NAME} — Digest", ""]
    else:
        subject = f"{APP_NAME} — Récapitulatif : {total} changement{'s' if total != 1 else ''}"
        lines = [f"{APP_NAME} — Récapitulatif", ""]

    if period_start and period_end:
        lines.append(f"{ui_text(lang, 'Période', 'Period')} : {_format_email_dt(period_start)} → {_format_email_dt(period_end)}")
        lines.append("")
    lines.extend([
        f"{ui_text(lang, 'Films', 'Movies')} : {counts['movie']}",
        f"{ui_text(lang, 'Séries', 'Series')} : {counts['series']}",
        f"{ui_text(lang, 'Épisodes', 'Episodes')} : {counts['episode']}",
        f"{ui_text(lang, 'Catégories', 'Categories')} : {counts['category']}",
        f"{ui_text(lang, 'Suppressions', 'Removals')} : {counts['removal']}",
    ])

    countries = {}
    for e in selected:
        candidates = [safe_text(e["category"]), safe_text(e["title"])]
        code = "OTHER"
        for candidate in candidates:
            detected = detect_country(candidate)
            if detected != "OTHER":
                code = detected
                break
        label = country_label(code, lang)
        countries[label] = countries.get(label, 0) + 1
    if countries:
        lines.extend(["", ui_text(lang, "Par pays / zone :", "By country / zone:")])
        for label, n in sorted(countries.items()):
            lines.append(f"• {label} : {n}")

    max_lines = max(5, min(100, int(settings.get("max_items", 25))))
    detail_lines = []

    movies = [e for e in selected if e["kind"] == "movie"]
    if movies:
        detail_lines.extend(["", ui_text(lang, "FILMS", "MOVIES")])
        detail_lines.extend(f"• {clean_display_title(e['title'])}" for e in movies)

    series = [e for e in selected if e["kind"] == "series"]
    if series:
        detail_lines.extend(["", ui_text(lang, "SÉRIES", "SERIES")])
        detail_lines.extend(f"• {clean_display_title(e['title'])}" for e in series)

    episodes = [e for e in selected if e["kind"] == "episode"]
    if episodes:
        detail_lines.extend(["", ui_text(lang, "ÉPISODES", "EPISODES")])
        groups = {}
        for e in episodes:
            groups.setdefault(clean_display_title(e["title"]), []).append(e)
        for title, items in groups.items():
            detail_lines.append(_episode_summary(title, items, lang))

    categories = [e for e in selected if e["kind"] in ("vod_category", "series_category")]
    if categories:
        detail_lines.extend(["", ui_text(lang, "CATÉGORIES", "CATEGORIES")])
        detail_lines.extend(f"• {safe_text(e['title'])}" for e in categories)

    removals = [
        e for e in selected
        if e["kind"] in (
            "movie_removed",
            "series_removed",
            "episode_removed",
            "vod_category_removed",
            "series_category_removed",
        )
    ]
    if removals:
        detail_lines.extend(["", ui_text(lang, "SUPPRESSIONS", "REMOVALS")])
        for e in removals:
            title = clean_display_title(e["title"])
            subtitle = safe_text(e["subtitle"]).strip()
            detail_lines.append(
                f"• {title}" + (f" — {subtitle}" if subtitle else "")
            )

    visible = []
    content_count = 0
    truncated = False
    for line in detail_lines:
        is_content = line.startswith("• ")
        if is_content and content_count >= max_lines:
            truncated = True
            continue
        visible.append(line)
        if is_content:
            content_count += 1
    lines.extend(visible)
    if truncated:
        lines.append(ui_text(
            lang,
            "… détail tronqué ; les compteurs ci-dessus restent complets.",
            "… details truncated; the totals above remain complete.",
        ))

    try:
        with db() as conn:
            last_scan_dt = parse_local_iso(get_meta(conn, "last_success", ""))
    except Exception:
        last_scan_dt = None

    last_scan_text = (
        last_scan_dt.strftime("%d/%m/%Y %H:%M")
        if last_scan_dt
        else "—"
    )

    lines.extend([
        "",
        f"{ui_text(lang, 'Dernier scan', 'Latest scan')} : {last_scan_text}"
    ])
    return subject, "\n".join(lines), selected


def _queued_email_rows(conn):
    return conn.execute("""
        SELECT e.*, q.queued_at
        FROM email_digest_queue q
        JOIN events e ON e.event_key=q.event_key
        ORDER BY q.queued_at ASC, e.detected_at ASC
    """).fetchall()


def queue_email_notifications(events):
    """Ajoute les changements du scan au prochain récapitulatif email."""
    try:
        with db() as conn:
            settings = get_email_settings(conn, include_password=True)
            if not settings.get("enabled"):
                return
            selected = [e for e in events if email_event_kind_enabled(safe_text(e["kind"]), settings)]
            if not selected:
                return
            now = iso_now()
            conn.executemany(
                "INSERT OR IGNORE INTO email_digest_queue(event_key,queued_at) VALUES(?,?)",
                [(safe_text(e["event_key"]), now) for e in selected],
            )
            conn.commit()
        EMAIL_WAKE.set()
        if settings.get("digest_hours", 2) == 0:
            flush_email_digest(force=True)
    except Exception as exc:
        message = sanitize_watcher_error(f"{type(exc).__name__}: {exc}")
        print(f"[WARN] Mise en file email impossible: {message}", flush=True)


def flush_email_digest(force=False):
    """Envoie le récapitulatif arrivé à échéance et vide uniquement son lot."""
    if not EMAIL_SEND_LOCK.acquire(blocking=False):
        return False
    try:
        with db() as conn:
            settings = get_email_settings(conn, include_password=True)
            if not settings.get("enabled"):
                conn.execute("DELETE FROM email_digest_queue")
                conn.commit()
                return False
            conn.execute("DELETE FROM email_digest_queue WHERE event_key NOT IN (SELECT event_key FROM events)")
            rows = _queued_email_rows(conn)
            if not rows:
                conn.commit()
                return False

            hours = int(settings.get("digest_hours", 2))
            oldest = parse_local_iso(rows[0]["queued_at"])
            now_local = datetime.now(TZ)
            if not force and hours > 0 and oldest and now_local < oldest + timedelta(hours=hours):
                conn.commit()
                return False

            last_attempt = parse_local_iso(get_meta(conn, "email_digest_last_attempt", ""))
            last_error = safe_text(get_meta(conn, "email_last_error", "")).strip()
            if (
                not force
                and last_error
                and last_attempt
                and (now_local - last_attempt) < timedelta(minutes=EMAIL_RETRY_MINUTES)
            ):
                conn.commit()
                return False

            keys = [safe_text(r["event_key"]) for r in rows]
            period_start = min((safe_text(r["detected_at"]) for r in rows), default=iso_now())
            period_end = iso_now()
            set_meta(conn, "email_digest_last_attempt", period_end)
            conn.commit()

        digest = build_email_digest(rows, settings, period_start=period_start, period_end=period_end)
        if not digest:
            with db() as conn:
                conn.executemany("DELETE FROM email_digest_queue WHERE event_key=?", [(k,) for k in keys])
                conn.commit()
            return False

        subject, body, selected = digest
        smtp_send(settings, subject, body)

        with db() as conn:
            conn.executemany("DELETE FROM email_digest_queue WHERE event_key=?", [(k,) for k in keys])
            set_meta(conn, "email_digest_last_sent", iso_now())
            conn.commit()
        record_email_result(True)
        print(f"[OK] Récapitulatif email envoyé ({len(selected)} changement(s)).", flush=True)
        return True
    except Exception as exc:
        message = sanitize_watcher_error(f"{type(exc).__name__}: {exc}")
        record_email_result(False, message)
        print(f"[WARN] Échec récapitulatif email: {message}", flush=True)
        return False
    finally:
        EMAIL_SEND_LOCK.release()


def email_digest_loop():
    while True:
        try:
            flush_email_digest(force=False)
        except Exception as exc:
            print(f"[WARN] Planificateur email: {sanitize_watcher_error(exc)}", flush=True)
        EMAIL_WAKE.wait(EMAIL_CHECK_SECONDS)
        EMAIL_WAKE.clear()


def send_email_test(settings):
    lang = normalize_ui_language(settings.get("language", "fr"))
    if lang == "en":
        subject = f"{APP_NAME} — Notification test"
        body = (
            f"✅ {APP_NAME}\n\nEmail notifications are working correctly.\n"
            f"Test performed on {datetime.now(TZ).strftime('%d/%m/%Y at %H:%M')}."
        )
    else:
        subject = f"{APP_NAME} — Test de notification"
        body = (
            f"✅ {APP_NAME}\n\nLes notifications par email fonctionnent correctement.\n"
            f"Test effectué le {datetime.now(TZ).strftime('%d/%m/%Y à %H:%M')}."
        )
    smtp_send(settings, subject, body)
    record_email_result(True)


def notify_backup_error(message, trigger="auto"):
    try:
        with db() as conn:
            settings = get_email_settings(conn, include_password=True)
        if not settings.get("enabled") or not settings.get("notify_backup_errors"):
            return
        lang = normalize_ui_language(settings.get("language", "fr"))
        if lang == "en":
            subject = f"{APP_NAME} — Backup failed"
            body = (
                "A SQLite backup failed.\n\n"
                f"Type: {trigger}\n"
                f"Error: {sanitize_watcher_error(message)}\n"
                f"Date: {datetime.now(TZ).strftime('%d/%m/%Y %H:%M')}"
            )
        else:
            subject = f"{APP_NAME} — Échec de sauvegarde"
            body = (
                "Une sauvegarde SQLite a échoué.\n\n"
                f"Type : {trigger}\n"
                f"Erreur : {sanitize_watcher_error(message)}\n"
                f"Date : {datetime.now(TZ).strftime('%d/%m/%Y %H:%M')}"
            )
        smtp_send(settings, subject, body)
        record_email_result(True)
    except Exception as exc:
        record_email_result(False, f"{type(exc).__name__}: {exc}")


def register_scan_failure(message):
    """Alerte après 3 échecs fatals consécutifs, puis au plus toutes les 6 h."""
    try:
        with db() as conn:
            try:
                failures = int(get_meta(conn, "scan_consecutive_failures", "0") or 0) + 1
            except Exception:
                failures = 1
            set_meta(conn, "scan_consecutive_failures", str(failures))
            settings = get_email_settings(conn, include_password=True)
            last_alert = parse_local_iso(get_meta(conn, "email_last_scan_error_alert", ""))
            should_alert = failures >= 3 and settings.get("enabled") and settings.get("notify_scan_errors")
            if should_alert and last_alert and (datetime.now(TZ) - last_alert) < timedelta(hours=6):
                should_alert = False
            if should_alert:
                set_meta(conn, "email_last_scan_error_alert", iso_now())
            conn.commit()
        if not should_alert:
            return
        lang = normalize_ui_language(settings.get("language", "fr"))
        if lang == "en":
            subject = f"{APP_NAME} — {failures} consecutive scan failures"
            body = (
                f"{APP_NAME} encountered {failures} consecutive scan failures.\n\n"
                f"Latest error: {sanitize_watcher_error(message)}\n"
                f"Date: {datetime.now(TZ).strftime('%d/%m/%Y %H:%M')}\n\n"
                "Another reminder will only be sent after several hours if the issue persists."
            )
        else:
            subject = f"{APP_NAME} — {failures} échecs de scan consécutifs"
            body = (
                f"L’application {APP_NAME} a rencontré {failures} échecs de scan consécutifs.\n\n"
                f"Dernière erreur : {sanitize_watcher_error(message)}\n"
                f"Date : {datetime.now(TZ).strftime('%d/%m/%Y %H:%M')}\n\n"
                "Un nouveau rappel ne sera envoyé qu'après plusieurs heures si le problème persiste."
            )
        smtp_send(settings, subject, body)
        record_email_result(True)
    except Exception as exc:
        record_email_result(False, f"{type(exc).__name__}: {exc}")


def register_scan_success(conn):
    set_meta(conn, "scan_consecutive_failures", "0")


def normalize_scan_interval(value, default=15):
    try:
        interval = int(round(float(value)))
    except Exception:
        interval = int(default)
    return max(5, min(1440, interval))


def parse_local_iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ)
    except Exception:
        return None


def get_scan_settings(conn):
    default_interval = normalize_scan_interval(CFG.get("interval_minutes", 15))
    interval = normalize_scan_interval(
        get_meta(conn, "scan_interval_minutes", str(default_interval)),
        default_interval,
    )
    return {
        "interval_minutes": interval,
        "schedule_changed_at": get_meta(conn, "scan_schedule_changed_at", ""),
        "last_attempt": get_meta(conn, "scan_last_attempt", ""),
        "last_success": get_meta(conn, "last_success", ""),
        "last_trigger": get_meta(conn, "scan_last_trigger", ""),
    }


def save_scan_settings(conn, form):
    old = get_scan_settings(conn)
    mode = safe_text(form.get("scan_interval_mode", [str(old["interval_minutes"])])[0]).strip()
    if mode == "custom":
        raw_interval = form.get("scan_interval_custom", [str(old["interval_minutes"])])[0]
    else:
        raw_interval = mode
    interval = normalize_scan_interval(raw_interval, old["interval_minutes"])

    set_meta(conn, "scan_interval_minutes", str(interval))
    changed = interval != old["interval_minutes"]
    if changed:
        set_meta(conn, "scan_schedule_changed_at", iso_now())
    # IMPORTANT : ne pas réveiller le scheduler ici. La transaction SQLite
    # n'est pas encore commitée et le thread pourrait relire l'ancienne
    # périodicité. Le réveil est fait juste après conn.commit().
    return interval, changed


def scan_next_due(settings, now_local=None):
    now_local = now_local or datetime.now(TZ)
    interval = timedelta(minutes=normalize_scan_interval(settings.get("interval_minutes", 15)))
    last_attempt = parse_local_iso(settings.get("last_attempt"))
    schedule_changed = parse_local_iso(settings.get("schedule_changed_at"))

    basis = None
    for candidate in (last_attempt, schedule_changed):
        if candidate and (basis is None or candidate > basis):
            basis = candidate
    if basis is None:
        return now_local
    return basis + interval


def scan_is_due(settings, now_local=None):
    now_local = now_local or datetime.now(TZ)
    return now_local >= scan_next_due(settings, now_local)


def get_scan_status(lang=None):
    try:
        with db() as conn:
            settings = get_scan_settings(conn)
            settings["language"] = get_ui_language(conn)
            last_success = get_meta(conn, "last_success", "")
            duration = get_meta(conn, "last_sync_duration_seconds", "")
            last_error = get_meta(conn, "last_error", "")
    except Exception:
        settings = {
            "interval_minutes": normalize_scan_interval(CFG.get("interval_minutes", 15)),
            "schedule_changed_at": "", "last_attempt": "", "last_success": "",
            "last_trigger": "",
            "language": normalize_ui_language(lang or "fr"),
        }
        last_success = ""
        duration = ""
        last_error = ""

    lang = normalize_ui_language(lang or settings.get("language", "fr")) if isinstance(settings, dict) else normalize_ui_language(lang)
    if not lang:
        lang = get_ui_language()

    with SCAN_STATE_LOCK:
        running = bool(SCAN_STATE.get("running"))
        trigger = safe_text(SCAN_STATE.get("trigger"))
        started_at = safe_text(SCAN_STATE.get("started_at"))

    next_due = scan_next_due(settings)
    last_dt = parse_local_iso(last_success)
    return {
        "running": running,
        "trigger": trigger,
        "started_at": started_at,
        "interval_minutes": settings["interval_minutes"],
        "last_success_iso": last_success,
        "last_detail": last_dt.strftime("%d/%m %H:%M") if last_dt else "—",
        "next_iso": next_due.isoformat(),
        "next_detail": ui_text(lang, "Scan en cours…", "Scan running…") if running else next_due.strftime("%H:%M"),
        "duration_seconds": safe_text(duration) or "—",
        "last_error": safe_text(last_error),
    }


def _scan_worker(trigger):
    started = iso_now()
    with SCAN_STATE_LOCK:
        SCAN_STATE.update({"running": True, "trigger": trigger, "started_at": started})
    try:
        # L'heure de tentative sert de point de départ au prochain intervalle,
        # même si le fournisseur renvoie temporairement une erreur.
        with db() as conn:
            set_meta(conn, "scan_last_attempt", started)
            set_meta(conn, "scan_last_trigger", trigger)
            conn.commit()
        sync_once()
    except Exception as exc:
        print(f"[ERREUR] Scan {trigger} : {safe_text(exc)[:500]}", flush=True)
    finally:
        with SCAN_STATE_LOCK:
            SCAN_STATE.update({"running": False, "trigger": "", "started_at": ""})
        SCAN_RUN_LOCK.release()
        SCAN_WAKE.set()


def start_scan(trigger="manual"):
    if not SCAN_RUN_LOCK.acquire(blocking=False):
        return False
    with SCAN_STATE_LOCK:
        SCAN_STATE.update({"running": True, "trigger": trigger, "started_at": iso_now()})
    try:
        threading.Thread(target=_scan_worker, args=(trigger,), daemon=True).start()
        return True
    except Exception:
        with SCAN_STATE_LOCK:
            SCAN_STATE.update({"running": False, "trigger": "", "started_at": ""})
        SCAN_RUN_LOCK.release()
        raise


def prune_backups(keep):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        BACKUP_DIR.glob("nouveautes-*.sqlite3"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old in files[max(1, int(keep)):]:
        try:
            old.unlink()
        except FileNotFoundError:
            pass
    return len(list(BACKUP_DIR.glob("nouveautes-*.sqlite3")))


def create_db_backup(trigger="manual"):
    """Crée une copie SQLite cohérente via l'API backup native de SQLite."""
    with BACKUP_LOCK:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        now_local = datetime.now(TZ)
        stamp = now_local.strftime("%Y-%m-%d_%H-%M-%S")
        final_path = BACKUP_DIR / f"nouveautes-{stamp}.sqlite3"
        tmp_path = BACKUP_DIR / f".nouveautes-{stamp}.sqlite3.tmp"

        try:
            if tmp_path.exists():
                tmp_path.unlink()

            # sqlite3.Connection.backup() inclut correctement l'état WAL et
            # produit une base autonome/restaurable, contrairement à une simple copie.
            with sqlite3.connect(DB_PATH, timeout=30) as source:
                with sqlite3.connect(tmp_path, timeout=30) as destination:
                    source.backup(destination)
                    destination.commit()

            os.replace(tmp_path, final_path)

            with db() as conn:
                settings = get_backup_settings(conn)
                now_iso = iso_now()
                set_meta(conn, "backup_last_success", now_iso)
                set_meta(conn, "backup_last_error", "")
                if trigger == "auto":
                    set_meta(conn, "backup_last_auto", now_iso)
                conn.commit()
                keep = settings["keep"]

            count = prune_backups(keep)
            print(
                f"[OK] Sauvegarde SQLite ({trigger}) : {final_path.name} · "
                f"{count} sauvegarde(s) conservée(s).",
                flush=True,
            )
            return {"ok": True, "path": str(final_path), "count": count}
        except Exception as exc:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            message = safe_text(exc)[:500]
            try:
                with db() as conn:
                    set_meta(conn, "backup_last_error", message)
                    conn.commit()
            except Exception:
                pass
            print(f"[ERREUR] Sauvegarde SQLite ({trigger}) : {message}", flush=True)
            threading.Thread(
                target=notify_backup_error, args=(message, trigger), daemon=True
            ).start()
            return {"ok": False, "error": message}



def get_backup_status(lang=None):
    """Retourne l'état courant des sauvegardes pour l'UI et l'API."""
    lang = normalize_ui_language(lang or get_ui_language())
    try:
        files = sorted(
            BACKUP_DIR.glob("nouveautes-*.sqlite3"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        files = []

    def human_size(size_bytes):
        try:
            size = float(max(0, int(size_bytes)))
        except Exception:
            size = 0.0
        units = (
            ("o", "Ko", "Mo", "Go", "To")
            if lang == "fr"
            else ("B", "KB", "MB", "GB", "TB")
        )
        index = 0
        while size >= 1024 and index < len(units) - 1:
            size /= 1024.0
            index += 1
        if index == 0:
            value = str(int(size))
        else:
            value = f"{size:.1f}".rstrip("0").rstrip(".")
            if lang == "fr":
                value = value.replace(".", ",")
        return f"{value} {units[index]}"

    if not files:
        return {
            "label": ui_text(lang, "Aucune sauvegarde", "No backup"),
            "class": "error",
            "icon": "❌",
            "detail": ui_text(lang, "Aucun fichier trouvé", "No file found"),
            "count": 0,
            "latest_iso": "",
            "latest_size": "—",
            "total_size": human_size(0),
        }

    latest = files[0]

    try:
        latest_size_bytes = latest.stat().st_size
    except Exception:
        latest_size_bytes = 0

    total_size_bytes = 0
    for backup_file in files:
        try:
            total_size_bytes += backup_file.stat().st_size
        except Exception:
            pass
    try:
        mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc).astimezone(TZ)
        age_hours = (datetime.now(TZ) - mtime).total_seconds() / 3600
        latest_iso = mtime.isoformat()
    except Exception:
        mtime = None
        age_hours = 9999
        latest_iso = ""

    if age_hours <= 36:
        status_class = "ok"
        icon = "✅"
        label = ui_text(lang, "Sauvegarde OK", "Backup OK")
    elif age_hours <= 60:
        status_class = "warn"
        icon = "⚠️"
        label = ui_text(lang, "Sauvegarde ancienne", "Old backup")
    else:
        status_class = "error"
        icon = "❌"
        label = ui_text(lang, "Sauvegarde à vérifier", "Backup needs checking")

    detail = mtime.strftime("%d/%m %H:%M") if mtime else ui_text(lang, "Date inconnue", "Unknown date")
    return {
        "label": label,
        "class": status_class,
        "icon": icon,
        "detail": detail,
        "count": len(files),
        "latest_iso": latest_iso,
        "latest_size": human_size(latest_size_bytes),
        "total_size": human_size(total_size_bytes),
    }

def backup_is_due(settings, now_local=None):
    if not settings.get("enabled"):
        return False

    now_local = now_local or datetime.now(TZ)
    try:
        hour, minute = [int(x) for x in settings.get("time", "03:15").split(":", 1)]
    except Exception:
        hour, minute = 3, 15

    scheduled_today = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def parse_local(value):
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(TZ)
        except Exception:
            return None

    previous = parse_local(settings.get("last_auto"))
    schedule_changed = parse_local(settings.get("schedule_changed_at"))

    # Si le planning a été modifié après la dernière sauvegarde automatique,
    # on repart du nouveau planning. Ex. : auto à 09:32, changement à 09:53
    # pour 09:54 => la prochaine sauvegarde est bien aujourd'hui à 09:54.
    if schedule_changed and (previous is None or schedule_changed > previous):
        changed_day_due = schedule_changed.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        # Si l'heure choisie est déjà passée au moment où l'on enregistre,
        # la sauvegarde devient due immédiatement au prochain passage du loop.
        next_due = changed_day_due if schedule_changed <= changed_day_due else schedule_changed
        return now_local >= next_due

    if previous is None:
        return now_local >= scheduled_today

    day_step = {"daily": 1, "2days": 2, "weekly": 7}.get(settings.get("frequency"), 1)
    next_date = previous.date() + timedelta(days=day_step)
    next_due = datetime(
        next_date.year, next_date.month, next_date.day,
        hour, minute, tzinfo=TZ,
    )
    return now_local >= next_due


def backup_loop():
    while True:
        try:
            with db() as conn:
                settings = get_backup_settings(conn)
            if backup_is_due(settings):
                # Le verrou principal évite de lancer la sauvegarde au milieu
                # d'une opération applicative longue. SQLite reste néanmoins
                # la source de cohérence grâce à son API backup native.
                with LOCK:
                    create_db_backup("auto")
        except Exception as exc:
            print(f"[ERREUR] Planificateur sauvegarde : {safe_text(exc)[:500]}", flush=True)
        time.sleep(BACKUP_CHECK_SECONDS)

def cleanup_old_events(conn):
    days = HISTORY_RETENTION_DAYS
    cutoff = (utc_now() - timedelta(days=days)).isoformat()
    cur = conn.execute("DELETE FROM events WHERE detected_at < ?", (cutoff,))
    conn.execute("DELETE FROM email_digest_queue WHERE event_key NOT IN (SELECT event_key FROM events)")
    set_meta(conn, "retention_days", days)
    set_meta(conn, "last_cleanup", iso_now())
    set_meta(conn, "last_cleanup_deleted", cur.rowcount)
    return cur.rowcount

def _meta_datetime(conn, key):
    raw = safe_text(get_meta(conn, key, "")).strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def db_maintenance_due(conn, now=None):
    now = now or utc_now()
    last = _meta_datetime(conn, "db_maintenance_last_run")
    if last is None:
        return True
    return now - last >= timedelta(hours=DB_MAINTENANCE_INTERVAL_HOURS)


def sqlite_space_stats(conn):
    page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
    free_pages = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
    free_bytes = free_pages * page_size
    free_ratio = (free_pages / page_count) if page_count else 0.0
    return {
        "page_size": page_size,
        "page_count": page_count,
        "free_pages": free_pages,
        "free_bytes": free_bytes,
        "free_ratio": free_ratio,
    }


def db_vacuum_due(conn, stats=None, now=None):
    now = now or utc_now()
    stats = stats or sqlite_space_stats(conn)
    if stats["free_bytes"] < VACUUM_MIN_FREE_BYTES:
        return False
    if stats["free_ratio"] < VACUUM_MIN_FREE_RATIO:
        return False
    last = _meta_datetime(conn, "db_vacuum_last_run")
    if last is not None and now - last < timedelta(days=VACUUM_MIN_INTERVAL_DAYS):
        return False
    return True


def run_db_maintenance(conn, force=False):
    """Entretien conservateur de la base, au plus une fois par jour.

    Les films/séries inactifs sont gardés un an afin qu'une disparition temporaire
    suivie d'un retour avec le même ID fournisseur ne soit pas annoncée comme une
    nouveauté. Les historiques techniques d'identité sont gardés deux ans.
    """
    now = utc_now()
    if not force and not db_maintenance_due(conn, now):
        return None

    inactive_cutoff = (now - timedelta(days=INACTIVE_ITEM_RETENTION_DAYS)).isoformat()
    identity_cutoff = (now - timedelta(days=IDENTITY_HISTORY_RETENTION_DAYS)).isoformat()

    # Supprimer d'abord le cache épisodes des séries réellement anciennes.
    old_series_ids = [
        safe_text(r[0]) for r in conn.execute(
            """
            SELECT id FROM series
            WHERE active=0 AND last_seen IS NOT NULL AND last_seen < ?
            """,
            (inactive_cutoff,),
        ).fetchall()
    ]

    deleted_episodes = 0
    if old_series_ids:
        placeholders = ",".join("?" for _ in old_series_ids)
        cur = conn.execute(
            f"DELETE FROM episodes WHERE series_id IN ({placeholders})",
            old_series_ids,
        )
        deleted_episodes += max(0, int(cur.rowcount or 0))

    # Un épisode sans série est inutilisable et ne peut plus être suivi.
    cur = conn.execute(
        """
        DELETE FROM episodes
        WHERE series_id NOT IN (SELECT id FROM series)
        """
    )
    deleted_orphans = max(0, int(cur.rowcount or 0))
    deleted_episodes += deleted_orphans

    cur = conn.execute(
        """
        DELETE FROM series
        WHERE active=0 AND last_seen IS NOT NULL AND last_seen < ?
        """,
        (inactive_cutoff,),
    )
    deleted_series = max(0, int(cur.rowcount or 0))

    cur = conn.execute(
        """
        DELETE FROM movies
        WHERE active=0 AND last_seen IS NOT NULL AND last_seen < ?
        """,
        (inactive_cutoff,),
    )
    deleted_movies = max(0, int(cur.rowcount or 0))

    history_deleted = {}
    for table in ("movie_id_changes", "series_id_changes", "episode_id_changes"):
        cur = conn.execute(
            f"DELETE FROM {table} WHERE detected_at < ?",
            (identity_cutoff,),
        )
        history_deleted[table] = max(0, int(cur.rowcount or 0))

    # Laisse SQLite mettre à jour ses statistiques sans coût important.
    try:
        conn.execute("PRAGMA optimize")
    except Exception:
        pass

    set_meta(conn, "db_maintenance_last_run", now.isoformat())
    set_meta(conn, "db_maintenance_inactive_days", INACTIVE_ITEM_RETENTION_DAYS)
    set_meta(conn, "db_maintenance_identity_days", IDENTITY_HISTORY_RETENTION_DAYS)
    set_meta(conn, "db_maintenance_deleted_movies", deleted_movies)
    set_meta(conn, "db_maintenance_deleted_series", deleted_series)
    set_meta(conn, "db_maintenance_deleted_episodes", deleted_episodes)
    set_meta(conn, "db_maintenance_deleted_orphans", deleted_orphans)
    set_meta(conn, "db_maintenance_deleted_movie_id_changes", history_deleted["movie_id_changes"])
    set_meta(conn, "db_maintenance_deleted_series_id_changes", history_deleted["series_id_changes"])
    set_meta(conn, "db_maintenance_deleted_episode_id_changes", history_deleted["episode_id_changes"])
    conn.commit()

    before = sqlite_space_stats(conn)
    vacuumed = False
    vacuum_error = ""
    if db_vacuum_due(conn, before, now):
        try:
            # VACUUM exige d'être hors transaction. Le LOCK applicatif du scan
            # empêche les opérations longues concurrentes; en cas de verrou tiers,
            # on reporte simplement au prochain entretien.
            conn.execute("VACUUM")
            vacuumed = True
            set_meta(conn, "db_vacuum_last_run", iso_now())
            set_meta(conn, "db_vacuum_last_error", "")
            conn.commit()
        except Exception as exc:
            vacuum_error = safe_text(exc)[:300]
            set_meta(conn, "db_vacuum_last_error", vacuum_error)
            conn.commit()

    after = sqlite_space_stats(conn)
    set_meta(conn, "db_maintenance_free_bytes", after["free_bytes"])
    set_meta(conn, "db_maintenance_free_ratio", f"{after['free_ratio']:.6f}")
    set_meta(conn, "db_maintenance_vacuumed", "1" if vacuumed else "0")
    conn.commit()

    total_deleted = (
        deleted_movies + deleted_series + deleted_episodes
        + sum(history_deleted.values())
    )
    print(
        f"[OK] Entretien DB: {deleted_movies} film(s), {deleted_series} série(s), "
        f"{deleted_episodes} épisode(s), {sum(history_deleted.values())} historique(s) "
        f"supprimé(s); libre {after['free_bytes'] / 1024 / 1024:.1f} MB "
        f"({after['free_ratio'] * 100:.1f}%); VACUUM={'oui' if vacuumed else 'non'}."
        , flush=True
    )
    if vacuum_error:
        print(f"[WARN] VACUUM reporté : {vacuum_error}", flush=True)

    return {
        "deleted": total_deleted,
        "deleted_movies": deleted_movies,
        "deleted_series": deleted_series,
        "deleted_episodes": deleted_episodes,
        "deleted_orphans": deleted_orphans,
        "history_deleted": history_deleted,
        "vacuumed": vacuumed,
        "free_bytes": after["free_bytes"],
        "free_ratio": after["free_ratio"],
    }

def api(action=None, **params):
    q = {"username": CFG["username"], "password": CFG["password"]}
    if action:
        q["action"] = action
    q.update({k: v for k, v in params.items() if v is not None})

    url = CFG["provider_url"] + "/player_api.php?" + urlencode(q)
    req = Request(url, headers={
        "User-Agent": CFG["user_agent"],
        "Accept": "application/json",
    })

    last_exc = None
    for attempt in range(3):
        try:
            with urlopen(req, timeout=float(CFG["request_timeout_seconds"])) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except Exception as e:
            last_exc = e
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Erreur API Xtream ({action or 'login'}): {last_exc}")

def sync_available_categories(conn, kind, categories, now):
    """Mémorise le catalogue de catégories pour le menu de réglages.

    Une réponse vide au démarrage (réseau/API pas encore prêt) ne doit jamais
    désactiver le dernier catalogue connu ni faire disparaître les préférences.
    """
    categories = categories if isinstance(categories, list) else []
    valid_categories = [
        cat for cat in categories
        if isinstance(cat, dict)
        and safe_text(cat.get("category_id")).strip()
        and safe_text(cat.get("category_name")).strip()
    ]
    if not valid_categories:
        print(
            f"[WARN] Catalogue catégories {kind} vide/non exploitable : "
            "dernier état connu conservé.",
            flush=True
        )
        return False

    conn.execute("UPDATE available_categories SET active=0 WHERE kind=?", (kind,))

    for cat in valid_categories:
        name = safe_text(cat.get("category_name")).strip()
        cid = safe_text(cat.get("category_id")).strip()
        if not cid or not name:
            continue

        code = detect_country(name)
        conn.execute("""
            INSERT INTO available_categories(
                kind,category_id,name,country_code,first_seen,last_seen,active
            ) VALUES(?,?,?,?,?,?,1)
            ON CONFLICT(kind,category_id) DO UPDATE SET
                name=excluded.name,
                country_code=excluded.country_code,
                last_seen=excluded.last_seen,
                active=1
        """, (kind, cid, name, code, now, now))

        country_row = conn.execute(
            "SELECT enabled FROM country_preferences WHERE country_code=?", (code,)
        ).fetchone()
        if country_row is None:
            # Aucun pays n'est imposé par défaut. Une nouvelle installation
            # découvre d'abord le catalogue, puis l'utilisateur choisit les pays
            # à surveiller dans l'interface. Un nouveau pays détecté plus tard
            # reste lui aussi désactivé jusqu'à sélection explicite.
            country_enabled = 0
            conn.execute("""
                INSERT INTO country_preferences(country_code,enabled,updated_at)
                VALUES(?,?,?)
            """, (code, country_enabled, now))
        else:
            country_enabled = int(country_row["enabled"])

        pref = conn.execute("""
            SELECT enabled FROM category_preferences
            WHERE kind=? AND category_id=?
        """, (kind, cid)).fetchone()
        if pref is None:
            # Dans un pays déjà surveillé, une nouvelle catégorie est activée
            # automatiquement. Il n'existe plus d'exception française codée en dur.
            enabled = 1 if country_enabled else 0
            # Si le fournisseur fait apparaître une nouvelle catégorie alors que
            # le watcher possède déjà une baseline, son contenu existant devient
            # d'abord une référence. Cela évite des milliers de faux "nouveaux".
            baseline_pending = 1 if (enabled and get_meta(conn, "baseline_complete", "0") == "1") else 0
            conn.execute("""
                INSERT INTO category_preferences(
                    kind,category_id,enabled,updated_at,baseline_pending
                ) VALUES(?,?,?,?,?)
            """, (kind, cid, enabled, now, baseline_pending))

    return True


def last_known_available_categories(conn, kind):
    """Reconstruit le dernier catalogue fiable connu depuis SQLite.

    Cas important après un ancien démarrage défaillant : une version précédente
    pouvait avoir passé toutes les catégories à active=0 avant de recevoir une
    réponse fournisseur vide. Si aucune catégorie active ne subsiste, on restaure
    le dernier snapshot complet grâce au last_seen le plus récent.
    """
    rows = conn.execute(
        "SELECT category_id,name FROM available_categories WHERE kind=? AND active=1 ORDER BY category_id",
        (kind,)
    ).fetchall()
    if rows:
        return [
            {"category_id": safe_text(r["category_id"]), "category_name": safe_text(r["name"])}
            for r in rows
        ]

    snapshot = conn.execute(
        "SELECT MAX(last_seen) AS last_seen FROM available_categories WHERE kind=?",
        (kind,)
    ).fetchone()
    last_seen = safe_text(snapshot["last_seen"]) if snapshot else ""
    if not last_seen:
        return []

    rows = conn.execute(
        """
        SELECT category_id,name
        FROM available_categories
        WHERE kind=? AND last_seen=?
        ORDER BY category_id
        """,
        (kind, last_seen)
    ).fetchall()
    if not rows:
        return []

    # Réactive uniquement les lignes du dernier snapshot connu. Les catégories
    # plus anciennes (déjà disparues avant ce snapshot) restent inactives.
    conn.execute("UPDATE available_categories SET active=0 WHERE kind=?", (kind,))
    conn.execute(
        "UPDATE available_categories SET active=1 WHERE kind=? AND last_seen=?",
        (kind, last_seen)
    )
    print(
        f"[WARN] Catalogue {kind} restauré depuis le dernier snapshot SQLite "
        f"({len(rows)} catégorie(s), {last_seen}).",
        flush=True
    )
    return [
        {"category_id": safe_text(r["category_id"]), "category_name": safe_text(r["name"])}
        for r in rows
    ]


def selected_category_map(conn, kind, categories):
    country_enabled = {
        r["country_code"]: int(r["enabled"]) == 1
        for r in conn.execute("SELECT country_code,enabled FROM country_preferences")
    }
    category_enabled = {
        safe_text(r["category_id"]): int(r["enabled"]) == 1
        for r in conn.execute(
            "SELECT category_id,enabled FROM category_preferences WHERE kind=?", (kind,)
        )
    }
    names = {}
    for cat in categories or []:
        name = safe_text(cat.get("category_name")).strip()
        cid = safe_text(cat.get("category_id")).strip()
        if not cid or not name:
            continue
        code = detect_country(name)
        if country_enabled.get(code, False) and category_enabled.get(cid, False):
            names[cid] = name
    return names


def current_enabled_category_names(conn):
    out = {"vod": set(), "series": set()}
    for row in conn.execute("""
        SELECT a.kind,a.name
        FROM available_categories a
        JOIN country_preferences cp
          ON cp.country_code=a.country_code AND cp.enabled=1
        JOIN category_preferences p
          ON p.kind=a.kind AND p.category_id=a.category_id AND p.enabled=1
        WHERE a.active=1
    """):
        out.setdefault(row["kind"], set()).add(normalize_category_name(row["name"]))
    return out


def enabled_country_summary(conn, lang=None):
    lang = normalize_ui_language(lang or get_ui_language(conn))
    rows = conn.execute("""
        SELECT country_code FROM country_preferences
        WHERE enabled=1 ORDER BY country_code
    """).fetchall()
    codes = [safe_text(r["country_code"]) for r in rows]
    labels = [country_label(c, lang) for c in codes]
    return codes, labels


def settings_ui_summary(conn):
    """Résumé léger renvoyé après un Enregistrer AJAX des paramètres."""
    lang = get_ui_language(conn)
    _, labels = enabled_country_summary(conn, lang)
    rows = conn.execute("""
        SELECT a.kind,
               COALESCE(p.enabled,0) AS category_enabled,
               COALESCE(cp.enabled,0) AS country_enabled
        FROM available_categories a
        LEFT JOIN category_preferences p
          ON p.kind=a.kind AND p.category_id=a.category_id
        LEFT JOIN country_preferences cp
          ON cp.country_code=a.country_code
        WHERE a.active=1
    """).fetchall()
    vod_count = sum(
        1 for r in rows
        if safe_text(r["kind"]) == "vod"
        and int(r["category_enabled"]) == 1
        and int(r["country_enabled"]) == 1
    )
    series_count = sum(
        1 for r in rows
        if safe_text(r["kind"]) == "series"
        and int(r["category_enabled"]) == 1
        and int(r["country_enabled"]) == 1
    )
    return {
        "countries": labels,
        "country_display": ", ".join(labels) if labels else ui_text(lang, "Aucun pays", "No country"),
        "ui_language": lang,
        "vod_categories": vod_count,
        "series_categories": series_count,
        "backup_settings": get_backup_settings(conn),
        "scan_settings": get_scan_settings(conn),
        "email_enabled": get_email_settings(conn).get("enabled", False),
    }


def effective_enabled_categories(conn):
    """Retourne les (kind, category_id) réellement surveillés à cet instant."""
    return {
        (safe_text(r["kind"]), safe_text(r["category_id"]))
        for r in conn.execute("""
            SELECT a.kind,a.category_id
            FROM available_categories a
            JOIN country_preferences cp
              ON cp.country_code=a.country_code AND cp.enabled=1
            JOIN category_preferences p
              ON p.kind=a.kind AND p.category_id=a.category_id AND p.enabled=1
            WHERE a.active=1
        """)
    }


def pending_baseline_category_ids(conn, kind):
    return {
        safe_text(r["category_id"])
        for r in conn.execute("""
            SELECT a.category_id
            FROM available_categories a
            JOIN country_preferences cp
              ON cp.country_code=a.country_code AND cp.enabled=1
            JOIN category_preferences p
              ON p.kind=a.kind AND p.category_id=a.category_id AND p.enabled=1
            WHERE a.kind=? AND a.active=1 AND p.baseline_pending=1
        """, (kind,))
    }


def clear_pending_category_baselines(conn, kind, category_ids):
    ids = {safe_text(x) for x in category_ids if safe_text(x)}
    if not ids:
        return
    conn.executemany("""
        UPDATE category_preferences
        SET baseline_pending=0
        WHERE kind=? AND category_id=?
    """, [(kind, cid) for cid in ids])


def reset_country_baseline(conn, country_code):
    """Recrée la référence des catégories actuellement surveillées d'une zone.

    Le scan suivant absorbera le catalogue courant sans créer de faux événements.
    Les événements déjà présents pour les catégories de cette zone sont retirés afin
    qu'une ancienne activation (avant l'ajout de la baseline) puisse être nettoyée.
    """
    code = safe_text(country_code).strip().upper()
    if not code:
        return {"categories": 0, "events_deleted": 0}

    rows = conn.execute("""
        SELECT a.kind,a.category_id,a.name
        FROM available_categories a
        JOIN country_preferences cp
          ON cp.country_code=a.country_code AND cp.enabled=1
        JOIN category_preferences p
          ON p.kind=a.kind AND p.category_id=a.category_id AND p.enabled=1
        WHERE a.country_code=? AND a.active=1
    """, (code,)).fetchall()

    if not rows:
        return {"categories": 0, "events_deleted": 0}

    now = iso_now()
    conn.executemany("""
        UPDATE category_preferences
        SET baseline_pending=1, updated_at=?
        WHERE kind=? AND category_id=?
    """, [
        (now, safe_text(r["kind"]), safe_text(r["category_id"]))
        for r in rows
    ])

    # Nettoie tous les événements déjà mémorisés pour cette zone, y compris
    # ceux d'une catégorie qui a été surveillée auparavant mais qui ne l'est
    # plus aujourd'hui. C'est important lors d'une recréation manuelle de la
    # référence : l'historique de la zone doit repartir proprement.
    #
    # On privilégie la détection du préfixe pays/zone directement dans la
    # catégorie de l'événement (ex. |IT|, [IT], IT -). Pour les événements de
    # catégorie/renommage où ce champ peut être vide, on vérifie aussi le titre
    # et les deux côtés éventuels du sous-titre.
    event_rows = conn.execute("SELECT event_key,category,title,subtitle FROM events").fetchall()
    event_keys = []
    for e in event_rows:
        candidates = [safe_text(e["category"]), safe_text(e["title"])]
        candidates.extend(safe_text(e["subtitle"]).split("→"))
        if any(detect_country(x) == code for x in candidates if safe_text(x).strip()):
            event_keys.append(safe_text(e["event_key"]))

    if event_keys:
        conn.executemany("DELETE FROM email_digest_queue WHERE event_key=?", [(k,) for k in event_keys])
        conn.executemany("DELETE FROM events WHERE event_key=?", [(k,) for k in event_keys])

    set_meta(conn, "last_manual_baseline_country", code)
    set_meta(conn, "last_manual_baseline_requested_at", now)
    conn.commit()
    return {"categories": len(rows), "events_deleted": len(event_keys)}


def save_category_settings(conn, form):
    now = iso_now()
    save_backup_settings(conn, form)
    _, scan_schedule_changed = save_scan_settings(conn, form)
    _, email_schedule_changed = save_email_settings(conn, form)
    selected_countries = set(form.get("countries", []))
    selected_vod = set(form.get("vod_categories", []))
    selected_series = set(form.get("series_categories", []))

    before_enabled = effective_enabled_categories(conn)

    active_category_count = conn.execute(
        "SELECT COUNT(*) AS n FROM available_categories WHERE active=1"
    ).fetchone()["n"]

    if int(active_category_count) > 0:
        for row in conn.execute("SELECT DISTINCT country_code FROM available_categories WHERE active=1"):
            code = safe_text(row["country_code"])
            conn.execute("""
                INSERT INTO country_preferences(country_code,enabled,updated_at)
                VALUES(?,?,?)
                ON CONFLICT(country_code) DO UPDATE SET
                    enabled=excluded.enabled, updated_at=excluded.updated_at
            """, (code, 1 if code in selected_countries else 0, now))

        for row in conn.execute("SELECT kind,category_id FROM available_categories WHERE active=1"):
            kind = safe_text(row["kind"])
            cid = safe_text(row["category_id"])
            selected = selected_vod if kind == "vod" else selected_series
            conn.execute("""
                INSERT INTO category_preferences(kind,category_id,enabled,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(kind,category_id) DO UPDATE SET
                    enabled=excluded.enabled, updated_at=excluded.updated_at
            """, (kind, cid, 1 if cid in selected else 0, now))
    else:
        print(
            "[WARN] Enregistrement Paramètres sans catalogue actif : "
            "sélections pays/catégories existantes conservées.",
            flush=True
        )

    # Compare l'état réellement surveillé avant/après Enregistrer. Une transition
    # désactivé -> activé reçoit une baseline au prochain scan. Une catégorie
    # désactivée perd son éventuel marqueur en attente.
    after_enabled = effective_enabled_categories(conn)
    newly_enabled = after_enabled - before_enabled

    conn.execute("UPDATE category_preferences SET baseline_pending=0 WHERE enabled=0")
    for kind, cid in newly_enabled:
        conn.execute("""
            UPDATE category_preferences
            SET baseline_pending=1
            WHERE kind=? AND category_id=?
        """, (kind, cid))

    conn.commit()
    # Réveiller le scheduler uniquement APRES le commit garantit qu'il relit
    # la nouvelle périodicité et non l'ancienne valeur encore visible avant
    # validation de la transaction.
    if scan_schedule_changed:
        SCAN_WAKE.set()
    if email_schedule_changed:
        EMAIL_WAKE.set()


def item_category_ids(item):
    out = set()
    cid = item.get("category_id")
    if cid is not None:
        out.add(safe_text(cid))
    cids = item.get("category_ids")
    if isinstance(cids, list):
        out.update(safe_text(x) for x in cids)
    elif cids not in (None, ""):
        out.add(safe_text(cids))
    return out


def selected_item_category_ids(item, category_map):
    return item_category_ids(item) & set(category_map.keys())


def item_is_activation_baseline(item, category_map, pending_category_ids):
    """Vrai si l'élément n'arrive que via des catégories tout juste activées."""
    matched = selected_item_category_ids(item, category_map)
    return bool(matched) and matched.issubset(set(pending_category_ids))


def fetch_items_global_or_by_category(action, category_map):
    try:
        data = api(action)
        if isinstance(data, list):
            return data
    except Exception:
        pass

    merged = {}
    for cid in category_map:
        data = api(action, category_id=cid)
        if isinstance(data, list):
            for item in data:
                iid = safe_text(item.get("stream_id") or item.get("series_id") or item.get("id"))
                if iid:
                    merged[iid] = item
        time.sleep(0.15)
    return list(merged.values())

def category_name_for(item, category_map):
    for cid in item_category_ids(item):
        if cid in category_map:
            return category_map[cid]
    return ""

def add_event(conn, event_key, kind, item_id, title, subtitle="", category="",
              provider_added=None, detected_at=None):
    cur = conn.execute("""
        INSERT OR IGNORE INTO events(
            event_key,kind,item_id,title,subtitle,category,detected_at,provider_added
        ) VALUES(?,?,?,?,?,?,?,?)
    """, (
        event_key, kind, safe_text(item_id), safe_text(title), safe_text(subtitle),
        safe_text(category), detected_at or iso_now(),
        safe_text(provider_added) if provider_added is not None else None
    ))
    return cur.rowcount == 1

def event_key_transition(prefix, item_id):
    # Une transition (suppression/renommage) peut arriver plusieurs fois dans la vie
    # du même élément, donc la date fait partie de la clé.
    return f"{prefix}:{item_id}:{iso_now()}"

def sync_categories(conn, kind, current_map, category_baseline, now, provider_ids=None, baseline_pending_ids=None):
    present_ids = set(current_map.keys())
    baseline_pending_ids = set(baseline_pending_ids or [])
    confirm = max(1, int(CFG.get("deletion_confirmation_scans", 2)))

    for cid, name in current_map.items():
        row = conn.execute("""
            SELECT * FROM categories WHERE kind=? AND category_id=?
        """, (kind, cid)).fetchone()

        if row is None:
            conn.execute("""
                INSERT INTO categories(
                    kind,category_id,name,first_seen,last_seen,active,missing_count
                ) VALUES(?,?,?,?,?,1,0)
            """, (kind, cid, name, now, now))

            if category_baseline and cid not in baseline_pending_ids:
                label = "Nouvelle catégorie Films" if kind == "vod" else "Nouvelle catégorie Séries"
                add_event(
                    conn,
                    f"category:{kind}:{cid}",
                    f"{kind}_category",
                    cid,
                    name,
                    label,
                    name,
                    None,
                    now
                )
        else:
            old_name = safe_text(row["name"])
            was_active = int(row["active"]) == 1

            if old_name != name and was_active:
                label = "Catégorie Films renommée" if kind == "vod" else "Catégorie Séries renommée"
                add_event(
                    conn,
                    event_key_transition(f"{kind}_category_renamed", cid),
                    f"{kind}_category_renamed",
                    cid,
                    name,
                    f"{old_name} → {name}",
                    name,
                    None,
                    now
                )

            conn.execute("""
                UPDATE categories
                SET name=?,last_seen=?,active=1,missing_count=0
                WHERE kind=? AND category_id=?
            """, (name, now, kind, cid))

    # Suppression confirmée après N scans successifs où la catégorie a disparu.
    old_rows = conn.execute("""
        SELECT * FROM categories WHERE kind=? AND active=1
    """, (kind,)).fetchall()

    for row in old_rows:
        cid = safe_text(row["category_id"])
        if cid in present_ids:
            continue

        if provider_ids is not None and cid in provider_ids:
            conn.execute("""
                UPDATE categories SET active=0,missing_count=0
                WHERE kind=? AND category_id=?
            """, (kind, cid))
            continue

        new_missing = int(row["missing_count"]) + 1
        if new_missing >= confirm:
            label = "Catégorie Films supprimée" if kind == "vod" else "Catégorie Séries supprimée"
            add_event(
                conn,
                event_key_transition(f"{kind}_category_removed", cid),
                f"{kind}_category_removed",
                cid,
                row["name"],
                label,
                row["name"],
                None,
                now
            )
            conn.execute("""
                UPDATE categories SET active=0,missing_count=? WHERE kind=? AND category_id=?
            """, (new_missing, kind, cid))
        else:
            conn.execute("""
                UPDATE categories SET missing_count=? WHERE kind=? AND category_id=?
            """, (new_missing, kind, cid))

def sync_missing_items(conn, table, current_ids, now, kind, monitored_categories=None):
    confirm = max(1, int(CFG.get("deletion_confirmation_scans", 2)))
    rows = conn.execute(f"SELECT * FROM {table} WHERE active=1").fetchall()

    monitored_norm = None
    if monitored_categories is not None:
        monitored_norm = {normalize_category_name(x) for x in monitored_categories}

    for row in rows:
        iid = safe_text(row["id"])
        if iid in current_ids:
            continue
        if monitored_norm is not None and normalize_category_name(row["category"]) not in monitored_norm:
            continue

        new_missing = int(row["missing_count"]) + 1
        if new_missing >= confirm:
            if kind == "movie":
                event_kind = "movie_removed"
                subtitle = "Film supprimé du catalogue fournisseur"
            else:
                event_kind = "series_removed"
                subtitle = "Série supprimée du catalogue fournisseur"

            add_event(
                conn,
                event_key_transition(event_kind, iid),
                event_kind,
                iid,
                row["name"],
                subtitle,
                row["category"],
                None,
                now
            )
            conn.execute(
                f"UPDATE {table} SET active=0,missing_count=? WHERE id=?",
                (new_missing, iid)
            )
        else:
            conn.execute(
                f"UPDATE {table} SET missing_count=? WHERE id=?",
                (new_missing, iid)
            )

def normalize_episode_rows(series_id, info):
    rows = []
    eps = info.get("episodes") if isinstance(info, dict) else {}
    if not isinstance(eps, dict):
        return rows

    for season_key, season_eps in eps.items():
        if not isinstance(season_eps, list):
            continue

        for ep in season_eps:
            if not isinstance(ep, dict):
                continue

            season = ep.get("season")
            if season is None:
                season = season_key
            try:
                season_i = int(season)
            except Exception:
                season_i = 0

            try:
                epnum = int(ep.get("episode_num") or 0)
            except Exception:
                epnum = 0

            title = safe_text(ep.get("title"))
            eid = safe_text(ep.get("id"))
            if not eid:
                eid = f"{season_i}:{epnum}:{title}"

            added = ep.get("added")
            if added in (None, "") and isinstance(ep.get("info"), dict):
                added = ep["info"].get("added")

            rows.append({
                "series_id": safe_text(series_id),
                "episode_id": eid,
                "season": season_i,
                "episode_num": epnum,
                "title": title,
                "provider_added": safe_text(added) if added not in (None, "") else None,
            })
    return rows

def process_pending_series(conn, scan_errors=None, monitored_categories=None):
    max_fetch = int(CFG["max_series_detail_fetches_per_run"])
    rows = conn.execute("""
        SELECT * FROM series
        WHERE pending=1 AND active=1
        ORDER BY is_new DESC, COALESCE(pending_since, first_seen) ASC
    """).fetchall()

    if monitored_categories is not None:
        monitored_norm = {normalize_category_name(x) for x in monitored_categories}
        rows = [r for r in rows if normalize_category_name(r["category"]) in monitored_norm]
    rows = rows[:max_fetch]

    processed = 0

    for s in rows:
        sid = s["id"]
        try:
            info = api("get_series_info", series_id=sid)
            current_eps = normalize_episode_rows(sid, info if isinstance(info, dict) else {})
            current_ids = {e["episode_id"] for e in current_eps}

            # Episode Identity V1 : si seul l'ID fournisseur change alors que
            # SxxExx reste unique, on réassocie avant de calculer ajouts/suppressions.
            reassociate_episode_ids(conn, sid, current_eps, iso_now())

            old_rows = conn.execute("""
                SELECT * FROM episodes WHERE series_id=?
            """, (sid,)).fetchall()
            old_ids = {r["episode_id"] for r in old_rows}

            # Nouveaux épisodes
            if not int(s["is_new"]):
                if old_ids:
                    new_rows = [e for e in current_eps if e["episode_id"] not in old_ids]
                else:
                    since = s["pending_since"]
                    try:
                        since_dt = datetime.fromisoformat(since) if since else None
                        if since_dt and since_dt.tzinfo is None:
                            since_dt = since_dt.replace(tzinfo=timezone.utc)
                    except Exception:
                        since_dt = None

                    new_rows = []
                    if since_dt:
                        # Petite marge pour éviter de perdre un épisode ajouté
                        # juste avant le scan précédent mais dont le changement
                        # de série n'est visible qu'au scan suivant.
                        episode_cutoff = since_dt - timedelta(minutes=10)
                        for e in current_eps:
                            added_dt = parse_epoch(e["provider_added"])
                            if added_dt and added_dt >= episode_cutoff:
                                new_rows.append(e)

                for e in new_rows:
                    code = f"S{int(e['season']):02d}E{int(e['episode_num']):02d}"
                    subtitle = code + (f" · {e['title']}" if e["title"] else "")
                    add_event(
                        conn,
                        f"episode:{sid}:{e['episode_id']}",
                        "episode",
                        sid,
                        s["name"],
                        subtitle,
                        s["category"],
                        e["provider_added"],
                    )

            # Épisodes retirés : uniquement si on avait déjà un état détaillé connu.
            if old_ids:
                for old in old_rows:
                    if old["episode_id"] not in current_ids:
                        code = f"S{int(old['season'] or 0):02d}E{int(old['episode_num'] or 0):02d}"
                        subtitle = code + (f" · {old['title']}" if old["title"] else "")
                        add_event(
                            conn,
                            event_key_transition(
                                "episode_removed",
                                f"{sid}:{old['episode_id']}"
                            ),
                            "episode_removed",
                            sid,
                            s["name"],
                            subtitle,
                            s["category"],
                            old["provider_added"],
                        )
                        conn.execute("""
                            DELETE FROM episodes
                            WHERE series_id=? AND episode_id=?
                        """, (sid, old["episode_id"]))

            # Mise à jour état courant
            for e in current_eps:
                conn.execute("""
                    INSERT INTO episodes(
                        series_id,episode_id,season,episode_num,title,provider_added
                    ) VALUES(?,?,?,?,?,?)
                    ON CONFLICT(series_id,episode_id) DO UPDATE SET
                        season=excluded.season,
                        episode_num=excluded.episode_num,
                        title=excluded.title,
                        provider_added=COALESCE(excluded.provider_added,episodes.provider_added)
                """, (
                    e["series_id"], e["episode_id"], e["season"],
                    e["episode_num"], e["title"], e["provider_added"]
                ))

            conn.execute("""
                UPDATE series SET
                    fetched_last_modified=seen_last_modified,
                    pending=0,
                    pending_since=NULL,
                    is_new=0,
                    retry_count=0
                WHERE id=?
            """, (sid,))
            conn.commit()
            processed += 1

        except Exception as e:
            conn.execute("""
                UPDATE series SET retry_count=retry_count+1 WHERE id=?
            """, (sid,))
            conn.commit()
            message = f"Détail série {sid} non récupéré : {type(e).__name__}: {e}"
            if scan_errors is not None:
                add_scan_error(scan_errors, message)
            print(f"[WARN] {message}", flush=True)

        time.sleep(float(CFG["series_fetch_delay_seconds"]))

    return processed

def sync_once():
    started = iso_now()
    scan_errors = []

    with LOCK:
        with db() as conn:
            deleted = cleanup_old_events(conn)
            conn.commit()

            if deleted:
                print(
                    f"[OK] Rétention : {deleted} ancienne(s) nouveauté(s) supprimée(s).",
                    flush=True
                )

            # Entretien léger quotidien : rétention longue des éléments techniques
            # et VACUUM uniquement si un volume significatif est réellement récupérable.
            run_db_maintenance(conn)

            baseline = get_meta(conn, "baseline_complete", "0") == "1"
            category_baseline = get_meta(conn, "category_baseline_complete", "0") == "1"
            previous_success = get_meta(conn, "last_success", started)

            try:
                vod_categories = api("get_vod_categories")
                series_categories = api("get_series_categories")
                vod_categories = vod_categories if isinstance(vod_categories, list) else []
                series_categories = series_categories if isinstance(series_categories, list) else []

                now = iso_now()
                vod_catalog_ok = sync_available_categories(conn, "vod", vod_categories, now)
                series_catalog_ok = sync_available_categories(conn, "series", series_categories, now)

                # Au démarrage d'une VM, le réseau ou le fournisseur peut répondre
                # quelques secondes trop tôt avec une liste vide. Dans ce cas, on
                # réutilise le dernier catalogue connu en base au lieu de faire
                # disparaître les pays/catégories de l'interface.
                if not vod_catalog_ok:
                    vod_categories = last_known_available_categories(conn, "vod")
                if not series_catalog_ok:
                    series_categories = last_known_available_categories(conn, "series")
                conn.commit()

                if not vod_categories and not series_categories:
                    raise RuntimeError(
                        "Catalogue VOD et Séries indisponible : aucun état précédent à réutiliser"
                    )

                selected_vod = selected_category_map(conn, "vod", vod_categories)
                selected_series = selected_category_map(conn, "series", series_categories)
                pending_vod_baselines = pending_baseline_category_ids(conn, "vod")
                pending_series_baselines = pending_baseline_category_ids(conn, "series")

                vod_all = fetch_items_global_or_by_category("get_vod_streams", selected_vod)
                series_all = fetch_items_global_or_by_category("get_series", selected_series)

                vod_items = [x for x in vod_all if item_category_ids(x) & set(selected_vod.keys())]
                series_items = [x for x in series_all if item_category_ids(x) & set(selected_series.keys())]

                sync_categories(
                    conn, "vod", selected_vod, category_baseline, now,
                    provider_ids={safe_text(x.get("category_id")) for x in vod_categories},
                    baseline_pending_ids=pending_vod_baselines
                )
                sync_categories(
                    conn, "series", selected_series, category_baseline, now,
                    provider_ids={safe_text(x.get("category_id")) for x in series_categories},
                    baseline_pending_ids=pending_series_baselines
                )

                if not category_baseline:
                    set_meta(conn, "category_baseline_complete", "1")
                    set_meta(conn, "category_baseline_at", now)
                    print(
                        f"[OK] Baseline catégories créée: {len(selected_vod)} catégories Films, "
                        f"{len(selected_series)} catégories Séries.",
                        flush=True
                    )

                # Films présents
                current_movie_ids = set()
                monitored_vod_norm = {
                    normalize_category_name(x) for x in selected_vod.values()
                }
                # Important pour Movie Identity V1 : on connaît à l'avance tous
                # les IDs présents dans CE scan. Un ancien ID qui coexiste encore
                # avec le nouveau ne sera donc jamais fusionné automatiquement.
                provider_movie_ids = {
                    safe_text(x.get("stream_id") or x.get("id"))
                    for x in vod_items
                    if safe_text(x.get("stream_id") or x.get("id"))
                }

                for m in vod_items:
                    mid = safe_text(m.get("stream_id") or m.get("id"))
                    if not mid:
                        continue
                    current_movie_ids.add(mid)

                    name = safe_text(m.get("name")) or f"Film {mid}"
                    cat = category_name_for(m, selected_vod)
                    added = safe_text(m.get("added")) or None
                    identity = movie_identity_from_item(m, name)
                    activation_baseline = item_is_activation_baseline(
                        m, selected_vod, pending_vod_baselines
                    )

                    row = conn.execute("SELECT * FROM movies WHERE id=?", (mid,)).fetchone()

                    if row is None:
                        old_row = None
                        matched_by = None

                        # On ne fait cette recherche que lorsqu'une vraie nouveauté
                        # pourrait être annoncée. Le tout premier baseline et le
                        # baseline d'une catégorie nouvellement activée restent O(n).
                        if baseline and not activation_baseline:
                            old_row, matched_by = find_movie_reassociation_candidate(
                                conn,
                                mid,
                                identity,
                                cat,
                                provider_movie_ids,
                                monitored_vod_norm,
                            )

                        if old_row is not None:
                            reassociate_movie_id(
                                conn,
                                old_row,
                                mid,
                                name,
                                cat,
                                added,
                                identity,
                                now,
                                matched_by,
                            )
                            row = conn.execute(
                                "SELECT * FROM movies WHERE id=?", (mid,)
                            ).fetchone()
                        else:
                            conn.execute("""
                                INSERT INTO movies(
                                    id,name,category,provider_added,first_seen,last_seen,
                                    active,missing_count,normalized_name,year,tmdb_id,imdb_id
                                ) VALUES(?,?,?,?,?,?,1,0,?,?,?,?)
                            """, (
                                mid, name, cat, added, now, now,
                                identity.get("normalized_name"),
                                identity.get("year"),
                                identity.get("tmdb_id"),
                                identity.get("imdb_id"),
                            ))

                            if baseline and not activation_baseline:
                                add_event(
                                    conn, f"movie:{mid}", "movie", mid,
                                    name, "", cat, added, now
                                )

                    if row is not None:
                        old_category = safe_text(row["category"])

                        # Certains fournisseurs réutilisent un même stream_id.
                        # Si un film auparavant connu dans une catégorie non
                        # surveillée apparaît maintenant dans une catégorie
                        # surveillée, il s'agit bien d'une nouveauté pour
                        # notre périmètre de surveillance.
                        enters_monitored_scope = bool(
                            old_category
                            and normalize_category_name(old_category)
                                not in monitored_vod_norm
                        )

                        if baseline and not activation_baseline and enters_monitored_scope:
                            add_event(
                                conn,
                                event_key_transition("movie", mid),
                                "movie",
                                mid,
                                name,
                                "",
                                cat,
                                added,
                                now
                            )

                        conn.execute("""
                            UPDATE movies SET
                                name=?,category=?,
                                provider_added=COALESCE(?,provider_added),
                                normalized_name=?,
                                year=COALESCE(?,year),
                                tmdb_id=COALESCE(?,tmdb_id),
                                imdb_id=COALESCE(?,imdb_id),
                                last_seen=?,active=1,missing_count=0
                            WHERE id=?
                        """, (
                            name,
                            cat,
                            added,
                            identity.get("normalized_name"),
                            identity.get("year"),
                            identity.get("tmdb_id"),
                            identity.get("imdb_id"),
                            now,
                            mid,
                        ))

                # Séries présentes
                current_series_ids = set()
                missing_lm = 0
                provider_series_ids = {
                    safe_text(x.get("series_id") or x.get("id"))
                    for x in series_items
                    if safe_text(x.get("series_id") or x.get("id"))
                }

                for s in series_items:
                    sid = safe_text(s.get("series_id") or s.get("id"))
                    if not sid:
                        continue
                    current_series_ids.add(sid)

                    name = safe_text(s.get("name")) or f"Série {sid}"
                    cat = category_name_for(s, selected_series)
                    lm = safe_text(s.get("last_modified"))
                    identity = series_identity_from_item(s, name)

                    if not lm:
                        missing_lm += 1

                    row = conn.execute("SELECT * FROM series WHERE id=?", (sid,)).fetchone()
                    series_reassociated = False

                    activation_baseline = item_is_activation_baseline(
                        s, selected_series, pending_series_baselines
                    )

                    if row is None:
                        old_row = None
                        matched_by = None
                        if baseline and not activation_baseline:
                            old_row, matched_by = find_series_reassociation_candidate(
                                conn,
                                sid,
                                identity,
                                cat,
                                provider_series_ids,
                            )

                        if old_row is not None and reassociate_series_id(
                            conn,
                            old_row,
                            sid,
                            name,
                            cat,
                            lm,
                            identity,
                            now,
                            matched_by,
                        ):
                            row = conn.execute(
                                "SELECT * FROM series WHERE id=?", (sid,)
                            ).fetchone()
                            series_reassociated = True
                        else:
                            # Lors de l'activation d'une catégorie déjà remplie, la série
                            # courante devient simplement l'état de référence. On ne va
                            # pas chercher tous ses épisodes historiques : au prochain
                            # vrai changement, la logique habituelle reprendra la main.
                            if activation_baseline:
                                conn.execute("""
                                    INSERT INTO series(
                                        id,name,category,seen_last_modified,fetched_last_modified,
                                        first_seen,last_seen,pending,pending_since,is_new,retry_count,
                                        active,missing_count,normalized_name,year,tmdb_id
                                    ) VALUES(?,?,?,?,?,?,?,?,?,?,0,1,0,?,?,?)
                                """, (
                                    sid, name, cat, lm, lm, now, now,
                                    0, None, 0,
                                    identity.get("normalized_name"),
                                    identity.get("year"),
                                    identity.get("tmdb_id"),
                                ))
                            else:
                                conn.execute("""
                                    INSERT INTO series(
                                        id,name,category,seen_last_modified,fetched_last_modified,
                                        first_seen,last_seen,pending,pending_since,is_new,retry_count,
                                        active,missing_count,normalized_name,year,tmdb_id
                                    ) VALUES(?,?,?,?,?,?,?,?,?,?,0,1,0,?,?,?)
                                """, (
                                    sid, name, cat, lm, None, now, now,
                                    1 if baseline else 0,
                                    previous_success if baseline else None,
                                    1 if baseline else 0,
                                    identity.get("normalized_name"),
                                    identity.get("year"),
                                    identity.get("tmdb_id"),
                                ))

                                if baseline:
                                    add_event(
                                        conn, f"series:{sid}", "series", sid,
                                        name, "", cat, s.get("added"), now
                                    )
                            continue

                    # Série déjà connue, ou réassociée ci-dessus.
                    old_lm = safe_text(row["seen_last_modified"])
                    # Une réassociation de series_id force un contrôle détaillé :
                    # le panel peut avoir renuméroté aussi les episode_id sans
                    # modifier last_modified. Episode Identity V1 absorbera ce cas.
                    changed = series_reassociated or bool(lm and old_lm and lm != old_lm)

                    if activation_baseline:
                        # Réactivation d'une catégorie déjà suivie autrefois :
                        # l'ancien détail d'épisodes ne sert plus de baseline.
                        conn.execute("DELETE FROM episodes WHERE series_id=?", (sid,))
                        conn.execute("""
                            UPDATE series SET
                                name=?,category=?,seen_last_modified=?,
                                fetched_last_modified=?,last_seen=?,pending=0,
                                pending_since=NULL,is_new=0,retry_count=0,
                                active=1,missing_count=0,
                                normalized_name=?,year=COALESCE(?,year),tmdb_id=COALESCE(?,tmdb_id)
                            WHERE id=?
                        """, (
                            name, cat, lm, lm, now,
                            identity.get("normalized_name"),identity.get("year"),
                            identity.get("tmdb_id"),sid
                        ))
                    elif int(row["is_new"]):
                        # Une vraie nouvelle série pas encore détaillée doit rester
                        # en mode baseline épisodes jusqu'à son traitement.
                        conn.execute("""
                            UPDATE series SET
                                name=?,category=?,seen_last_modified=?,last_seen=?,
                                active=1,missing_count=0,
                                normalized_name=?,year=COALESCE(?,year),tmdb_id=COALESCE(?,tmdb_id)
                            WHERE id=?
                        """, (
                            name,cat,lm or old_lm,now,
                            identity.get("normalized_name"),identity.get("year"),
                            identity.get("tmdb_id"),sid
                        ))
                    elif changed:
                        conn.execute("""
                            UPDATE series SET
                                name=?,category=?,seen_last_modified=?,last_seen=?,
                                pending=1,
                                pending_since=COALESCE(pending_since,?),
                                is_new=0,active=1,missing_count=0,
                                normalized_name=?,year=COALESCE(?,year),tmdb_id=COALESCE(?,tmdb_id)
                            WHERE id=?
                        """, (
                            name,cat,lm,now,previous_success,
                            identity.get("normalized_name"),identity.get("year"),
                            identity.get("tmdb_id"),sid
                        ))
                    else:
                        conn.execute("""
                            UPDATE series SET
                                name=?,category=?,
                                seen_last_modified=CASE
                                    WHEN seen_last_modified IS NULL OR seen_last_modified='' THEN ?
                                    ELSE seen_last_modified
                                END,
                                last_seen=?,active=1,missing_count=0,
                                normalized_name=?,year=COALESCE(?,year),tmdb_id=COALESCE(?,tmdb_id)
                            WHERE id=?
                        """, (
                            name,cat,lm,now,
                            identity.get("normalized_name"),identity.get("year"),
                            identity.get("tmdb_id"),sid
                        ))

                # Les catégories nouvellement activées viennent maintenant d'être
                # absorbées comme état de référence. Aux scans suivants, leurs
                # ajouts seront donc de vraies nouveautés.
                clear_pending_category_baselines(conn, "vod", pending_vod_baselines)
                clear_pending_category_baselines(conn, "series", pending_series_baselines)

                # Suppressions confirmées après N scans consécutifs. Pendant le
                # tout premier scan d'une catégorie nouvellement activée, on ne
                # compare pas avec un ancien état : cela fait partie de la baseline.
                if baseline:
                    deletion_vod_categories = [
                        name for cid, name in selected_vod.items()
                        if cid not in pending_vod_baselines
                    ]
                    deletion_series_categories = [
                        name for cid, name in selected_series.items()
                        if cid not in pending_series_baselines
                    ]
                    sync_missing_items(
                        conn, "movies", current_movie_ids, now, "movie",
                        deletion_vod_categories
                    )
                    sync_missing_items(
                        conn, "series", current_series_ids, now, "series",
                        deletion_series_categories
                    )

                conn.commit()

                set_meta(conn, "vod_category_count", len(selected_vod))
                set_meta(conn, "series_category_count", len(selected_series))
                set_meta(conn, "movie_count", len(vod_items))
                set_meta(conn, "series_count", len(series_items))
                set_meta(conn, "series_missing_last_modified", missing_lm)
                set_meta(conn, "deletion_confirmation_scans",
                         CFG.get("deletion_confirmation_scans", 2))

                if not baseline:
                    set_meta(conn, "baseline_complete", "1")
                    set_meta(conn, "baseline_at", now)
                    print(
                        f"[OK] Baseline créée: {len(vod_items)} films, "
                        f"{len(series_items)} séries, aucune ancienne entrée signalée.",
                        flush=True
                    )
                else:
                    processed = process_pending_series(conn, scan_errors, selected_series.values())
                    pending = conn.execute("""
                        SELECT COUNT(*) AS n FROM series WHERE pending=1 AND active=1
                    """).fetchone()["n"]
                    set_meta(conn, "pending_series", pending)
                    set_meta(conn, "last_detail_fetch_count", processed)

                set_meta(conn, "last_success", now)
                set_meta(conn, "last_error", "")
                register_scan_success(conn)
                set_meta(
                    conn,
                    "last_sync_duration_seconds",
                    round((utc_now() - datetime.fromisoformat(started)).total_seconds(), 2)
                )
                conn.commit()

                # Tous les événements réellement créés pendant CE scan.
                new_events = conn.execute("""
                    SELECT * FROM events
                    WHERE detected_at >= ?
                    ORDER BY detected_at ASC
                """, (started,)).fetchall()

                # Le scan est terminé : remplace l'état d'erreur précédent.
                # Zéro erreur => la section repasse automatiquement à 0.
                publish_watcher_errors(scan_errors)

                print(
                    f"[OK] Scan terminé: {len(vod_items)} films, {len(series_items)} séries, "
                    f"{len(selected_vod)} catégories Films, {len(selected_series)} catégories Séries, "
                    f"{len(new_events)} changement(s).",
                    flush=True
                )

            except Exception as e:
                message = f"{type(e).__name__}: {e}"
                add_scan_error(scan_errors, message)
                publish_watcher_errors(scan_errors)
                set_meta(conn, "last_error", sanitize_watcher_error(message))
                set_meta(conn, "last_error_at", iso_now())
                conn.commit()
                print("[ERROR] " + traceback.format_exc(), flush=True)
                threading.Thread(
                    target=register_scan_failure, args=(message,), daemon=True
                ).start()
                return

    # Hors verrou DB : l'envoi email ne bloque pas les opérations SQLite.
    queue_email_notifications(new_events)

def fmt_dt(value):
    if not value:
        return "—"
    try:
        d = datetime.fromisoformat(value)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(TZ).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return safe_text(value)

def clean_display_title(title):
    if not title:
        return ""
    return re.sub(r"^\|[A-Za-z]{2}\|\s*", "", safe_text(title))

def fmt_dt_short(value):
    if not value:
        return "—"
    try:
        d = datetime.fromisoformat(value)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(TZ).strftime("%d/%m %H:%M")
    except Exception:
        return safe_text(value)

def render_page(days):
    days = days if days in (1, 7, 30) else 1

    # Les périodes suivent les jours civils locaux : aujourd'hui = depuis 00:00,
    # 7 jours = aujourd'hui + les 6 jours précédents, 30 jours = aujourd'hui
    # + les 29 jours précédents. Cela garantit au maximum 7/30 lignes de dates.
    now_local = datetime.now(TZ)
    start_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_local = start_today - timedelta(days=(days - 1))
    cutoff_iso = start_local.astimezone(timezone.utc).isoformat()

    with LOCK:
        with db() as conn:
            events = conn.execute("""
                SELECT * FROM events
                WHERE detected_at >= ?
                ORDER BY detected_at DESC
            """, (cutoff_iso,)).fetchall()

            meta = {
                r["key"]: r["value"]
                for r in conn.execute("SELECT * FROM meta")
            }

            last_update_row = conn.execute("""
                SELECT detected_at
                FROM events
                ORDER BY detected_at DESC
                LIMIT 1
            """).fetchone()

            last_update = (
                fmt_dt_short(last_update_row["detected_at"])
                if last_update_row else "—"
            )

            lang = normalize_ui_language(meta.get("ui_language", "fr"))

            enabled_category_names = current_enabled_category_names(conn)
            _, enabled_country_labels = enabled_country_summary(conn, lang)
            settings_rows = conn.execute("""
                SELECT a.kind,a.category_id,a.name,a.country_code,
                       COALESCE(p.enabled,0) AS category_enabled,
                       COALESCE(cp.enabled,0) AS country_enabled
                FROM available_categories a
                LEFT JOIN category_preferences p
                  ON p.kind=a.kind AND p.category_id=a.category_id
                LEFT JOIN country_preferences cp
                  ON cp.country_code=a.country_code
                WHERE a.active=1
                ORDER BY a.country_code,a.kind,UPPER(a.name)
            """).fetchall()
            backup_settings = get_backup_settings(conn)
            scan_settings = get_scan_settings(conn)
            email_settings = get_email_settings(conn)

            # Compteurs dynamiques : ils reflètent immédiatement les catégories
            # réellement cochées dans les pays/zones activés, sans attendre un scan.
            enabled_vod_category_count = sum(
                1 for r in settings_rows
                if safe_text(r["kind"]) == "vod"
                and int(r["category_enabled"]) == 1
                and int(r["country_enabled"]) == 1
            )
            enabled_series_category_count = sum(
                1 for r in settings_rows
                if safe_text(r["kind"]) == "series"
                and int(r["category_enabled"]) == 1
                and int(r["country_enabled"]) == 1
            )

    watcher_errors = get_watcher_errors()
    L = lambda fr, en: ui_text(lang, fr, en)

    vod_event_kinds = {
        "movie", "movie_removed",
        "vod_category", "vod_category_removed", "vod_category_renamed",
    }
    series_event_kinds = {
        "series", "series_removed", "episode", "episode_removed",
        "series_category", "series_category_removed", "series_category_renamed",
    }

    def event_is_ignored(e):
        kind = safe_text(e["kind"])
        selected = enabled_category_names.get("vod", set()) if kind in vod_event_kinds else (
            enabled_category_names.get("series", set()) if kind in series_event_kinds else set()
        )
        if not selected:
            return True
        candidates = [e["category"]]
        if "category" in kind:
            candidates.append(e["title"])
            candidates.extend(safe_text(e["subtitle"]).split("→"))
        return not any(
            normalize_category_name(x) in selected
            for x in candidates if safe_text(x).strip()
        )

    events = [e for e in events if not event_is_ignored(e)]

    def settings_modal():
        by_country = {}
        country_enabled = {}
        for r in settings_rows:
            code = safe_text(r["country_code"]) or "OTHER"
            country_enabled[code] = int(r["country_enabled"]) == 1
            by_country.setdefault(code, {"vod": [], "series": []})
            by_country[code][safe_text(r["kind"])].append(r)

        if not by_country:
            body = f'<div class="settings-empty">{L("Aucune catégorie détectée pour le moment. Attends la fin du premier scan.", "No category detected yet. Wait for the first scan to finish.")}</div>'
            tabs = ''
        else:
            ordered = sorted(by_country, key=lambda c: (c == "OTHER", country_label(c, lang).lower()))
            tabs_parts = []
            panels = []
            for index, code in enumerate(ordered):
                active = " active" if index == 0 else ""
                enabled = country_enabled.get(code, False)
                monitored = " monitored" if enabled else ""
                checked = " checked" if enabled else ""
                label = country_label(code, lang)
                total = len(by_country[code]["vod"]) + len(by_country[code]["series"])
                tabs_parts.append(
                    f'<button type="button" class="country-tab{active}{monitored}" data-country="{html.escape(code, quote=True)}">'
                    f'{html.escape(label)} <span>{total}</span></button>'
                )

                cols = []
                for kind, heading in (("vod", L("VOD / Films", "VOD / Movies")), ("series", L("Séries", "Series"))):
                    rows = by_country[code][kind]
                    items = []
                    field = "vod_categories" if kind == "vod" else "series_categories"
                    for r in rows:
                        cat_checked = " checked" if int(r["category_enabled"]) == 1 else ""
                        cid = html.escape(safe_text(r["category_id"]), quote=True)
                        name = html.escape(safe_text(r["name"]))
                        search = html.escape(safe_text(r["name"]).lower(), quote=True)
                        items.append(
                            f'<label class="category-option" data-cat-search="{search}">'
                            f'<input type="checkbox" name="{field}" value="{cid}"{cat_checked}> '
                            f'<span>{name}</span></label>'
                        )
                    if not items:
                        items = [f'<div class="settings-empty small">{L("Aucune catégorie.", "No category.")}</div>']
                    cols.append(
                        f'<div class="category-column" data-kind="{kind}">'
                        f'<div class="category-column-head"><b>{heading}</b>'
                        f'<span><button type="button" class="mini-select" data-action="all" data-kind="{kind}">{L("Tout", "All")}</button>'
                        f'<button type="button" class="mini-select" data-action="none" data-kind="{kind}">{L("Aucun", "None")}</button></span></div>'
                        f'<div class="category-list">{"".join(items)}</div></div>'
                    )

                panels.append(
                    f'<section class="country-panel{active}" data-country-panel="{html.escape(code, quote=True)}">'
                    f'<div class="country-enable">'
                    f'<label><input type="checkbox" name="countries" value="{html.escape(code, quote=True)}"{checked}> '
                    f'<strong>{L("Surveiller", "Monitor")} {html.escape(label)}</strong></label>'
                    f'<button type="button" class="baseline-reset-btn" data-baseline-country="{html.escape(code, quote=True)}" '
                    f'data-baseline-label="{html.escape(label, quote=True)}">↺ {L("Recréer la référence", "Rebuild baseline")}</button>'
                    f'</div>'
                    f'<div class="category-grid">{"".join(cols)}</div></section>'
                )

            tabs = ''.join(tabs_parts)
            body = ''.join(panels)

        return f'''
<div id="settingsModal" class="modal" aria-hidden="true">
  <div class="modal-card">
    <div class="modal-head">
      <div><div class="eyebrow">{L("Configuration", "Configuration")}</div><h2>⚙️ {L("Pays et catégories", "Countries and categories")}</h2></div>
      <button type="button" class="modal-close" id="closeSettings">×</button>
    </div>
    <form method="post" action="/settings" id="settingsForm">
      <input type="hidden" name="return_days" value="{days}">
      <div class="settings-tools">
        <input id="categorySearch" class="settings-search" type="search" placeholder="{L("Rechercher une catégorie…", "Search a category…")}" autocomplete="off">
        <div class="settings-hint">{L("Coche un pays puis les catégories VOD/Séries à surveiller.", "Select a country, then the VOD/Series categories to monitor.")}</div>
        <div class="baseline-warning">⚠️ {L(
            "Attention : « Recréer la référence » efface les nouveautés déjà mémorisées pour les catégories surveillées de cette zone. Au prochain scan, le catalogue courant deviendra la nouvelle référence.",
            "Warning: ‘Rebuild baseline’ clears the remembered changes for the monitored categories in this zone. On the next scan, the current catalogue will become the new baseline."
        )}</div>
      </div>
      <div class="settings-layout">
        <aside class="country-tabs">{tabs}</aside>
        <div class="country-content">{body}</div>
      </div>
      <section class="scan-settings">
        <div class="scan-settings-head">
          <div>
            <div class="eyebrow">{L("Surveillance", "Monitoring")}</div>
            <h3>🔄 {L("Périodicité du scan", "Scan interval")}</h3>
          </div>
          <button type="button" class="scan-now-btn" id="runScanNow">{L("Scanner maintenant", "Scan now")}</button>
        </div>
        <div class="scan-grid">
          <label>
            <span>{L("Fréquence", "Frequency")}</span>
            <select name="scan_interval_mode" id="scanIntervalMode">
              <option value="5"{" selected" if scan_settings["interval_minutes"] == 5 else ""}>{L("Toutes les 5 minutes", "Every 5 minutes")}</option>
              <option value="10"{" selected" if scan_settings["interval_minutes"] == 10 else ""}>{L("Toutes les 10 minutes", "Every 10 minutes")}</option>
              <option value="15"{" selected" if scan_settings["interval_minutes"] == 15 else ""}>{L("Toutes les 15 minutes", "Every 15 minutes")}</option>
              <option value="30"{" selected" if scan_settings["interval_minutes"] == 30 else ""}>{L("Toutes les 30 minutes", "Every 30 minutes")}</option>
              <option value="60"{" selected" if scan_settings["interval_minutes"] == 60 else ""}>{L("Toutes les heures", "Every hour")}</option>
              <option value="120"{" selected" if scan_settings["interval_minutes"] == 120 else ""}>{L("Toutes les 2 heures", "Every 2 hours")}</option>
              <option value="custom"{" selected" if scan_settings["interval_minutes"] not in (5,10,15,30,60,120) else ""}>{L("Personnalisée", "Custom")}</option>
            </select>
          </label>
          <label id="scanCustomWrap" class="{'scan-custom-visible' if scan_settings['interval_minutes'] not in (5,10,15,30,60,120) else 'scan-custom-hidden'}">
            <span>{L("Minutes (5 à 1440)", "Minutes (5 to 1440)")}</span>
            <input type="number" id="scanIntervalCustom" name="scan_interval_custom" min="5" max="1440" value="{scan_settings["interval_minutes"]}">
          </label>
        </div>
        <div class="scan-info">
          {L("Dernier scan", "Latest scan")} : <strong id="scanSettingsLast">—</strong> ·
          {L("Prochain", "Next")} : <strong id="scanSettingsNext">—</strong>.
          {L("Une modification de fréquence recalcule immédiatement le prochain passage.", "Changing the frequency immediately recalculates the next run.")}
        </div>
      </section>
      <section class="backup-settings">
        <div class="backup-settings-head">
          <div>
            <div class="eyebrow">{L("Base de données", "Database")}</div>
            <h3>💾 {L("Sauvegarde automatique", "Automatic backup")}</h3>
          </div>
          <button type="button" class="backup-now-btn" id="runBackupNow">{L("Sauvegarder maintenant", "Back up now")}</button>
        </div>
        <div class="backup-grid">
          <label class="backup-toggle">
            <input type="checkbox" name="backup_enabled" value="1"{" checked" if backup_settings["enabled"] else ""}>
            <span>{L("Activer la sauvegarde automatique", "Enable automatic backup")}</span>
          </label>
          <label>
            <span>{L("Fréquence", "Frequency")}</span>
            <select name="backup_frequency">
              <option value="daily"{" selected" if backup_settings["frequency"] == "daily" else ""}>{L("Tous les jours", "Every day")}</option>
              <option value="2days"{" selected" if backup_settings["frequency"] == "2days" else ""}>{L("Tous les 2 jours", "Every 2 days")}</option>
              <option value="weekly"{" selected" if backup_settings["frequency"] == "weekly" else ""}>{L("Toutes les semaines", "Every week")}</option>
            </select>
          </label>
          <label>
            <span>{L("Heure", "Time")}</span>
            <input type="time" name="backup_time" value="{html.escape(backup_settings["time"], quote=True)}">
          </label>
          <label>
            <span>{L("Conserver", "Keep")}</span>
            <div class="backup-keep"><input type="number" name="backup_keep" min="1" max="365" value="{backup_settings["keep"]}"><span>{L("sauvegardes", "backups")}</span></div>
          </label>
        </div>
        <div class="backup-info" id="backupSettingsInfo">
          {L("Dernière sauvegarde", "Latest backup")} : <strong class="system-value" id="backupSettingsDetail">{html.escape(backup["detail"])}</strong> ·
          {L("Taille", "Size")} : <strong class="system-value" id="backupSettingsLatestSize">{html.escape(backup["latest_size"])}</strong> ·
          <span class="system-value" id="backupSettingsCount">{html.escape(str(backup["count"]))}</span> {L("fichier(s) conservé(s)", "file(s) kept")} ·
          {L("Total", "Total")} : <strong class="system-value" id="backupSettingsTotalSize">{html.escape(backup["total_size"])}</strong>.
          {L("La sauvegarde utilise la fonction native SQLite, compatible avec le mode WAL.", "Backups use SQLite’s native backup function and are compatible with WAL mode.")}
        </div>
      </section>
      <section class="email-settings">
        <div class="email-settings-head">
          <div>
            <div class="eyebrow">{L("Alertes", "Alerts")}</div>
            <h3>✉️ {L("Notifications par email", "Email notifications")}</h3>
          </div>
          <button type="button" class="email-test-btn" id="testEmailBtn">{L("Envoyer un email de test", "Send test email")}</button>
        </div>
        <div class="email-grid">
          <label class="email-toggle">
            <input type="checkbox" name="email_enabled" value="1"{" checked" if email_settings["enabled"] else ""}>
            <span>{L("Activer les notifications", "Enable notifications")}</span>
          </label>
          <label>
            <span>{L("Fréquence d’envoi", "Send frequency")}</span>
            <select name="email_digest_hours" id="emailDigestHours" data-saved-value="{email_settings["digest_hours"]}">
              <option value="0"{" selected" if email_settings["digest_hours"] == 0 else ""}>{L("Immédiatement", "Immediately")}</option>
              <option value="1"{" selected" if email_settings["digest_hours"] == 1 else ""}>{L("Toutes les heures", "Every hour")}</option>
              <option value="2"{" selected" if email_settings["digest_hours"] == 2 else ""}>{L("Toutes les 2 heures", "Every 2 hours")}</option>
              <option value="3"{" selected" if email_settings["digest_hours"] == 3 else ""}>{L("Toutes les 3 heures", "Every 3 hours")}</option>
              <option value="6"{" selected" if email_settings["digest_hours"] == 6 else ""}>{L("Toutes les 6 heures", "Every 6 hours")}</option>
            </select>
          </label>
          <label>
            <span>{L("Serveur SMTP", "SMTP server")}</span>
            <input type="text" name="email_smtp_host" value="{html.escape(email_settings["smtp_host"], quote=True)}" placeholder="smtp.gmail.com" autocomplete="off">
          </label>
          <label>
            <span>Port</span>
            <input type="number" name="email_smtp_port" min="1" max="65535" value="{email_settings["smtp_port"]}">
          </label>
          <label>
            <span>{L("Sécurité", "Security")}</span>
            <select name="email_security">
              <option value="starttls"{" selected" if email_settings["security"] == "starttls" else ""}>STARTTLS</option>
              <option value="ssl"{" selected" if email_settings["security"] == "ssl" else ""}>SSL/TLS</option>
              <option value="none"{" selected" if email_settings["security"] == "none" else ""}>{L("Aucune", "None")}</option>
            </select>
          </label>
          <label>
            <span>{L("Utilisateur SMTP", "SMTP username")}</span>
            <input type="text" value="{L('Configuré via .env', 'Configured via .env') if email_settings.get('smtp_username_configured') else L('Non configuré dans .env', 'Not configured in .env')}" readonly>
          </label>
          <label>
            <span>{L("Mot de passe / mot de passe d’application", "Password / app password")}</span>
            <input type="text" value="{L('Configuré via .env', 'Configured via .env') if email_settings.get('smtp_password_configured') else L('Non configuré dans .env', 'Not configured in .env')}" readonly>
          </label>
          <label>
            <span>{L("Expéditeur", "Sender")}</span>
            <input type="email" name="email_from" value="{html.escape(email_settings["from_addr"], quote=True)}" placeholder="monadresse@gmail.com">
          </label>
          <label>
            <span>{L("Destinataire(s)", "Recipient(s)")}</span>
            <input type="text" name="email_to" value="{html.escape(email_settings["to_addr"], quote=True)}" placeholder="moi@gmail.com">
          </label>
        </div>
        <div class="email-events">
          <span>{L("Notifier pour :", "Notify for:")}</span>
          <label><input type="checkbox" name="email_notify_movies" value="1"{" checked" if email_settings["notify_movies"] else ""}> {L("Nouveaux films", "New movies")}</label>
          <label><input type="checkbox" name="email_notify_series" value="1"{" checked" if email_settings["notify_series"] else ""}> {L("Nouvelles séries", "New series")}</label>
          <label><input type="checkbox" name="email_notify_episodes" value="1"{" checked" if email_settings["notify_episodes"] else ""}> {L("Nouveaux épisodes", "New episodes")}</label>
          <label><input type="checkbox" name="email_notify_categories" value="1"{" checked" if email_settings["notify_categories"] else ""}> {L("Nouvelles catégories", "New categories")}</label>
          <label><input type="checkbox" name="email_notify_removals" value="1"{" checked" if email_settings["notify_removals"] else ""}> {L("Suppressions", "Removals")}</label>
          <label><input type="checkbox" name="email_notify_scan_errors" value="1"{" checked" if email_settings["notify_scan_errors"] else ""}> {L("Erreurs de scan", "Scan errors")}</label>
          <label><input type="checkbox" name="email_notify_backup_errors" value="1"{" checked" if email_settings["notify_backup_errors"] else ""}> {L("Échec de sauvegarde", "Backup failure")}</label>
        </div>
        <div class="email-info">
          {L("Les changements sont regroupés selon la fréquence choisie ; aucun email n’est envoyé si la période ne contient rien.", "Changes are grouped according to the selected frequency; no email is sent when the period contains no changes.")}
          {L("Les épisodes d’une même série sont regroupés dans le récapitulatif. Les erreurs de scan/sauvegarde restent immédiates.", "Episodes from the same series are grouped in the digest. Scan and backup errors remain immediate.")}
          {L("Les identifiants SMTP sont lus exclusivement depuis le fichier .env et ne sont jamais enregistrés dans SQLite.", "SMTP credentials are read exclusively from the .env file and are never stored in SQLite.")}
        </div>
      </section>
      <div class="modal-actions">
        <button type="button" class="secondary-btn" id="cancelSettings">{L("Annuler", "Cancel")}</button>
        <button type="submit" class="save-btn">{L("Enregistrer", "Save")}</button>
      </div>
    </form>
  </div>
</div>'''


    grouped = {}
    for e in events:
        grouped.setdefault(e["kind"], []).append(e)

    def count(*kinds):
        return sum(len(grouped.get(k, [])) for k in kinds)

    def local_dt(value):
        if not value:
            return None
        try:
            d = datetime.fromisoformat(value)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.astimezone(TZ)
        except Exception:
            return None

    scan_status = get_scan_status(lang)
    backup = get_backup_status(lang)

    try:
        db_size = f"{DB_PATH.stat().st_size / (1024 * 1024):.1f} MB"
    except Exception:
        db_size = "—"

    kind_labels = {
        "movie": ("film", "🎬"),
        "series": ("serie", "📺"),
        "episode": ("episode", "▶️"),
        "vod_category": ("categorie", "🗂️"),
        "series_category": ("categorie", "🗂️"),
        "movie_removed": ("suppression", "❌"),
        "series_removed": ("suppression", "❌"),
        "episode_removed": ("suppression", "🗑️"),
        "vod_category_removed": ("suppression", "❌"),
        "series_category_removed": ("suppression", "❌"),
        "vod_category_renamed": ("renommage", "✏️"),
        "series_category_renamed": ("renommage", "✏️"),
    }

    def day_info(dt):
        if not dt:
            return "unknown", L("Date inconnue", "Unknown date")
        today = datetime.now(TZ).date()
        event_day = dt.date()
        if event_day == today:
            label = L("Aujourd’hui", "Today")
        elif event_day == today - timedelta(days=1):
            label = L("Hier", "Yesterday")
        else:
            if lang == "en":
                months = (
                    "January", "February", "March", "April", "May", "June",
                    "July", "August", "September", "October", "November", "December"
                )
                label = f"{months[event_day.month - 1]} {event_day.day}"
            else:
                months = (
                    "janvier", "février", "mars", "avril", "mai", "juin",
                    "juillet", "août", "septembre", "octobre", "novembre", "décembre"
                )
                label = f"{event_day.day} {months[event_day.month - 1]}"
            if event_day.year != today.year:
                label += f" {event_day.year}"
        return event_day.isoformat(), label

    def render_items(rows):
        """Transforme des événements en cartes, en regroupant les épisodes par série/jour."""
        generated_subtitle_en = {
            "Nouvelle catégorie Films": "New movie category",
            "Nouvelle catégorie Séries": "New series category",
            "Catégorie Films renommée": "Movie category renamed",
            "Catégorie Séries renommée": "Series category renamed",
            "Catégorie Films supprimée": "Movie category removed",
            "Catégorie Séries supprimée": "Series category removed",
            "Film supprimé du catalogue fournisseur": "Movie removed from provider catalogue",
            "Série supprimée du catalogue fournisseur": "Series removed from provider catalogue",
        }
        episode_groups = {}
        for e in rows:
            if safe_text(e["kind"]) != "episode":
                continue
            dt = local_dt(e["detected_at"])
            day_key = dt.date().isoformat() if dt else ""
            series_key = safe_text(e["item_id"]) or safe_text(e["title"])
            episode_groups.setdefault((day_key, series_key), []).append(e)

        emitted_episode_groups = set()
        rendered = []

        for e in rows:
            dt = local_dt(e["detected_at"])
            kind = safe_text(e["kind"])

            if kind == "episode":
                day_key = dt.date().isoformat() if dt else ""
                series_key = safe_text(e["item_id"]) or safe_text(e["title"])
                key = (day_key, series_key)
                if key in emitted_episode_groups:
                    continue
                emitted_episode_groups.add(key)
                grouped_events = episode_groups.get(key, [e])
                episode_count = len(grouped_events)
                episode_word = L("épisode", "episode") if episode_count == 1 else L("épisodes", "episodes")
                title = html.escape(clean_display_title(e["title"] or ""))
                cat = html.escape(e["category"] or "")
                detected = html.escape(fmt_dt(e["detected_at"]))
                searchable = html.escape(
                    " ".join([
                        safe_text(e["title"]),
                        safe_text(e["category"]),
                        " ".join(safe_text(x["subtitle"]) for x in grouped_events),
                        "episode",
                    ]).lower(),
                    quote=True
                )
                meta_bits = [detected]
                if cat:
                    meta_bits.append(cat)
                card = (
                    f'<article class="event-card" data-filter="episode" data-event-count="{episode_count}" data-search="{searchable}">'
                    f'<div class="event-icon">▶️</div>'
                    f'<div class="event-main">'
                    f'<div class="event-title-row">'
                    f'<div class="event-title">{title}</div>'
                    f'<span class="event-badge add">+{episode_count} {episode_word}</span>'
                    f'</div>'
                    f'<div class="event-meta">{" · ".join(meta_bits)}</div>'
                    f'</div>'
                    f'</article>'
                )
                rendered.append({
                    "dt": dt,
                    "html": card,
                    "count": episode_count,
                    "filter": "episode",
                })
                continue

            filter_kind, emoji = kind_labels.get(kind, ("autre", "ℹ️"))
            title = html.escape(clean_display_title(e["title"] or ""))
            raw_subtitle = safe_text(e["subtitle"])
            if lang == "en" and raw_subtitle in generated_subtitle_en:
                raw_subtitle = generated_subtitle_en[raw_subtitle]
            subtitle = html.escape(raw_subtitle)
            cat = html.escape(e["category"] or "")
            detected = html.escape(fmt_dt(e["detected_at"]))
            searchable = html.escape(
                " ".join([
                    safe_text(e["title"]),
                    safe_text(e["subtitle"]),
                    safe_text(e["category"]),
                    kind,
                ]).lower(),
                quote=True
            )

            badge = ""
            if kind in ("movie", "series", "vod_category", "series_category"):
                badge = f'<span class="event-badge add">{L("Ajout", "Added")}</span>'
            elif "renamed" in kind:
                badge = f'<span class="event-badge rename">{L("Renommé", "Renamed")}</span>'
            elif "removed" in kind:
                badge = f'<span class="event-badge remove">{L("Supprimé", "Removed")}</span>'

            meta_bits = [detected]
            if cat and "category" not in kind:
                meta_bits.append(cat)

            card = (
                f'<article class="event-card" data-filter="{filter_kind}" data-event-count="1" data-search="{searchable}">'
                f'<div class="event-icon">{emoji}</div>'
                f'<div class="event-main">'
                f'<div class="event-title-row"><div class="event-title">{title}</div>{badge}</div>'
                f'{"<div class=\"event-subtitle\">"+subtitle+"</div>" if subtitle else ""}'
                f'<div class="event-meta">{" · ".join(meta_bits)}</div>'
                f'</div>'
                f'</article>'
            )
            rendered.append({
                "dt": dt,
                "html": card,
                "count": 1,
                "filter": filter_kind,
            })

        return rendered

    def cards(kinds):
        """Vue Aujourd'hui : liste directe à l'intérieur de chaque rubrique."""
        if isinstance(kinds, str):
            kinds = (kinds,)
        rows = [e for e in events if e["kind"] in kinds]
        if not rows:
            return f'<div class="empty-state">{L("Aucun changement sur cette période.", "No changes during this period.")}</div>'
        return "".join(item["html"] for item in render_items(rows))

    def day_breakdown(counts):
        labels = (
            ("film", L("film", "movie"), L("films", "movies")),
            ("serie", L("série", "series"), L("séries", "series")),
            ("episode", L("épisode", "episode"), L("épisodes", "episodes")),
            ("categorie", L("catégorie", "category"), L("catégories", "categories")),
            ("suppression", L("suppression", "removal"), L("suppressions", "removals")),
            ("renommage", L("renommage", "rename"), L("renommages", "renames")),
        )
        parts = []
        for key, singular, plural in labels:
            n = int(counts.get(key, 0) or 0)
            if n:
                label = singular if n == 1 else plural
                parts.append(
                    f'<span class="day-breakdown-number">{n}</span> '
                    f'{html.escape(label)}'
                )
        return " · ".join(parts)

    def history_by_day():
        """Vues 7/30 jours : au maximum une ligne par journée ayant des changements."""
        if not events:
            return f'<div class="empty-state history-empty">{L("Aucun changement sur cette période.", "No changes during this period.")}</div>'

        groups = []
        indexes = {}
        for item in render_items(events):
            day_key, day_label = day_info(item["dt"])
            if day_key not in indexes:
                indexes[day_key] = len(groups)
                groups.append({
                    "key": day_key,
                    "label": day_label,
                    "items": [],
                    "count": 0,
                    "counts": {},
                })
            group = groups[indexes[day_key]]
            group["items"].append(item["html"])
            group["count"] += int(item["count"])
            group["counts"][item["filter"]] = group["counts"].get(item["filter"], 0) + int(item["count"])

        out = []
        for group in groups:
            total = int(group["count"])
            total_word = L("changement", "change") if total == 1 else L("changements", "changes")
            breakdown = day_breakdown(group["counts"])
            out.append(
                f'<details class="day-group history-day" data-day="{html.escape(group["key"], quote=True)}">'
                f'<summary>'
                f'<span class="day-label">{html.escape(group["label"])}</span>'
                f'<span class="day-summary">'
                f'<span class="day-count">{total} {total_word}</span>'
                f'<span class="day-breakdown">{breakdown}</span>'
                f'</span>'
                f'</summary>'
                f'<div class="day-body">{"".join(group["items"])}</div>'
                f'</details>'
            )
        return "".join(out)

    def section(section_id, title, emoji, kinds, section_count, open_when_nonempty=False):
        # Ne pas afficher les sections sans changement.
        if not section_count:
            return ""

        open_attr = ""
        return (
            f'<details class="section" id="{section_id}"{open_attr}>'
            f'<summary>'
            f'<span class="summary-left"><span class="summary-icon">{emoji}</span>{title}</span>'
            f'<span class="summary-count">{section_count}</span>'
            f'</summary>'
            f'<div class="section-body">{cards(kinds)}</div>'
            f'</details>'
        )

    def watcher_errors_section():
        if not watcher_errors:
            body = f'<div class="empty-state">{L("Aucune erreur sur le dernier scan.", "No error on the latest scan.")}</div>'
        else:
            rows = []
            for item in reversed(watcher_errors):
                rows.append(
                    '<div class="watcher-error-line">'
                    f'<span class="watcher-error-time">{html.escape(fmt_dt(item.get("at")))}</span>'
                    f'<span>{html.escape(safe_text(item.get("message")))}</span>'
                    '</div>'
                )
            body = "".join(rows)

        return (
            '<details class="section watcher-errors">'
            '<summary>'
            f'<span class="summary-left"><span class="summary-icon">⚠️</span>{L("Erreurs de l’application", "Application errors")}</span>'
            f'<span class="summary-count">{len(watcher_errors)}</span>'
            '</summary>'
            f'<div class="section-body">{body}</div>'
            '</details>'
        )

    last_error = safe_text(meta.get("last_error", ""))
    api_ok = not bool(last_error)
    api_label = "API OK" if api_ok else L("API en erreur", "API error")
    api_class = "ok" if api_ok else "error"

    missing_lm = int(meta.get("series_missing_last_modified", "0") or 0)
    warnings = ""
    if missing_lm:
        warnings += (
            f'<div class="warning">⚠️ {missing_lm} {L("séries ne fournissent pas", "series do not provide")} '
            f'<code>last_modified</code>.</div>'
        )

    notif_status = L("Email activé", "Email enabled") if email_settings.get("enabled") else L("Désactivées", "Disabled")

    interval = safe_text(scan_status.get("interval_minutes", scan_settings.get("interval_minutes", 15)))
    duration = safe_text(meta.get("last_sync_duration_seconds", "—"))
    tabs = "".join(
        f'<a class="period-tab {"active" if days==d else ""}" href="/?days={d}">'
        f'{L("Aujourd’hui", "Today") if d==1 else str(d)+" "+L("jours", "days")}</a>'
        for d in (1, 7, 30)
    )

    total_changes = len(events)

    country_display = ", ".join(enabled_country_labels) if enabled_country_labels else L("Aucun pays", "No country")

    if days == 1:
        events_markup = "".join([
            section("films", L("Films", "Movies"), "🎬", "movie", count("movie")),
            section("series", L("Nouvelles séries", "New series"), "📺", "series", count("series")),
            section("episodes", L("Nouveaux épisodes", "New episodes"), "▶️", "episode", count("episode")),
            section("categories", L("Nouvelles catégories", "New categories"), "🗂️", ("vod_category", "series_category"), count("vod_category", "series_category")),
            section("renommages", L("Catégories renommées", "Renamed categories"), "✏️", ("vod_category_renamed", "series_category_renamed"), count("vod_category_renamed", "series_category_renamed")),
            section("suppressions", L("Suppressions", "Removals"), "❌", ("movie_removed", "series_removed", "episode_removed", "vod_category_removed", "series_category_removed"), count("movie_removed", "series_removed", "episode_removed", "vod_category_removed", "series_category_removed")),
        ])
    else:
        events_markup = history_by_day()

    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(APP_NAME)}</title>
<link rel="icon" type="image/png" sizes="64x64" href="/favicon.png?v={html.escape(APP_VERSION)}">
<link rel="apple-touch-icon" href="/app-logo.png?v={html.escape(APP_VERSION)}">
<script>
(() => {{
    try {{
        const savedTheme = localStorage.getItem("xtream-theme");
        if (savedTheme === "light" || savedTheme === "dark") {{
            document.documentElement.setAttribute("data-theme", savedTheme);
        }}
    }} catch (_) {{}}
}})();
</script>
<style>
:root {{
    color-scheme: dark;

    --bg: #080b11;
    --bg-glow: rgba(139,108,255,.09);
    --panel: #101620;
    --panel-2: #151d29;

    --line: #263244;
    --line-strong: #35455d;
    --line-medium: #304158;
    --modal-border: #2b3950;
    --settings-line: #27344a;
    --control-border: #34445e;
    --control-border-soft: #2c3b53;
    --category-border: #293850;
    --country-enable-border: #2d3b53;
    --country-enable-bg: #151f30;
    --category-head-bg: #131e2e;
    --mini-border: #354761;
    --mini-bg: #1a2639;
    --category-hover-bg: #172337;

    --text: #f4f7fb;
    --text-soft: #c8d1dd;
    --text-bright: #e8edf5;
    --strong-text: #ffffff;
    --muted: #8e9caf;
    --muted-2: #8fa2bd;
    --muted-3: #8295b0;
    --label: #9cafc7;

    --accent: #8b6cff;
    --accent-soft: rgba(139,108,255,.14);

    --good: #38c793;
    --good-soft: rgba(56,199,147,.13);
    --good-border: #39765f;
    --good-border-strong: #4c9b7a;
    --good-panel: #173429;
    --good-panel-muted: #132a22;
    --good-panel-active: #1b3b2f;
    --good-text: #a8e8cf;
    --good-text-soft: #b9efd9;
    --good-text-strong: #d8f7e9;
    --good-hover: #204537;

    --warn: #e8a44a;
    --warn-soft: rgba(232,164,74,.13);
    --warn-border: rgba(232,164,74,.35);
    --warn-text: #f0c987;

    --danger: #ef6a76;
    --danger-soft: rgba(239,106,118,.13);
    --danger-border: #87404a;
    --danger-panel: #351a20;
    --danger-text: #ffc3ca;

    --hero-bg: linear-gradient(180deg, #172233 0%, #0f1723 100%);
    --toolbar-bg: linear-gradient(180deg, #141e2c 0%, #0e151f 100%);
    --card-bg: linear-gradient(180deg, #1b2738 0%, #111a27 100%);
    --section-bg: linear-gradient(180deg, #182334 0%, #101824 100%);

    --glass-bg: rgba(255,255,255,.025);
    --day-bg: rgba(255,255,255,.018);
    --hover-bg-strong: rgba(255,255,255,.03);
    --code-bg: rgba(255,255,255,.05);
    --hairline: rgba(255,255,255,.055);
    --hairline-strong: rgba(255,255,255,.06);

    --shadow-card: 0 12px 32px rgba(0,0,0,.38);
    --shadow-stat: 0 12px 30px rgba(0,0,0,.40);
    --shadow-strong: 0 16px 42px rgba(0,0,0,.42);
    --shadow-inset: inset 0 1px 0 rgba(255,255,255,.07);
    --shadow-inset-soft: inset 0 1px 0 rgba(255,255,255,.055);
    --toast-shadow: 0 12px 35px rgba(0,0,0,.35);
    --modal-shadow: 0 24px 80px rgba(0,0,0,.45);

    --overlay: rgba(4,8,15,.78);
    --settings-bg: #0f1724;
    --settings-alt: #0c1420;
    --settings-section: #111d2c;
    --settings-section-2: #101a28;
    --settings-section-3: #111b29;

    --button-bg: #182235;
    --button-hover: #22304a;
    --button-text: #e9eef7;
    --secondary-bg: #172235;
    --secondary-text: #d9e2ef;
    --input-bg: #111b2b;
    --toggle-text: #dce5f1;
    --active-tab-bg: #1d2b43;
    --active-tab-text: #ffffff;

    --baseline-warning-border: #7d3b45;
    --baseline-warning-bg: #2a171b;
    --baseline-warning-text: #ff9da8;
    --baseline-reset-border: #7a5a2f;
    --baseline-reset-bg: #2a2115;
    --baseline-reset-text: #f1c981;
    --baseline-reset-hover: #382a18;

    --primary-border: #4d78ff;
    --primary-bg: #2e5ee8;
    --primary-text: #ffffff;

    --info-border: #3e6fa8;
    --info-bg: #172d47;
    --info-text: #b9dcff;
    --info-hover: #203d5f;

    --email-test-border: #4c6488;
    --email-test-bg: #18263b;
    --email-test-text: #d7e5fa;
    --email-test-hover: #22344f;

    --country-tab-text: #aebbd0;
    --mini-text: #cad5e5;
    --info-strong: #cbd7e6;
    --email-events-text: #c9d6e7;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
    margin: 0;
    background:
        radial-gradient(circle at top right, var(--bg-glow), transparent 28rem),
        var(--bg);
    color: var(--text);
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
button, input {{ font: inherit; }}
.wrap {{
    width: min(1180px, calc(100% - 28px));
    margin: 0 auto;
    padding: 24px 0 42px;
}}
.hero {{
    background: var(--hero-bg);
    border: 1px solid var(--line-strong);
    border-radius: 22px;
    padding: 20px;
    box-shadow:
        var(--shadow-strong),
        var(--shadow-inset);
}}
.hero-top {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 18px;
    flex-wrap: wrap;
}}
.eyebrow {{
    color: var(--muted);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: .12em;
    font-weight: 800;
}}
h1 {{
    margin: 4px 0 6px;
    font-size: clamp(25px, 5vw, 36px);
    letter-spacing: -.035em;
}}

.app-title {{
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}}
.app-logo {{
    width: clamp(36px, 5vw, 42px);
    height: clamp(36px, 5vw, 42px);
    display: block;
    flex: 0 0 auto;
    border-radius: 11px;
    box-shadow: 0 5px 16px rgba(0,0,0,.25);
}}
.version-badge {{
    display: inline-flex;
    vertical-align: middle;
    margin-left: 8px;
    padding: 3px 7px;
    border: 1px solid var(--line);
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent);
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .02em;
}}
.toast-stack {{
    position:fixed;
    top:18px;
    right:18px;
    z-index:20000;
    display:flex;
    flex-direction:column;
    gap:9px;
    width:min(380px, calc(100vw - 36px));
    pointer-events:none;
}}
.toast {{
    padding:12px 14px;
    border-radius:11px;
    border:1px solid var(--line);
    background:var(--panel-2);
    color:var(--text);
    box-shadow:var(--toast-shadow);
    font-size:13px;
    font-weight:700;
    line-height:1.4;
    opacity:0;
    transform:translateY(-8px);
    transition:opacity .18s ease, transform .18s ease;
}}
.toast.show {{
    opacity:1;
    transform:translateY(0);
}}
.toast.success {{
    border-color:var(--good-border);
    background:var(--good-panel);
    color:var(--good-text-soft);
}}
.toast.error {{
    border-color:var(--danger-border);
    background:var(--danger-panel);
    color:var(--danger-text);
}}
.hero-sub {{
    color: var(--muted);
    font-size: 13px;
}}
.status-pill,
.language-switch,
.theme-switch {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 34px;
    padding: 0 10px;
    border: 1px solid var(--line);
    border-radius: 999px;
    background: var(--glass-bg);
    color: var(--text);
    font-size: 12px;
    font-weight: 800;
    line-height: 1;
    white-space: nowrap;
}}
.status-dot {{
    width: 8px;
    height: 8px;
    border-radius: 99px;
    background: var(--good);
    box-shadow: 0 0 0 4px var(--good-soft);
}}
.status-pill.error .status-dot {{
    background: var(--danger);
    box-shadow: 0 0 0 4px var(--danger-soft);
}}
.status-pill.warn .status-dot {{
    background: var(--warn);
    box-shadow: 0 0 0 4px var(--warn-soft);
}}
.quick-status {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0,1fr));
    gap: 9px;
    margin-top: 18px;
}}
.quick {{
    background: var(--card-bg);
    border: 1px solid var(--line-strong);
    border-radius: 14px;
    padding: 11px 12px;
    box-shadow:
        var(--shadow-card),
        var(--shadow-inset);
}}
.quick-label {{
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .06em;
}}
.quick-value {{
    margin-top: 3px;
    font-weight: 780;
    font-size: 14px;
}}
.hero-actions {{
    display:flex;
    gap:8px;
    flex-wrap:wrap;
    align-items:center;
    justify-content:flex-end;
}}
.language-switch select {{
    border:0;
    outline:0;
    background:transparent;
    color:var(--text);
    font:inherit;
    font-size:12px;
    font-weight:800;
    cursor:pointer;
}}
.language-switch select option {{
    background:var(--panel);
    color:var(--text);
}}
.toolbar {{
    position: sticky;
    top: 0;
    z-index: 10;
    margin: 16px 0;
    padding: 10px;
    display: flex;
    flex-direction:column;
    gap: 9px;
    background: var(--toolbar-bg);
    backdrop-filter: blur(16px);
    border: 1px solid var(--line-medium);
    border-radius: 16px;
    box-shadow:
        var(--shadow-card),
        var(--shadow-inset-soft);
}}
.toolbar-main {{
    width:100%;
    display:flex;
    align-items:center;
    gap:9px;
}}
.toolbar-actions {{
    display:grid;
    grid-template-columns:repeat(2,max-content);
    align-items:center;
    gap:7px;
    flex:0 0 auto;
}}
.toolbar-actions .scan-now-btn,
.toolbar-actions .backup-now-btn {{
    padding:10px 13px;
    border-radius:10px;
}}
.periods, .filters {{
    display: flex;
    gap: 7px;
    flex-wrap: wrap;
}}
.filters {{ width:100%; }}
.period-tab, .filter-btn, .refresh-btn {{
    border: 1px solid var(--line);
    background: var(--panel);
    color: var(--text);
    text-decoration: none;
    border-radius: 10px;
    padding: 8px 11px;
    cursor: pointer;
    font-size: 13px;
}}
.period-tab.active, .filter-btn.active {{
    border-color: var(--accent);
    background: var(--accent-soft);
}}
.search {{
    min-width: 220px;
    flex: 1 1 260px;
    border: 1px solid var(--line);
    background: var(--panel);
    color: var(--text);
    border-radius: 10px;
    padding: 9px 12px;
    outline: none;
}}
.search:focus {{
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
}}
.refresh-btn {{
    margin-left: 0;
}}
.stats {{
    display: grid;
    grid-template-columns: repeat(6, minmax(0,1fr));
    gap: 10px;
    margin-bottom: 16px;
}}
.stat {{
    display: flex;
    flex-direction: column;
    background: var(--card-bg);
    border: 1px solid var(--line-strong);
    border-radius: 14px;
    padding: 11px 12px;
    min-width: 0;
    box-shadow:
        var(--shadow-card),
        var(--shadow-inset);
}}
.stat strong {{
    order: 2;
    display: block;
    margin-top: 3px;
    font-size: 22px;
    line-height: 1.05;
    font-weight: 780;
}}
.stat span {{
    order: 1;
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .06em;
}}
.section {{
    background: var(--section-bg);
    border: 1px solid var(--line-medium);
    border-radius: 17px;
    margin-bottom: 12px;
    overflow: hidden;
    box-shadow:
        var(--shadow-card),
        var(--shadow-inset-soft);
}}
.section > summary {{
    list-style: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 14px 15px;
    font-weight: 800;
    user-select: none;
}}
.section > summary::-webkit-details-marker {{ display: none; }}
.summary-left {{
    display: flex;
    align-items: center;
    gap: 9px;
}}
.summary-icon {{ font-size: 19px; }}
.summary-count {{
    min-width: 30px;
    text-align: center;
    border: 1px solid var(--line);
    background: var(--panel-2);
    border-radius: 999px;
    padding: 3px 8px;
    font-size: 12px;
}}
.section-body {{
    padding: 0 10px 10px;
}}
.day-divider {{
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--muted);
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: .07em;
    padding: 12px 5px 7px;
}}
.day-divider::after {{
    content: "";
    height: 1px;
    background: var(--line);
    flex: 1;
}}
.day-group {{
    border: 1px solid var(--hairline);
    border-radius: 12px;
    background: var(--day-bg);
    margin: 8px 0;
    overflow: hidden;
}}
.day-group > summary {{
    list-style: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 11px 12px;
    user-select: none;
    transition: background .15s ease;
}}
.day-group > summary:hover {{ background: var(--hover-bg-strong); }}
.day-group > summary::-webkit-details-marker {{ display: none; }}
.day-label {{
    font-weight: 800;
    color: var(--text-bright);
}}
.day-label::before {{
    content: "›";
    display: inline-block;
    margin-right: 9px;
    color: var(--muted);
    transition: transform .15s ease;
}}
.day-group[open] .day-label::before {{ transform: rotate(90deg); }}
.day-summary {{
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 9px;
    min-width: 0;
}}
.day-count {{
    color: var(--text);
    border: 1px solid var(--line);
    background: var(--panel-2);
    border-radius: 999px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 800;
    white-space: nowrap;
}}
.day-breakdown {{
    color: var(--muted);
    font-size: 12px;
    white-space: nowrap;
}}
.day-breakdown-number {{
    color:var(--strong-text);
    font-weight:800;
}}
.day-body {{
    border-top: 1px solid var(--hairline);
    padding: 5px 4px 6px;
}}
.event-card {{
    display: flex;
    align-items: flex-start;
    gap: 11px;
    padding: 11px;
    border-radius: 12px;
    transition: background .15s ease, transform .15s ease;
}}
.event-card:hover {{
    background: var(--glass-bg);
    transform: translateY(-1px);
}}
.event-card.hidden {{ display: none; }}
.event-icon {{
    width: 34px;
    height: 34px;
    border-radius: 10px;
    display: grid;
    place-items: center;
    background: var(--panel-2);
    flex: 0 0 auto;
}}
.event-main {{
    min-width: 0;
    flex: 1;
}}
.event-title-row {{
    display: flex;
    gap: 8px;
    justify-content: space-between;
    align-items: flex-start;
}}
.event-title {{
    font-weight: 780;
    overflow-wrap: anywhere;
}}
.event-subtitle {{
    color: var(--text-soft);
    font-size: 13px;
    margin-top: 3px;
}}
.event-meta {{
    color: var(--muted);
    font-size: 11px;
    margin-top: 5px;
}}
.event-badge {{
    flex: 0 0 auto;
    border-radius: 999px;
    padding: 3px 7px;
    font-size: 10px;
    font-weight: 850;
    text-transform: uppercase;
    letter-spacing: .04em;
}}
.event-badge.add {{
    color: var(--good);
    background: var(--good-soft);
}}
.event-badge.rename {{
    color: var(--warn);
    background: var(--warn-soft);
}}
.event-badge.remove {{
    color: var(--danger);
    background: var(--danger-soft);
}}
.empty-state {{
    color: var(--muted);
    font-size: 13px;
    padding: 10px 5px 13px;
}}
.system {{
    margin-top: 17px;
    display: grid;
    grid-template-columns: 1.2fr .8fr;
    gap: 10px;
}}
.system-value {{
    color:var(--strong-text);
    font-weight:700;
}}
.system-card {{
    background: var(--card-bg);
    border: 1px solid var(--line-strong);
    border-radius: 16px;
    padding: 14px;
    color: var(--muted);
    font-size: 12px;
    line-height: 1.75;
    box-shadow:
        var(--shadow-stat),
        var(--shadow-inset);
}}
.system-card b {{ color: var(--text); }}
.watcher-errors {{
    margin-top: 12px;
}}
.watcher-error-line {{
    display: grid;
    grid-template-columns: 125px 1fr;
    gap: 12px;
    padding: 10px 2px;
    border-bottom: 1px solid var(--hairline-strong);
    color: var(--warn-text);
    font-size: 12px;
    line-height: 1.45;
}}
.watcher-error-line:last-child {{
    border-bottom: 0;
}}
.watcher-error-time {{
    color: var(--muted);
    white-space: nowrap;
}}

.warning {{
    margin-top: 10px;
    padding: 11px;
    border: 1px solid var(--warn-border);
    border-radius: 12px;
    background: var(--warn-soft);
    color: var(--warn-text);
    font-size: 12px;
}}
code {{
    background: var(--code-bg);
    padding: 2px 5px;
    border-radius: 5px;
}}
.no-results {{
    display: none;
    text-align: center;
    color: var(--muted);
    padding: 26px 10px;
}}
.no-results.visible {{ display: block; }}

@media (max-width: 980px) {{
    .stats {{ grid-template-columns: repeat(3, minmax(0,1fr)); }}
    .quick-status {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
}}
@media (max-width: 680px) {{
    .wrap {{ width: min(100% - 18px, 1180px); padding-top: 10px; }}
    .hero {{ border-radius: 17px; padding: 16px; }}
    .stats {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
    .toolbar {{ position: static; }}
    .toolbar-main {{ flex-wrap:wrap; }}
    .periods {{ order:1; }}
    .toolbar-actions {{ order:2; margin-left:auto; }}
    .search {{ order:3; flex-basis:100%; width:100%; }}
    .hero-actions {{ justify-content:flex-start; }}
    .system {{ grid-template-columns: 1fr; }}
    .event-title-row {{ display: block; }}
    .event-badge {{ display: inline-block; margin-top: 5px; }}
    .day-group > summary {{ align-items: flex-start; }}
    .day-summary {{ align-items: flex-end; flex-direction: column; gap: 4px; }}
    .day-breakdown {{ white-space: normal; text-align: right; }}
}}


/* --- Paramètres Pays / Catégories --- */
.settings-btn, .refresh-btn {{
    border:1px solid var(--modal-border);
    background:var(--button-bg);
    color:var(--button-text);
    border-radius:10px;
    padding:10px 13px;
    cursor:pointer;
    font-weight:700;
    font-size:13px;
}}
.settings-btn:hover, .refresh-btn:hover {{
    background:var(--button-hover);
}}
.modal {{ position:fixed; inset:0; background:var(--overlay); display:none; align-items:center; justify-content:center; padding:20px; z-index:9999; }}
.modal.open {{ display:flex; }}
.modal-card {{ width:min(1120px,96vw); max-height:92vh; overflow:hidden; background:var(--settings-bg); border:1px solid var(--modal-border); border-radius:18px; box-shadow:var(--modal-shadow); display:flex; flex-direction:column; }}
.modal-head {{ display:flex; justify-content:space-between; align-items:center; padding:18px 20px; border-bottom:1px solid var(--settings-line); }}
.modal-head h2 {{ margin:2px 0 0; font-size:22px; }}
.modal-close {{ width:38px; height:38px; border-radius:10px; border:1px solid var(--control-border); background:var(--button-bg); color:var(--strong-text); font-size:25px; cursor:pointer; }}
#settingsForm {{ display:flex; flex-direction:column; flex:1 1 auto; min-height:0; overflow-y:auto; overscroll-behavior:contain; }}
.settings-tools {{ padding:14px 20px; border-bottom:1px solid var(--settings-line); }}
.settings-search {{ width:100%; padding:11px 12px; border-radius:10px; border:1px solid var(--control-border); background:var(--input-bg); color:var(--strong-text); }}
.settings-hint {{ color:var(--muted-2); font-size:12px; margin-top:8px; }}
.baseline-warning {{
    margin-top:9px;
    padding:9px 11px;
    border:1px solid var(--baseline-warning-border);
    border-radius:9px;
    background:var(--baseline-warning-bg);
    color:var(--baseline-warning-text);
    font-size:12px;
    font-weight:700;
    line-height:1.45;
}}
.settings-layout {{ display:grid; grid-template-columns:220px 1fr; min-height:460px; overflow:hidden; flex:0 0 auto; }}
.country-tabs {{ padding:10px; border-right:1px solid var(--settings-line); overflow:auto; background:var(--settings-alt); }}
.country-tab {{ width:100%; display:flex; justify-content:space-between; gap:8px; border:0; background:transparent; color:var(--country-tab-text); padding:10px 11px; border-radius:9px; cursor:pointer; text-align:left; }}
.country-tab span {{ opacity:.6; }}
.country-tab.active {{ background:var(--active-tab-bg); color:var(--active-tab-text); }}
.country-tab.monitored {{
    background:var(--good-panel-muted);
    color:var(--good-text);
    box-shadow:inset 0 0 0 1px var(--good-border);
}}
.country-tab.monitored span {{
    color:var(--good-text);
    opacity:.9;
}}
.country-tab.monitored.active {{
    background:var(--good-panel-active);
    color:var(--good-text-strong);
    box-shadow:inset 0 0 0 1px var(--good-border-strong);
}}
.country-content {{ overflow:auto; padding:16px 18px 22px; }}
.country-panel {{ display:none; }}
.country-panel.active {{ display:block; }}
.country-enable {{ margin-bottom:14px; padding:12px 14px; background:var(--country-enable-bg); border:1px solid var(--country-enable-border); border-radius:10px; display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
.baseline-reset-btn {{ border:1px solid var(--baseline-reset-border); background:var(--baseline-reset-bg); color:var(--baseline-reset-text); border-radius:8px; padding:7px 10px; font-size:12px; font-weight:700; cursor:pointer; }}
.baseline-reset-btn:hover {{ background:var(--baseline-reset-hover); }}
.category-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
.category-column {{ min-width:0; border:1px solid var(--category-border); border-radius:12px; overflow:hidden; }}
.category-column-head {{ display:flex; justify-content:space-between; align-items:center; gap:8px; padding:11px 12px; background:var(--category-head-bg); }}
.category-column-head span {{ display:flex; gap:5px; }}
.mini-select {{ border:1px solid var(--mini-border); background:var(--mini-bg); color:var(--mini-text); border-radius:7px; padding:4px 7px; font-size:11px; cursor:pointer; }}
.category-list {{ max-height:360px; overflow:auto; padding:8px; }}
.category-option {{ display:flex; gap:8px; align-items:flex-start; padding:7px 8px; border-radius:7px; cursor:pointer; font-size:13px; }}
.category-option:hover {{ background:var(--category-hover-bg); }}
.category-option input {{ margin-top:2px; }}
.settings-empty {{ color:var(--muted-2); padding:20px; }}
.settings-empty.small {{ padding:10px; font-size:12px; }}
.modal-actions {{ display:flex; justify-content:flex-end; gap:9px; padding:14px 20px; border-top:1px solid var(--settings-line); background:var(--settings-alt); position:sticky; bottom:0; z-index:20; flex-shrink:0; }}
.secondary-btn,.save-btn {{ border-radius:9px; padding:10px 14px; font-weight:700; cursor:pointer; }}
.secondary-btn {{ border:1px solid var(--control-border); background:var(--secondary-bg); color:var(--secondary-text); }}
.save-btn {{ border:1px solid var(--primary-border); background:var(--primary-bg); color:var(--primary-text); }}
.scan-settings {{ padding:16px 20px; border-top:1px solid var(--settings-line); background:var(--settings-section); }}
.scan-settings-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; flex-wrap:wrap; }}
.scan-settings-head h3 {{ margin:2px 0 0; font-size:17px; }}
.scan-now-btn {{ border:1px solid var(--info-border); background:var(--info-bg); color:var(--info-text); border-radius:9px; padding:8px 11px; font-weight:750; cursor:pointer; }}
.scan-now-btn:hover {{ background:var(--info-hover); }}
.scan-now-btn:disabled {{ opacity:.65; cursor:default; }}
.scan-grid {{ display:grid; grid-template-columns:1.4fr 1fr; gap:10px; align-items:end; }}
.scan-grid label {{ display:flex; flex-direction:column; gap:6px; color:var(--label); font-size:12px; }}
.scan-grid select,.scan-grid input[type="number"] {{ width:100%; border:1px solid var(--control-border); background:var(--input-bg); color:var(--strong-text); border-radius:9px; padding:9px 10px; }}
.scan-custom-hidden {{ display:none !important; }}
.scan-custom-visible {{ display:flex !important; }}
.scan-info {{ color:var(--muted-3); font-size:11px; margin-top:10px; line-height:1.5; }}
.scan-info strong {{ color:var(--info-strong); }}
.backup-settings {{ padding:16px 20px; border-top:1px solid var(--settings-line); background:var(--settings-section-2); }}
.backup-settings-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; flex-wrap:wrap; }}
.backup-settings-head h3 {{ margin:2px 0 0; font-size:17px; }}
.backup-now-btn {{ border:1px solid var(--good-border); background:var(--good-panel); color:var(--good-text); border-radius:9px; padding:8px 11px; font-weight:750; cursor:pointer; }}
.backup-now-btn:hover {{ background:var(--good-hover); }}
.backup-grid {{ display:grid; grid-template-columns:1.4fr 1fr .8fr 1fr; gap:10px; align-items:end; }}
.backup-grid label {{ display:flex; flex-direction:column; gap:6px; color:var(--label); font-size:12px; }}
.backup-grid select,.backup-grid input[type="time"],.backup-grid input[type="number"] {{ width:100%; border:1px solid var(--control-border); background:var(--input-bg); color:var(--strong-text); border-radius:9px; padding:9px 10px; }}
.backup-toggle {{ flex-direction:row !important; align-items:center; gap:9px !important; min-height:39px; padding:9px 10px; border:1px solid var(--control-border-soft); border-radius:9px; background:var(--input-bg); color:var(--toggle-text) !important; }}
.backup-keep {{ display:flex; align-items:center; gap:7px; }}
.backup-keep span {{ white-space:nowrap; }}
.backup-info {{ color:var(--muted-3); font-size:11px; margin-top:10px; line-height:1.5; }}
.backup-info strong {{ color:var(--info-strong); }}
.email-settings {{ padding:16px 20px; border-top:1px solid var(--settings-line); background:var(--settings-section-3); }}
.email-settings-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; flex-wrap:wrap; }}
.email-settings-head h3 {{ margin:2px 0 0; font-size:17px; }}
.email-test-btn {{ border:1px solid var(--email-test-border); background:var(--email-test-bg); color:var(--email-test-text); border-radius:9px; padding:8px 11px; font-weight:750; cursor:pointer; }}
.email-test-btn:hover {{ background:var(--email-test-hover); }}
.email-grid {{ display:grid; grid-template-columns:1.25fr 1.25fr .55fr .85fr; gap:10px; align-items:end; }}
.email-grid label {{ display:flex; flex-direction:column; gap:6px; color:var(--label); font-size:12px; }}
.email-grid input,.email-grid select {{ width:100%; border:1px solid var(--control-border); background:var(--input-bg); color:var(--strong-text); border-radius:9px; padding:9px 10px; box-sizing:border-box; }}
.email-toggle {{ flex-direction:row !important; align-items:center; gap:9px !important; min-height:39px; padding:9px 10px; border:1px solid var(--control-border-soft); border-radius:9px; background:var(--input-bg); color:var(--toggle-text) !important; }}
.email-toggle input {{ width:auto !important; }}
.email-events {{ display:flex; gap:10px 16px; flex-wrap:wrap; margin-top:12px; padding:10px 12px; border:1px solid var(--control-border-soft); border-radius:9px; background:var(--settings-section-2); color:var(--email-events-text); font-size:12px; }}
.email-events > span {{ color:var(--muted-2); font-weight:700; width:100%; }}
.email-events label {{ display:flex; align-items:center; gap:6px; }}
.email-info {{ color:var(--muted-3); font-size:11px; margin-top:10px; line-height:1.5; }}
@media (max-width: 1050px) {{ .email-grid {{ grid-template-columns:1fr 1fr; }} }}
@media (max-width: 900px) {{ .backup-grid {{ grid-template-columns:1fr 1fr; }} .scan-grid {{ grid-template-columns:1fr 1fr; }} }}
@media (max-width: 760px) {{
  .settings-layout {{ grid-template-columns:1fr; min-height:520px; }}
  .country-tabs {{ display:flex; gap:6px; border-right:0; border-bottom:1px solid var(--settings-line); overflow:auto; }}
  .country-tab {{ width:auto; min-width:max-content; }}
  .category-grid {{ grid-template-columns:1fr; }}
  .backup-grid {{ grid-template-columns:1fr; }}
  .scan-grid {{ grid-template-columns:1fr; }}
  .email-grid {{ grid-template-columns:1fr; }}
}}
.theme-switch {{
    cursor: pointer;
}}

.theme-switch:hover {{
    border-color: var(--accent);
    background: var(--accent-soft);
}}

:root[data-theme="light"] {{
    color-scheme: light;

    --bg: #eef2f7;
    --bg-glow: rgba(111,80,232,.08);
    --panel: #ffffff;
    --panel-2: #f6f8fb;

    --line: #d6dee9;
    --line-strong: #c7d2df;
    --line-medium: #d2dae5;
    --modal-border: #cbd5e1;
    --settings-line: #d9e1eb;
    --control-border: #cbd5e1;
    --control-border-soft: #d6dee9;
    --category-border: #d7e0ea;
    --country-enable-border: #d7e0ea;
    --country-enable-bg: #ffffff;
    --category-head-bg: #f6f8fb;
    --mini-border: #cbd5e1;
    --mini-bg: #ffffff;
    --category-hover-bg: #eef3f9;

    --text: #172033;
    --text-soft: #44536a;
    --text-bright: #172033;
    --strong-text: #172033;
    --muted: #68758a;
    --muted-2: #718096;
    --muted-3: #718096;
    --label: #64748b;

    --accent: #6f50e8;
    --accent-soft: rgba(111,80,232,.10);

    --good: #16845f;
    --good-soft: rgba(22,132,95,.10);
    --good-border: #8dcbb2;
    --good-border-strong: #72b99d;
    --good-panel: #eef9f4;
    --good-panel-muted: #eef9f4;
    --good-panel-active: #e1f5eb;
    --good-text: #176a4c;
    --good-text-soft: #176a4c;
    --good-text-strong: #115b41;
    --good-hover: #d9f2e6;

    --warn: #ad6812;
    --warn-soft: rgba(173,104,18,.10);
    --warn-border: rgba(173,104,18,.28);
    --warn-text: #8c5a0b;

    --danger: #c13c4a;
    --danger-soft: rgba(193,60,74,.10);
    --danger-border: #e6a8ae;
    --danger-panel: #fff1f2;
    --danger-text: #a62f3b;

    --hero-bg: linear-gradient(180deg, #ffffff 0%, #f5f7fb 100%);
    --toolbar-bg: linear-gradient(180deg, #ffffff 0%, #f7f9fc 100%);
    --card-bg: linear-gradient(180deg, #ffffff 0%, #f7f9fc 100%);
    --section-bg: linear-gradient(180deg, #ffffff 0%, #f7f9fc 100%);

    --glass-bg: rgba(255,255,255,.72);
    --day-bg: rgba(15,23,42,.018);
    --hover-bg-strong: rgba(15,23,42,.05);
    --code-bg: #eef2f7;
    --hairline: rgba(15,23,42,.08);
    --hairline-strong: rgba(15,23,42,.10);

    --shadow-card: 0 12px 32px rgba(15,23,42,.08);
    --shadow-stat: 0 12px 30px rgba(15,23,42,.08);
    --shadow-strong: 0 16px 42px rgba(15,23,42,.10);
    --shadow-inset: inset 0 1px 0 rgba(255,255,255,.82);
    --shadow-inset-soft: inset 0 1px 0 rgba(255,255,255,.72);
    --toast-shadow: 0 12px 35px rgba(15,23,42,.14);
    --modal-shadow: 0 24px 80px rgba(15,23,42,.18);

    --overlay: rgba(15,23,42,.28);
    --settings-bg: #ffffff;
    --settings-alt: #f6f8fb;
    --settings-section: #f7f9fc;
    --settings-section-2: #f8fafc;
    --settings-section-3: #f8fafc;

    --button-bg: #ffffff;
    --button-hover: #f1f5f9;
    --button-text: #172033;
    --secondary-bg: #ffffff;
    --secondary-text: #172033;
    --input-bg: #ffffff;
    --toggle-text: #172033;
    --active-tab-bg: #ece8ff;
    --active-tab-text: #4d38c8;

    --baseline-warning-border: #efb4ba;
    --baseline-warning-bg: #fff1f2;
    --baseline-warning-text: #a62f3b;
    --baseline-reset-border: #e0ba7c;
    --baseline-reset-bg: #fff8e8;
    --baseline-reset-text: #8a5a10;
    --baseline-reset-hover: #fff1cf;

    --primary-border: #6f50e8;
    --primary-bg: #6f50e8;
    --primary-text: #ffffff;

    --info-border: #9fc0ef;
    --info-bg: #e8f1ff;
    --info-text: #204a87;
    --info-hover: #dceaff;

    --email-test-border: #b5c4dd;
    --email-test-bg: #eef3fb;
    --email-test-text: #334e75;
    --email-test-hover: #e2eaf6;

    --country-tab-text: #5f6f86;
    --mini-text: #44536a;
    --info-strong: #44536a;
    --email-events-text: #44536a;
}}

</style>
</head>
<body>
<div id="toastStack" class="toast-stack" aria-live="polite" aria-atomic="true"></div>
<div class="wrap">

<header class="hero">
    <div class="hero-top">
        <div>
            <div class="eyebrow">Monitoring Xtream · <span id="monitorCountryDisplay">{html.escape(country_display)}</span></div>
            <h1 class="app-title"><img class="app-logo" src="/app-logo.png?v={html.escape(APP_VERSION)}" alt="" aria-hidden="true"><span>{html.escape(APP_NAME)}</span><span class="version-badge">v{html.escape(APP_VERSION)}</span></h1>
            <div class="hero-sub">{total_changes} {L("changement(s) sur la période sélectionnée", "change(s) in the selected period")}</div>
        </div>
        <div class="hero-actions">
            <div class="status-pill {api_class}">
                <span class="status-dot"></span>
                {html.escape(api_label)}
            </div>
            <div class="status-pill {backup["class"]}" id="backupStatusPill" title="{html.escape(str(backup["count"]))} {L("sauvegarde(s) conservée(s)", "backup(s) kept")}">
                <span class="status-dot"></span>
                <span id="backupStatusText">{html.escape(backup["label"])} · {html.escape(backup["detail"])}</span>
            </div>
            <form method="post" action="/language" class="language-switch" title="{L("Langue de l’interface et des emails", "Interface and email language")}">
                <input type="hidden" name="return_days" value="{days}">
                <span aria-hidden="true" style="display:{'inline-flex' if lang == 'fr' else 'none'};align-items:center;">
                    <svg width="22" height="15" viewBox="0 0 30 20" style="border-radius:2px;display:block;">
                        <rect width="10" height="20" x="0" fill="#0055A4"/>
                        <rect width="10" height="20" x="10" fill="#FFFFFF"/>
                        <rect width="10" height="20" x="20" fill="#EF4135"/>
                    </svg>
                </span>
                <span aria-hidden="true" style="display:{'inline-flex' if lang == 'en' else 'none'};align-items:center;">
                    <svg width="22" height="15" viewBox="0 0 60 36" style="border-radius:2px;display:block;">
                        <rect width="60" height="36" fill="#012169"/>
                        <path d="M0 0L60 36M60 0L0 36" stroke="#FFFFFF" stroke-width="7"/>
                        <path d="M0 0L60 36M60 0L0 36" stroke="#C8102E" stroke-width="3"/>
                        <path d="M30 0V36M0 18H60" stroke="#FFFFFF" stroke-width="12"/>
                        <path d="M30 0V36M0 18H60" stroke="#C8102E" stroke-width="7"/>
                    </svg>
                </span>
                <select name="ui_language" aria-label="{L("Langue", "Language")}" onchange="this.form.submit()">
                    <option value="fr"{" selected" if lang == "fr" else ""}>FR</option>
                    <option value="en"{" selected" if lang == "en" else ""}>GB</option>
                </select>
            </form>

            <button type="button"
                    class="theme-switch"
                    id="themeSwitch"
                    title="{L("Changer de thème", "Change theme")}"
                    aria-label="{L("Changer de thème", "Change theme")}">
                <span id="themeSwitchIcon" aria-hidden="true">☀️</span>
                <span id="themeSwitchText">{L("Clair", "Light")}</span>
            </button>
        </div>
    </div>

    <div class="quick-status">
        <div class="quick">
            <div class="quick-label">{L("Dernier scan", "Latest scan")}</div>
            <div class="quick-value" id="lastScanValue">{html.escape(scan_status.get("last_detail", "—"))}</div>
        </div>
        <div class="quick">
            <div class="quick-label">{L("Prochain scan", "Next scan")}</div>
            <div class="quick-value" id="nextScanValue">≈ {html.escape(scan_status.get("next_detail", "—"))}</div>
        </div>
        <div class="quick">
            <div class="quick-label">{L("Durée", "Duration")}</div>
            <div class="quick-value">{html.escape(duration)} s</div>
        </div>
        <div class="quick">
            <div class="quick-label">{L("Dernière mise à jour", "Last update")}</div>
            <div class="quick-value">{html.escape(last_update)}</div>
        </div>
    </div>
</header>
<script>
(() => {{
    const root = document.documentElement;
    const button = document.getElementById("themeSwitch");
    const icon = document.getElementById("themeSwitchIcon");
    const text = document.getElementById("themeSwitchText");

    if (!button || !icon || !text) return;

    const lightLabel = "{L("Clair", "Light")}";
    const darkLabel = "{L("Sombre", "Dark")}";

    function updateThemeButton() {{
        const current = root.getAttribute("data-theme") === "light" ? "light" : "dark";

        if (current === "light") {{
            icon.textContent = "🌙";
            text.textContent = darkLabel;
        }} else {{
            icon.textContent = "☀️";
            text.textContent = lightLabel;
        }}
    }}

    button.addEventListener("click", () => {{
        const current = root.getAttribute("data-theme") === "light" ? "light" : "dark";
        const next = current === "light" ? "dark" : "light";

        root.setAttribute("data-theme", next);

        try {{
            localStorage.setItem("xtream-theme", next);
        }} catch (_) {{}}

        updateThemeButton();
    }});

    updateThemeButton();
}})();
</script>

<nav class="toolbar">
    <div class="toolbar-main">
        <div class="periods">{tabs}</div>

        <input id="searchInput" class="search"
               type="search"
               placeholder="{L("Rechercher un film, une série, un épisode…", "Search a movie, series or episode…")}"
               autocomplete="off">

        <div class="toolbar-actions">
            <button class="settings-btn" id="openSettings">⚙️ {L("Paramètres", "Settings")}</button>
            <button class="refresh-btn" onclick="location.reload()">
                <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:5px;">
                    <path d="M20 6v5h-5"/>
                    <path d="M4 18v-5h5"/>
                    <path d="M6.1 9a7 7 0 0 1 11.5-2.6L20 11"/>
                    <path d="M17.9 15a7 7 0 0 1-11.5 2.6L4 13"/>
                </svg>{L("Actualiser", "Refresh")}
            </button>
            <button type="button" class="scan-now-btn" id="runScanQuick">{L("Scanner maintenant", "Scan now")}</button>
            <button type="button" class="backup-now-btn" id="runBackupQuick">{L("Sauvegarder maintenant", "Back up now")}</button>
        </div>
    </div>

    <div class="filters">
        <button class="filter-btn active" data-filter="all">{L("Tout", "All")}</button>
        <button class="filter-btn" data-filter="film">{L("Films", "Movies")}</button>
        <button class="filter-btn" data-filter="serie">{L("Séries", "Series")}</button>
        <button class="filter-btn" data-filter="episode">{L("Épisodes", "Episodes")}</button>
        <button class="filter-btn" data-filter="categorie">{L("Catégories", "Categories")}</button>
        <button class="filter-btn" data-filter="suppression">{L("Suppressions", "Removals")}</button>
        <button class="filter-btn" data-filter="renommage">{L("Renommages", "Renames")}</button>
    </div>
</nav>

<section class="stats">
    <div class="stat"><strong>{count("movie")}</strong><span>{L("Nouveaux films", "New movies")}</span></div>
    <div class="stat"><strong>{count("series")}</strong><span>{L("Nouvelles séries", "New series")}</span></div>
    <div class="stat"><strong>{count("episode")}</strong><span>{L("Nouveaux épisodes", "New episodes")}</span></div>
    <div class="stat"><strong>{count("vod_category","series_category")}</strong><span>{L("Nouvelles catégories", "New categories")}</span></div>
    <div class="stat"><strong>{count("movie_removed","series_removed","episode_removed","vod_category_removed","series_category_removed")}</strong><span>{L("Suppressions", "Removals")}</span></div>
    <div class="stat"><strong>{count("vod_category_renamed","series_category_renamed")}</strong><span>{L("Renommages", "Renames")}</span></div>
</section>

<main id="events">
    {events_markup}
    <div id="noResults" class="no-results">{L("Aucun résultat avec ces filtres.", "No results with these filters.")}</div>
</main>

{watcher_errors_section()}

<section class="system">
    <div class="system-card">
        <b>{L("Catalogue suivi", "Monitored catalogue")}</b><br>
        <span class="system-value">{html.escape(meta.get("movie_count","—"))}</span> {L("films", "movies")} ·
        <span class="system-value">{html.escape(meta.get("series_count","—"))}</span> {L("séries", "series")}<br>
        {L("Pays", "Countries")} : <span class="system-value" id="catalogCountryDisplay">{html.escape(country_display)}</span><br>
        <span class="system-value" id="catalogVodCategoryCount">{enabled_vod_category_count}</span> {L("catégories Films", "Movie categories")} ·
        <span class="system-value" id="catalogSeriesCategoryCount">{enabled_series_category_count}</span> {L("catégories Séries", "Series categories")}
    </div>
    <div class="system-card">
        <b>{L("État de l’application", "Application status")}</b><br>
        {L("Scan automatique", "Automatic scan")} : <span class="system-value" id="scanSystemInterval">{html.escape(interval)}</span> min<br>
        {L("Notifications", "Notifications")} : <span class="system-value" id="notificationSystemStatus">{notif_status}</span><br>
        {L("Sauvegardes", "Backups")} : <span class="system-value" id="backupSystemCount">{html.escape(str(backup["count"]))}</span> {L("fichiers", "files")} ·
        <span class="system-value" id="backupSystemTotalSize">{html.escape(backup["total_size"])}</span><br>
        {L("Base de données", "Database")} : <span class="system-value">{db_size}</span>
    </div>
</section>

{warnings}

{settings_modal()}

</div>

<script>
const searchInput = document.getElementById('searchInput');
const filterButtons = [...document.querySelectorAll('.filter-btn')];
const cards = [...document.querySelectorAll('.event-card')];
const details = [...document.querySelectorAll('#events .section')];
const dayGroups = [...document.querySelectorAll('#events .day-group')];
const noResults = document.getElementById('noResults');
const UI_LANG = {json.dumps(lang, ensure_ascii=False)};
const TXT = {{
    change: {json.dumps(L('changement', 'change'), ensure_ascii=False)},
    changes: {json.dumps(L('changements', 'changes'), ensure_ascii=False)},
    movie: {json.dumps(L('film', 'movie'), ensure_ascii=False)},
    movies: {json.dumps(L('films', 'movies'), ensure_ascii=False)},
    seriesOne: {json.dumps(L('série', 'series'), ensure_ascii=False)},
    seriesMany: {json.dumps(L('séries', 'series'), ensure_ascii=False)},
    episode: {json.dumps(L('épisode', 'episode'), ensure_ascii=False)},
    episodes: {json.dumps(L('épisodes', 'episodes'), ensure_ascii=False)},
    category: {json.dumps(L('catégorie', 'category'), ensure_ascii=False)},
    categories: {json.dumps(L('catégories', 'categories'), ensure_ascii=False)},
    removal: {json.dumps(L('suppression', 'removal'), ensure_ascii=False)},
    removals: {json.dumps(L('suppressions', 'removals'), ensure_ascii=False)},
    rename: {json.dumps(L('renommage', 'rename'), ensure_ascii=False)},
    renames: {json.dumps(L('renommages', 'renames'), ensure_ascii=False)},
    noCountry: {json.dumps(L('Aucun pays', 'No country'), ensure_ascii=False)},
    emailEnabled: {json.dumps(L('Email activé', 'Email enabled'), ensure_ascii=False)},
    disabled: {json.dumps(L('Désactivées', 'Disabled'), ensure_ascii=False)},
    scanRunning: {json.dumps(L('Scan en cours…', 'Scan running…'), ensure_ascii=False)},
    scanFinished: {json.dumps(L('Scan terminé ✅', 'Scan completed ✅'), ensure_ascii=False)},
    scanNow: {json.dumps(L('Scanner maintenant', 'Scan now'), ensure_ascii=False)},
    scanStarted: {json.dumps(L('Scan lancé ✓', 'Scan started ✓'), ensure_ascii=False)},
    launching: {json.dumps(L('Lancement…', 'Starting…'), ensure_ascii=False)},
    invalidMin: {json.dumps(L('Valeur invalide. Minimum : 5 minutes.', 'Invalid value. Minimum: 5 minutes.'), ensure_ascii=False)},
    min5: {json.dumps(L('Minimum : 5 minutes.', 'Minimum: 5 minutes.'), ensure_ascii=False)},
    max1440: {json.dumps(L('Maximum : 1440 minutes.', 'Maximum: 1440 minutes.'), ensure_ascii=False)},
    scanStartFailed: {json.dumps(L('Impossible de lancer le scan', 'Unable to start scan'), ensure_ascii=False)},
    scanFailed: {json.dumps(L('Scan impossible', 'Scan failed'), ensure_ascii=False)},
    backup: {json.dumps(L('Sauvegarde', 'Backup'), ensure_ascii=False)},
    backupsKept: {json.dumps(L('sauvegarde(s) conservée(s)', 'backup(s) kept'), ensure_ascii=False)},
    backupConfirm: {json.dumps(L('Créer une sauvegarde de la base SQLite maintenant ?', 'Create a SQLite database backup now?'), ensure_ascii=False)},
    backingUp: {json.dumps(L('Sauvegarde…', 'Backing up…'), ensure_ascii=False)},
    backupFailed: {json.dumps(L('Échec de la sauvegarde', 'Backup failed'), ensure_ascii=False)},
    backupDone: {json.dumps(L('Sauvegarde effectuée ✓', 'Backup completed ✓'), ensure_ascii=False)},
    backupImpossible: {json.dumps(L('Sauvegarde impossible', 'Backup failed'), ensure_ascii=False)},
    sending: {json.dumps(L('Envoi…', 'Sending…'), ensure_ascii=False)},
    emailSendFailed: {json.dumps(L("Échec de l'envoi", 'Send failed'), ensure_ascii=False)},
    emailSent: {json.dumps(L('Email envoyé ✓', 'Email sent ✓'), ensure_ascii=False)},
    emailTestImpossible: {json.dumps(L('Email de test impossible', 'Test email failed'), ensure_ascii=False)},
    save: {json.dumps(L('Enregistrer', 'Save'), ensure_ascii=False)},
    saving: {json.dumps(L('Enregistrement…', 'Saving…'), ensure_ascii=False)},
    saveFailed: {json.dumps(L('Échec de l’enregistrement', 'Save failed'), ensure_ascii=False)},
    saved: {json.dumps(L('Enregistré ✓', 'Saved ✓'), ensure_ascii=False)},
    saveImpossible: {json.dumps(L('Enregistrement impossible', 'Unable to save'), ensure_ascii=False)},
    immediateWarning: {json.dumps(L(
        'Attention : les notifications en attente seront envoyées immédiatement après l’enregistrement. Continuer ?',
        'Warning: pending notifications will be sent immediately after saving. Continue?'
    ), ensure_ascii=False)},
    rebuildTitle: {json.dumps(L('Recréer la référence pour', 'Rebuild baseline for'), ensure_ascii=False)},
    rebuildBody1: {json.dumps(L('Les nouveautés actuellement mémorisées pour les catégories surveillées de cette zone seront nettoyées.', 'The changes currently remembered for the monitored categories in this zone will be cleared.'), ensure_ascii=False)},
    rebuildBody2: {json.dumps(L('Au prochain scan, le catalogue présent deviendra la nouvelle référence.', 'On the next scan, the current catalogue will become the new baseline.'), ensure_ascii=False)}
}};

const toastStack = document.getElementById('toastStack');

function showToast(message, type = 'success') {{
    if (!toastStack || !message) return;

    const toast = document.createElement('div');
    toast.className = 'toast ' + type;
    toast.textContent = message;
    toastStack.appendChild(toast);

    requestAnimationFrame(() => toast.classList.add('show'));

    setTimeout(() => {{
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 220);
    }}, type === 'error' ? 5000 : 3000);
}}

const sectionFilterMap = {{
    films: 'film',
    series: 'serie',
    episodes: 'episode',
    categories: 'categorie',
    suppressions: 'suppression',
    renommages: 'renommage'
}};

let activeFilter = sessionStorage.getItem('iptvActiveFilter') || 'all';
const savedSearch = sessionStorage.getItem('iptvSearch') || '';

searchInput.value = savedSearch;

function restoreActiveButton() {{
    const matching = filterButtons.find(
        b => b.dataset.filter === activeFilter
    );

    if (!matching) {{
        activeFilter = 'all';
    }}

    filterButtons.forEach(
        b => b.classList.toggle('active', b.dataset.filter === activeFilter)
    );
}}

function cardEventCount(card) {{
    const n = Number(card.dataset.eventCount || '1');
    return Number.isFinite(n) && n > 0 ? n : 1;
}}

function applyFilters() {{
    const q = searchInput.value.trim().toLowerCase();
    let visibleCards = 0;
    let visibleSections = 0;

    cards.forEach(card => {{
        const matchesKind = activeFilter === 'all' || card.dataset.filter === activeFilter;
        const matchesText = !q || card.dataset.search.includes(q);
        const show = matchesKind && matchesText;
        card.classList.toggle('hidden', !show);
        if (show) visibleCards += cardEventCount(card);
    }});

    // Dans les vues 7/30 jours, chaque journée devient une ligne repliable.
    // La recherche masque les jours sans résultat et ouvre automatiquement
    // ceux qui contiennent une correspondance.
    dayGroups.forEach(group => {{
        const groupCards = [...group.querySelectorAll('.event-card')];
        const visibleGroupCards = groupCards.filter(c => !c.classList.contains('hidden'));
        const visibleCount = visibleGroupCards
            .reduce((sum, c) => sum + cardEventCount(c), 0);
        const badge = group.querySelector('.day-count');
        const breakdown = group.querySelector('.day-breakdown');

        if (badge) {{
            badge.textContent = `${{visibleCount}} ${{visibleCount === 1 ? TXT.change : TXT.changes}}`;
        }}

        if (breakdown) {{
            const counts = {{}};
            visibleGroupCards.forEach(card => {{
                const key = card.dataset.filter || 'autre';
                counts[key] = (counts[key] || 0) + cardEventCount(card);
            }});
            const labels = [
                ['film', TXT.movie, TXT.movies],
                ['serie', TXT.seriesOne, TXT.seriesMany],
                ['episode', TXT.episode, TXT.episodes],
                ['categorie', TXT.category, TXT.categories],
                ['suppression', TXT.removal, TXT.removals],
                ['renommage', TXT.rename, TXT.renames]
            ];
            breakdown.replaceChildren();
            const parts = labels.filter(([key]) => counts[key]);

            parts.forEach(([key, one, many], index) => {{
                if (index > 0) {{
                    breakdown.appendChild(document.createTextNode(' · '));
                }}

                const number = document.createElement('span');
                number.className = 'day-breakdown-number';
                number.textContent = String(counts[key]);
                breakdown.appendChild(number);
                breakdown.appendChild(
                    document.createTextNode(` ${{counts[key] === 1 ? one : many}}`)
                );
            }});
        }}

        group.style.display = visibleCount > 0 ? '' : 'none';
        if (q && visibleCount > 0) {{
            group.open = true;
        }}
    }});

    details.forEach(section => {{
        const sectionKind = sectionFilterMap[section.id];
        const filterAllowsSection =
            activeFilter === 'all' || sectionKind === activeFilter;

        if (!filterAllowsSection) {{
            section.style.display = 'none';
            return;
        }}

        const sectionCards = [...section.querySelectorAll('.event-card')];
        const visible = sectionCards
            .filter(c => !c.classList.contains('hidden'))
            .reduce((sum, c) => sum + cardEventCount(c), 0);
        const badge = section.querySelector('.summary-count');

        if (badge) {{
            badge.textContent = visible;
        }}

        if (sectionCards.length === 0) {{
            // Sans recherche : on garde la section pertinente visible,
            // même à 0, afin que le compteur reste compréhensible.
            // Avec une recherche : une section vide n'apporte rien.
            section.style.display = q ? 'none' : '';
        }} else {{
            section.style.display = visible > 0 ? '' : 'none';
        }}

        if (section.style.display !== 'none') {{
            visibleSections++;
        }}
    }});

    noResults.classList.toggle(
        'visible',
        (q || activeFilter !== 'all') &&
        visibleCards === 0 &&
        visibleSections === 0
    );
}}

searchInput.addEventListener('input', () => {{
    sessionStorage.setItem('iptvSearch', searchInput.value);
    applyFilters();
}});

filterButtons.forEach(btn => {{
    btn.addEventListener('click', () => {{
        activeFilter = btn.dataset.filter;
        sessionStorage.setItem('iptvActiveFilter', activeFilter);

        filterButtons.forEach(
            b => b.classList.toggle('active', b === btn)
        );

        applyFilters();
    }});
}});

restoreActiveButton();
applyFilters();

const settingsModal = document.getElementById('settingsModal');
const openSettings = document.getElementById('openSettings');
const closeSettings = document.getElementById('closeSettings');
const cancelSettings = document.getElementById('cancelSettings');
const categorySearch = document.getElementById('categorySearch');

let pageRefreshTimer = null;
let refreshAfterScanPending = false;
let knownLastSuccessIso = {json.dumps(scan_status.get("last_success_iso", ""), ensure_ascii=False)};
let scanFinishedTimer = null;
let previousScanRunning = false;
let scanFinishedDisplayUntil = 0;
const PAGE_REFRESH_MS = 300000;

function schedulePageRefresh() {{
    if (pageRefreshTimer) clearTimeout(pageRefreshTimer);
    pageRefreshTimer = setTimeout(() => {{
        // Ne jamais recharger la page pendant que les paramètres sont ouverts.
        if (settingsModal && settingsModal.classList.contains('open')) {{
            schedulePageRefresh();
            return;
        }}
        location.reload();
    }}, PAGE_REFRESH_MS);
}}

function setSettingsOpen(open) {{
    if (!settingsModal) return;
    settingsModal.classList.toggle('open', open);
    settingsModal.setAttribute('aria-hidden', open ? 'false' : 'true');
    document.body.style.overflow = open ? 'hidden' : '';

    if (open) {{
        // Stoppe le compte à rebours de rafraîchissement pendant les réglages.
        if (pageRefreshTimer) {{
            clearTimeout(pageRefreshTimer);
            pageRefreshTimer = null;
        }}
    }} else {{
        if (refreshAfterScanPending) {{
            location.reload();
            return;
        }}
        // Repart sur 5 minutes complètes après fermeture des paramètres.
        schedulePageRefresh();
    }}
}}
if (openSettings) openSettings.addEventListener('click', () => setSettingsOpen(true));
if (closeSettings) closeSettings.addEventListener('click', () => setSettingsOpen(false));
if (cancelSettings) cancelSettings.addEventListener('click', () => setSettingsOpen(false));
if (settingsModal) settingsModal.addEventListener('click', (e) => {{
    if (e.target === settingsModal) setSettingsOpen(false);
}});

schedulePageRefresh();

document.querySelectorAll('input[name="countries"]').forEach(checkbox => {{
    checkbox.addEventListener('change', () => {{
        const panel = checkbox.closest('.country-panel');
        if (!panel) return;

        const code = panel.dataset.countryPanel;
        const tab = document.querySelector(
            `.country-tab[data-country="${{CSS.escape(code)}}"]`
        );

        if (tab) tab.classList.toggle('monitored', checkbox.checked);
    }});
}});

document.querySelectorAll('.country-tab').forEach(btn => {{
    btn.addEventListener('click', () => {{
        document.querySelectorAll('.country-tab').forEach(x => x.classList.toggle('active', x === btn));
        document.querySelectorAll('.country-panel').forEach(panel => {{
            panel.classList.toggle('active', panel.dataset.countryPanel === btn.dataset.country);
        }});
        if (categorySearch) {{
            categorySearch.value = '';
            categorySearch.dispatchEvent(new Event('input'));
        }}
    }});
}});

if (categorySearch) categorySearch.addEventListener('input', () => {{
    const q = categorySearch.value.trim().toLowerCase();
    document.querySelectorAll('.country-panel.active .category-option').forEach(row => {{
        row.style.display = !q || row.dataset.catSearch.includes(q) ? '' : 'none';
    }});
}});

const runBackupNow = document.getElementById('runBackupNow');
const runScanNow = document.getElementById('runScanNow');
const runBackupQuick = document.getElementById('runBackupQuick');
const runScanQuick = document.getElementById('runScanQuick');

const scanActionButtons = [runScanNow, runScanQuick].filter(Boolean);
const backupActionButtons = [runBackupNow, runBackupQuick].filter(Boolean);

backupActionButtons.forEach(btn => {{
    btn.dataset.idleText = btn.textContent;
}});

const testEmailBtn = document.getElementById('testEmailBtn');
const scanIntervalMode = document.getElementById('scanIntervalMode');
const scanIntervalCustom = document.getElementById('scanIntervalCustom');
const scanCustomWrap = document.getElementById('scanCustomWrap');
const settingsForm = document.getElementById('settingsForm');

function syncScanCustomVisibility() {{
    if (!scanIntervalMode || !scanCustomWrap) return;
    const custom = scanIntervalMode.value === 'custom';
    scanCustomWrap.classList.toggle('scan-custom-hidden', !custom);
    scanCustomWrap.classList.toggle('scan-custom-visible', custom);
}}
if (scanIntervalMode) scanIntervalMode.addEventListener('change', syncScanCustomVisibility);
syncScanCustomVisibility();

function normalizeScanCustomInput(showMessage = false) {{
    if (!scanIntervalCustom) return true;
    const raw = scanIntervalCustom.value.trim();
    const value = Number(raw);
    let corrected = null;
    let message = '';

    if (!raw || !Number.isFinite(value)) {{
        corrected = 5;
        message = TXT.invalidMin;
    }} else if (value < 5) {{
        corrected = 5;
        message = TXT.min5;
    }} else if (value > 1440) {{
        corrected = 1440;
        message = TXT.max1440;
    }}

    if (corrected !== null) {{
        scanIntervalCustom.value = String(corrected);
        if (showMessage) alert(message);
        return false;
    }}
    return true;
}}

if (scanIntervalCustom) {{
    scanIntervalCustom.addEventListener('blur', () => normalizeScanCustomInput(true));
}}

function applySettingsSummary(summary) {{
    if (!summary) return;
    const countryDisplay = summary.country_display || TXT.noCountry;
    const monitorCountries = document.getElementById('monitorCountryDisplay');
    const catalogCountries = document.getElementById('catalogCountryDisplay');
    const vodCount = document.getElementById('catalogVodCategoryCount');
    const seriesCount = document.getElementById('catalogSeriesCategoryCount');
    if (monitorCountries) monitorCountries.textContent = countryDisplay;
    if (catalogCountries) catalogCountries.textContent = countryDisplay;
    if (vodCount && summary.vod_categories !== undefined) vodCount.textContent = String(summary.vod_categories);
    if (seriesCount && summary.series_categories !== undefined) seriesCount.textContent = String(summary.series_categories);
    const notifStatus = document.getElementById('notificationSystemStatus');
    if (notifStatus && summary.email_enabled !== undefined) {{
        notifStatus.textContent = summary.email_enabled ? TXT.emailEnabled : TXT.disabled;
    }}
}}

function applyScanStatus(status, scanJustFinished = false) {{
    if (!status) return;
    if (Date.now() < scanFinishedDisplayUntil) {{
    const quickNext = document.getElementById('nextScanValue');
    if (quickNext) quickNext.textContent = TXT.scanFinished;
}}
    const last = status.last_detail || '—';
    const next = status.next_detail || '—';
    const wasRunning = previousScanRunning;
    previousScanRunning = !!status.running;
    const interval = String(status.interval_minutes ?? '—');

    const settingsLast = document.getElementById('scanSettingsLast');
    const settingsNext = document.getElementById('scanSettingsNext');
    const quickLast = document.getElementById('lastScanValue');
    const quickNext = document.getElementById('nextScanValue');
    const systemInterval = document.getElementById('scanSystemInterval');

    if (settingsLast) settingsLast.textContent = last;
    if (settingsNext) settingsNext.textContent = next;
    if (quickLast) quickLast.textContent = last;
    if (quickNext) {{
    if (scanJustFinished) {{
        scanFinishedDisplayUntil = Date.now() + 3000;

        quickNext.textContent = TXT.scanFinished;

        clearTimeout(scanFinishedTimer);
        scanFinishedTimer = setTimeout(() => {{
            scanFinishedDisplayUntil = 0;
        }}, 3000);

    }} else if (Date.now() >= scanFinishedDisplayUntil) {{
        quickNext.textContent = `≈ ${{next}}`;
    }}
}}
    if (systemInterval) systemInterval.textContent = interval;
    scanActionButtons.forEach(btn => {{
        btn.disabled = !!status.running;
        btn.textContent = status.running ? TXT.scanRunning : TXT.scanNow;
    }});
}}

async function refreshScanStatus() {{
    try {{
        const response = await fetch('/api/scan/status', {{ cache: 'no-store' }});
        if (!response.ok) return;

        const status = await response.json();

        const latestSuccessIso = status.last_success_iso || '';
        const scanJustFinished = latestSuccessIso && latestSuccessIso !== knownLastSuccessIso;

        if (scanJustFinished) {{
        knownLastSuccessIso = latestSuccessIso;
}}

applyScanStatus(status, scanJustFinished);

if (scanJustFinished) {{

            // Ne jamais couper une utilisation des paramètres en cours.
            if (settingsModal && settingsModal.classList.contains('open')) {{
                refreshAfterScanPending = true;
            }} else {{
                setTimeout(() => {{
                    location.reload();
                }}, 3000);
                return;
            }}
        }}
    }} catch (err) {{
        // Le polling du scan ne doit jamais perturber l'interface.
    }}
}}

async function handleRunScanNow() {{
    scanActionButtons.forEach(btn => {{
        btn.disabled = true;
        btn.textContent = TXT.launching;
    }});

    try {{
        const response = await fetch('/scan/run?ajax=1', {{
            method: 'POST',
            headers: {{ 'Accept': 'application/json' }},
            body: new URLSearchParams({{ return_days: String({days}) }}),
        }});
        const result = await response.json();

        if (!response.ok || !result.ok) {{
            throw new Error(result.error || TXT.scanStartFailed);
        }}

        applyScanStatus(result.status);
        showToast(TXT.scanStarted, 'success');

    }} catch (err) {{
        showToast(`${{TXT.scanFailed}}: ${{err.message || err}}`, 'error');

        scanActionButtons.forEach(btn => {{
            btn.disabled = false;
            btn.textContent = TXT.scanNow;
        }});
    }}
}}

scanActionButtons.forEach(btn => btn.addEventListener('click', handleRunScanNow));

function applyBackupStatus(status) {{
    if (!status) return;
    const detail = status.detail || '—';
    const count = String(status.count ?? 0);
    const label = status.label || TXT.backup;

    const settingsDetail = document.getElementById('backupSettingsDetail');
    const settingsCount = document.getElementById('backupSettingsCount');
    const settingsLatestSize = document.getElementById('backupSettingsLatestSize');
    const settingsTotalSize = document.getElementById('backupSettingsTotalSize');
    const systemDetail = document.getElementById('backupSystemDetail');
    const systemCount = document.getElementById('backupSystemCount');
    const systemLatestSize = document.getElementById('backupSystemLatestSize');
    const systemTotalSize = document.getElementById('backupSystemTotalSize');
    const pill = document.getElementById('backupStatusPill');
    const pillText = document.getElementById('backupStatusText');

    if (settingsDetail) settingsDetail.textContent = detail;
    if (settingsCount) settingsCount.textContent = count;
    if (settingsLatestSize) settingsLatestSize.textContent = status.latest_size || '—';
    if (settingsTotalSize) settingsTotalSize.textContent = status.total_size || '—';
    if (systemDetail) systemDetail.textContent = detail;
    if (systemCount) systemCount.textContent = count;
    if (systemLatestSize) systemLatestSize.textContent = status.latest_size || '—';
    if (systemTotalSize) systemTotalSize.textContent = status.total_size || '—';
    if (pillText) pillText.textContent = `${{label}} · ${{detail}}`;
    if (pill) {{
        pill.classList.remove('ok', 'warn', 'error');
        if (status.class) pill.classList.add(status.class);
        pill.title = `${{count}} ${{TXT.backupsKept}}`;
    }}
}}

async function refreshBackupStatus() {{
    try {{
        const response = await fetch('/api/backup/status', {{ cache: 'no-store' }});
        if (!response.ok) return;
        applyBackupStatus(await response.json());
    }} catch (err) {{
        // Une erreur de polling ne doit jamais perturber l'utilisation de la page.
    }}
}}

async function handleRunBackupNow() {{
    const ok = confirm(TXT.backupConfirm);
    if (!ok) return;

    backupActionButtons.forEach(btn => {{
        btn.disabled = true;
        btn.textContent = TXT.backingUp;
    }});

    try {{
        const response = await fetch('/backup/run?ajax=1', {{
            method: 'POST',
            headers: {{ 'Accept': 'application/json' }},
            body: new URLSearchParams({{ return_days: String({days}) }}),
        }});
        const result = await response.json();

        if (!response.ok || !result.ok) {{
            throw new Error(result.error || TXT.backupFailed);
        }}

        applyBackupStatus(result.status);

        backupActionButtons.forEach(btn => {{
            btn.textContent = TXT.backupDone;
        }});

        showToast(TXT.backupDone, 'success');

        setTimeout(() => {{
            backupActionButtons.forEach(btn => {{
                btn.textContent = btn.dataset.idleText;
                btn.disabled = false;
            }});
        }}, 1600);

    }} catch (err) {{
        showToast(`${{TXT.backupImpossible}}: ${{err.message || err}}`, 'error');

        backupActionButtons.forEach(btn => {{
            btn.textContent = btn.dataset.idleText;
            btn.disabled = false;
        }});
    }}
}}

backupActionButtons.forEach(btn => btn.addEventListener('click', handleRunBackupNow));

if (testEmailBtn) testEmailBtn.addEventListener('click', async () => {{
    const originalText = testEmailBtn.textContent;
    testEmailBtn.disabled = true;
    testEmailBtn.textContent = TXT.sending;
    try {{
        const params = new URLSearchParams(new FormData(settingsForm));
        const response = await fetch('/notifications/test', {{
            method: 'POST',
            headers: {{
                'Accept': 'application/json',
                'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
            }},
            body: params.toString(),
        }});
        const result = await response.json();
        if (!response.ok || !result.ok) {{
            throw new Error(result.error || TXT.emailSendFailed);
        }}
        testEmailBtn.textContent = TXT.emailSent;
        showToast(TXT.emailSent, 'success');
        setTimeout(() => {{
            testEmailBtn.textContent = originalText;
            testEmailBtn.disabled = false;
        }}, 1800);
    }} catch (err) {{
        showToast(`${{TXT.emailTestImpossible}}: ${{err.message || err}}`, 'error');
        testEmailBtn.textContent = originalText;
        testEmailBtn.disabled = false;
    }}
}});

if (settingsForm) settingsForm.addEventListener('submit', async (e) => {{
    e.preventDefault();

    const digestSelect = settingsForm.querySelector('#emailDigestHours');
    const emailEnabled = settingsForm.querySelector('input[name="email_enabled"]');

    if (
        digestSelect &&
        emailEnabled &&
        emailEnabled.checked &&
        digestSelect.value === '0' &&
        digestSelect.dataset.savedValue !== '0'
    ) {{
        const ok = confirm(TXT.immediateWarning);
        if (!ok) {{
            digestSelect.value = digestSelect.dataset.savedValue || '2';
            return;
        }}
    }}

    const submitBtn = settingsForm.querySelector('.save-btn');
    const originalText = submitBtn ? submitBtn.textContent : TXT.save;
    if (submitBtn) {{
        submitBtn.disabled = true;
        submitBtn.textContent = TXT.saving;
    }}
    try {{
        if (scanIntervalMode && scanIntervalMode.value === 'custom' && scanIntervalCustom) {{
            // Le navigateur autorise la saisie clavier hors bornes malgré min/max.
            // On corrige donc visuellement la valeur avant de l'envoyer au serveur.
            normalizeScanCustomInput(true);
        }}
        const params = new URLSearchParams(new FormData(settingsForm));
        const response = await fetch('/settings?ajax=1', {{
            method: 'POST',
            headers: {{
                'Accept': 'application/json',
                'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
            }},
            body: params.toString(),
        }});
        const result = await response.json();
        if (!response.ok || !result.ok) {{
            throw new Error(result.error || TXT.saveFailed);
        }}
        applySettingsSummary(result.summary);
        applyBackupStatus(result.status);
        applyScanStatus(result.scan_status);
        if (digestSelect) digestSelect.dataset.savedValue = digestSelect.value;
        if (submitBtn) {{
            submitBtn.textContent = TXT.saved;
            showToast(TXT.saved, 'success');
            setTimeout(() => {{
                submitBtn.textContent = originalText;
                submitBtn.disabled = false;
            }}, 1400);
        }}
        // Important : la fenêtre Paramètres reste ouverte. Aucun reload complet.
    }} catch (err) {{
        showToast(`${{TXT.saveImpossible}}: ${{err.message || err}}`, 'error');
        if (submitBtn) {{
            submitBtn.textContent = originalText;
            submitBtn.disabled = false;
        }}
    }}
}});

// Actualise les états sans recharger la page.
refreshScanStatus();
setInterval(refreshScanStatus, 5000);
refreshBackupStatus();
setInterval(refreshBackupStatus, 10000);

document.querySelectorAll('.baseline-reset-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
        const code = btn.dataset.baselineCountry || '';
        const label = btn.dataset.baselineLabel || code;
        if (!code) return;
        const ok = confirm(
            `${{TXT.rebuildTitle}} ${{label}} ?\n\n` +
            `${{TXT.rebuildBody1}} ` +
            TXT.rebuildBody2
        );
        if (!ok) return;

        const form = document.createElement('form');
        form.method = 'post';
        form.action = '/baseline/reset';
        const country = document.createElement('input');
        country.type = 'hidden';
        country.name = 'country';
        country.value = code;
        form.appendChild(country);
        const daysInput = document.createElement('input');
        daysInput.type = 'hidden';
        daysInput.name = 'return_days';
        daysInput.value = {days};
        form.appendChild(daysInput);
        document.body.appendChild(form);
        form.submit();
    }});
}});

document.querySelectorAll('.mini-select').forEach(btn => {{
    btn.addEventListener('click', () => {{
        const panel = btn.closest('.country-panel');
        if (!panel) return;
        const column = panel.querySelector(`.category-column[data-kind="${{btn.dataset.kind}}"]`);
        if (!column) return;
        const checked = btn.dataset.action === 'all';
        column.querySelectorAll('.category-option').forEach(row => {{
            if (row.style.display !== 'none') {{
                const box = row.querySelector('input[type="checkbox"]');
                if (box) box.checked = checked;
            }}
        }});
    }});
}});
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path in ("/favicon.png", "/app-logo.png"):
            asset_name = {
                "/favicon.png": "favicon.png",
                "/app-logo.png": "app-logo.png",
            }[parsed.path]
            asset_path = ASSET_DIR / asset_name
            try:
                body = asset_path.read_bytes()
            except OSError:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/scan/status":
            payload = json.dumps(get_scan_status(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/api/backup/status":
            payload = json.dumps(get_backup_status(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/health":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path != "/":
            self.send_error(404)
            return

        q = parse_qs(parsed.query)
        try:
            days = int(q.get("days", ["1"])[0])
        except Exception:
            days = 1

        body = render_page(days).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in ("/settings", "/baseline/reset", "/backup/run", "/scan/run", "/notifications/test", "/language"):
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except Exception:
            length = 0
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = parse_qs(raw, keep_blank_values=True)

        if parsed.path == "/language":
            with db() as conn:
                save_ui_language(conn, form)
                conn.commit()
            try:
                days = int(form.get("return_days", ["1"])[0])
            except Exception:
                days = 1
            if days not in (1, 7, 30):
                days = 1
            self.send_response(303)
            self.send_header("Location", f"/?days={days}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        if parsed.path == "/notifications/test":
            try:
                with db() as conn:
                    settings = email_settings_from_form(conn, form)
                send_email_test(settings)
                lang = normalize_ui_language(settings.get("language", "fr"))
                payload = json.dumps({"ok": True, "message": ui_text(lang, "Email de test envoyé", "Test email sent")}, ensure_ascii=False).encode("utf-8")
                status = 200
            except Exception as exc:
                message = sanitize_watcher_error(f"{type(exc).__name__}: {exc}")
                record_email_result(False, message)
                payload = json.dumps({"ok": False, "error": message}, ensure_ascii=False).encode("utf-8")
                status = 400
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/scan/run":
            lang = get_ui_language()
            started = start_scan("manual")
            payload = json.dumps({
                "ok": True,
                "started": started,
                "message": ui_text(lang, "Scan lancé", "Scan started") if started else ui_text(lang, "Un scan est déjà en cours", "A scan is already running"),
                "status": get_scan_status(lang),
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/backup/run":
            with LOCK:
                backup_result = create_db_backup("manual")

            ajax = parse_qs(parsed.query).get("ajax", ["0"])[0] == "1"
            if ajax:
                payload_obj = dict(backup_result)
                payload_obj["status"] = get_backup_status()
                payload = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")
                self.send_response(200 if backup_result.get("ok") else 500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
        else:
            settings_summary = None
            with LOCK:
                with db() as conn:
                    if parsed.path == "/settings":
                        save_category_settings(conn, form)
                        settings_summary = settings_ui_summary(conn)
                    else:
                        country = safe_text(form.get("country", [""])[0]).strip().upper()
                        result = reset_country_baseline(conn, country)
                        print(
                            f"[OK] Référence demandée pour {country_label(country)}: "
                            f"{result['categories']} catégorie(s), "
                            f"{result['events_deleted']} événement(s) nettoyé(s).",
                            flush=True
                        )

            if parsed.path == "/settings":
                ajax = parse_qs(parsed.query).get("ajax", ["0"])[0] == "1"
                if ajax:
                    response_lang = (settings_summary or {}).get("ui_language", get_ui_language())
                    payload = json.dumps({
                        "ok": True,
                        "summary": settings_summary or {},
                        "status": get_backup_status(response_lang),
                        "scan_status": get_scan_status(response_lang),
                    }, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

        try:
            days = int(form.get("return_days", ["1"])[0])
        except Exception:
            days = 1
        if days not in (1, 7, 30):
            days = 1
        self.send_response(303)
        self.send_header("Location", f"/?days={days}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass

def loop():
    # Comme l'ancienne version, un redémarrage du conteneur lance un scan
    # immédiatement. Ensuite, les échéances sont calculées depuis la base.
    start_scan("startup")
    while True:
        try:
            with db() as conn:
                settings = get_scan_settings(conn)
            if scan_is_due(settings) and not get_scan_status().get("running"):
                start_scan("auto")

            next_due = scan_next_due(settings)
            wait_seconds = max(1.0, min(float(SCAN_CHECK_SECONDS), (next_due - datetime.now(TZ)).total_seconds()))
        except Exception as exc:
            print(f"[ERREUR] Planificateur scan : {safe_text(exc)[:500]}", flush=True)
            wait_seconds = float(SCAN_CHECK_SECONDS)

        SCAN_WAKE.wait(wait_seconds)
        SCAN_WAKE.clear()

def main():
    BASE.mkdir(parents=True, exist_ok=True)
    init_db()

    t = threading.Thread(target=loop, daemon=True)
    t.start()

    backup_thread = threading.Thread(target=backup_loop, daemon=True)
    backup_thread.start()

    email_thread = threading.Thread(target=email_digest_loop, daemon=True)
    email_thread.start()

    server = ThreadingHTTPServer(("0.0.0.0", int(CFG["port"])), Handler)
    print(f"[OK] Page web prête sur le port {CFG['port']}", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    main()
