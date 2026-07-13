import os
import json
import requests
from datetime import datetime
from app.audit import DEFAULT_DB_PATH, init_db
from app.db import FxCacheRepository

STATIC_FX_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "fx_rates.json")
)

def load_static_fx_rate(from_currency: str, to_currency: str = "INR") -> float:
    """
    Loads static rate from fx_rates.json. Defaults to USD: 83.5, EUR: 90.0, GBP: 106.0, INR: 1.0.
    """
    fallback_rates = {"USD": 83.5, "EUR": 90.0, "GBP": 106.0, "INR": 1.0}
    if os.path.exists(STATIC_FX_PATH):
        try:
            with open(STATIC_FX_PATH, "r") as f:
                rates = json.load(f)
                return rates.get(from_currency, fallback_rates.get(from_currency, 1.0))
        except Exception:
            pass
            
    if from_currency == to_currency:
        return 1.0
    return fallback_rates.get(from_currency, 1.0)

def get_fx_rate(from_currency: str, to_currency: str = "INR", db_path: str = DEFAULT_DB_PATH) -> tuple[float, str]:
    """
    Returns (rate, source) where source is 'live_api' or 'static_fallback'.
    Checks local cache (valid for 6 hours) before calling the free live API.
    """
    from_curr = from_currency.upper().strip()
    to_curr = to_currency.upper().strip()
    
    if from_curr == to_curr:
        return 1.0, "live_api"
        
    pair = f"{from_curr}_{to_curr}"
    
    # Ensure DB is initialized
    init_db(db_path)
    repo = FxCacheRepository(db_path)
    
    # 1. Check local cache (fetched within the last 6 hours)
    cached_rate = repo.get_cached_rate(pair, max_age_hours=6)
    if cached_rate is not None:
        return cached_rate, "live_api"
        
    # 2. Call live FX API
    url = f"https://open.er-api.com/v6/latest/{from_curr}"
    try:
        response = requests.get(url, timeout=3.0)
        if response.status_code == 200:
            data = response.json()
            if data.get("result") == "success":
                rates = data.get("rates", {})
                rate = rates.get(to_curr)
                if rate is not None:
                    rate = float(rate)
                    repo.store_rate(pair, rate, "live_api")
                    return rate, "live_api"
    except Exception:
        pass
        
    # 3. Fallback to static JSON file
    rate = load_static_fx_rate(from_curr, to_curr)
    return rate, "static_fallback"
