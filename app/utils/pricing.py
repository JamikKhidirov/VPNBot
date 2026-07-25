DISCOUNT_INFO = {
    "1month":  {"monthly": 70,  "original": 70,   "discount_pct": 0},
    "3months": {"monthly": 70,  "original": 210,  "discount_pct": 10},
    "1year":   {"monthly": 70,  "original": 840,  "discount_pct": 30},
}


def get_discount_text(plan_code: str, price: float) -> str:
    info = DISCOUNT_INFO.get(plan_code)
    if not info or info["discount_pct"] == 0:
        return ""
    saved = info["original"] - price
    return f" 🔥 -{info['discount_pct']}% (экономия {int(saved)}₽)"


def get_plan_price_text(price: float) -> str:
    return f"{int(price)} ₽" if price == int(price) else f"{price} ₽"
