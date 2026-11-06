import re
from datetime import date, timedelta

METHOD_PATTERNS = [
    ("vehicle_ramming", r"\b(ram|rammed|ramming|crash|crashed|(?:drove|driven|backed) (?:[\w-]+ ){0,3}?(?:into|through)|vehicle (?:into|through)|smash(?:ed)? (?:a |the )?(?:car|truck|suv|vehicle) into)\b"),
    ("safe_cut", r"\b(safe (?:was )?(?:cut|sawed|ground|opened with)|cut (?:open )?(?:the |a )?safe|saw(?:ed)? (?:open )?(?:the |a )?safe|grinder|angle grinder|circular saw|torch|saw(?:ed|ing)? (?:into|through))\b"),
    ("atm_theft", r"\batm\b"),
    ("wifi_jammer", r"\b(wi-?fi jammer|signal jammer|jammer)\b"),
    ("distraction_ruse", r"\b(ruse|distraction|posed as|salesman|pretend(?:ed|ing)? to be|impersonat)\b"),
    ("second_floor_entry", r"\b(second[- ]floor|second[- ]story|upper[- ]floor|balcony)\b"),
    ("rear_window", r"\b(rear window|back window|rear slid(?:ing|er)|rear (?:glass |sliding )*(?:doors?|windows?)|back door)\b"),
    ("glass_smash", r"\b(smash(?:ed|ing)? (?:the |a |through )?(?:front |glass |store|shop|display )?(?:window|glass|door)|broke (?:the |a )?(?:glass|window)|shattered|rock (?:was )?thrown|threw a rock|brick through|glass (?:\w+ )?(?:smashed|punched|broken|breaker|shattered)|(?:window|door|entrance|doors) (?:\w+ )?(?:broken|shattered|punched)|punched out|broken with a rock|using a rock|rock was used to break|object thrown into|window punching)\b"),
    ("forced_door", r"\b(pried|pry(?:ing)? ?(?:bar|open)?|forced (?:the |a )?(?:door|entry|open)|kick(?:ed|ing) (?:in|open)|forc(?:ed|ing) (?:open|entry)|broke in|crowbar|jimmied|broke (?:the |a )?lock|cut (?:the |a )?lock|bolt cutter)\b"),
]

COLOR_WORDS = ["black", "dark", "white", "silver", "grey", "gray", "red", "blue", "gold", "tan", "green", "maroon", "light"]
BODY_PATTERNS = [
    ("u_haul", r"\bu-?haul\b"),
    ("box_truck", r"\bbox truck\b"),
    ("pickup", r"\b(pickup|pick-up)\b"),
    ("suv", r"\b(suv|jeep|tahoe|suburban|escalade|4runner|explorer|highlander)\b"),
    ("van", r"\b(van|minivan)\b"),
    ("sedan", r"\b(sedan|honda|toyota|hyundai|kia|nissan|infiniti|lexus|bmw|mercedes|audi)\b"),
    ("e_bike", r"\b(e-?bike|electric bike|ebike)\b"),
    ("bicycle", r"\b(bicycle|bike)\b"),
    ("truck", r"\btruck\b"),
    ("car", r"\b(car|vehicle)\b"),
]

NO_VEHICLE_PATTERN = r"\b(?:no|without|unknown) (?:known |suspect )?vehicles?\b"

ITEM_PATTERNS = [
    ("cash", r"\b(cash|money|currency|register|till)\b"),
    ("atm", r"\batm\b"),
    ("safe", r"\bsafe\b"),
    ("jewelry", r"\b(jewel|jewelry|jewellery|watch|watches|ring|necklace|gold|diamond)\b"),
    ("phones", r"\b(phone|iphone|cell ?phone|smartphone|tablet|ipad)\b"),
    ("electronics", r"\b(electronic|laptop|computer|camera|tv|television|console|playstation|xbox)\b"),
    ("tobacco", r"\b(cigarette|tobacco|vape|nicotine|smoke shop)\b"),
    ("cannabis", r"\b(cannabis|marijuana|weed|dispensary)\b"),
    ("firearms", r"\b(gun|firearm|pistol|rifle|handgun)\b"),
    ("alcohol", r"\b(liquor|alcohol|wine|beer|spirits)\b"),
    ("designer_goods", r"\b(designer|handbag|purse|luxury|louis|gucci|chanel)\b"),
    ("tools", r"\b(tool|equipment)\b"),
    ("vehicle", r"\b(car keys|vehicle stolen|stole (?:a|the) (?:car|vehicle|truck))\b"),
]

SCENE_TYPES = {
    "residence": ["residence", "home", "house", "apartment", "condo", "residential", "dwelling"],
    "restaurant": ["restaurant", "cafe", "coffee", "bar", "diner", "eatery", "taqueria", "pizzeria"],
    "retail": ["store", "shop", "retail", "boutique", "market", "grocery", "pharmacy", "dispensary", "smoke shop"],
    "business": ["business", "office", "commercial", "warehouse", "salon", "gym", "clinic"],
    "bank": ["bank", "credit union"],
}


def canonical_method(*texts):
    joined = " ".join(t for t in texts if t).lower()
    found = []
    for key, pattern in METHOD_PATTERNS:
        if re.search(pattern, joined) and key not in found:
            found.append(key)
    return found


def canonical_vehicle(text):
    if not text:
        return None
    lowered = text.lower()
    lowered = re.sub(NO_VEHICLE_PATTERN, "", lowered)
    body = next((key for key, pattern in BODY_PATTERNS if re.search(pattern, lowered)), None)
    if body is None:
        return None
    color = next((c for c in COLOR_WORDS if re.search(rf"\b{c}\b", lowered)), None)
    if color in ("black", "dark", "grey", "gray", "maroon", "green", "blue"):
        color = "dark" if color != "blue" else "blue"
    if color in ("white", "silver", "light", "tan", "gold"):
        color = "light"
    if body in ("u_haul", "box_truck", "e_bike", "bicycle"):
        return body
    return f"{color}_{body}" if color else body


def canonical_items(items, *texts):
    joined = " ".join([*(items or []), *(t for t in texts if t)]).lower()
    found = []
    for key, pattern in ITEM_PATTERNS:
        if re.search(pattern, joined) and key not in found:
            found.append(key)
    return found


def canonical_scene(scene_type, *texts):
    joined = " ".join([scene_type or "", *(t for t in texts if t)]).lower()
    if scene_type and scene_type.lower() in SCENE_TYPES:
        return scene_type.lower()
    for key, words in SCENE_TYPES.items():
        if any(w in joined for w in words):
            return key
    return (scene_type or "unknown").lower()


def time_window(date_text, precision="day"):
    if not date_text:
        return None
    if precision == "month" or len(date_text) == 7:
        return date_text[:7]
    year, month, day = (int(x) for x in date_text[:10].split("-"))
    iso = date(year, month, day).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def window_bounds(window):
    if window is None:
        return None, None
    if "-W" in window:
        year, week = window.split("-W")
        start = date.fromisocalendar(int(year), int(week), 1)
        return start, start + timedelta(days=6)
    year, month = (int(x) for x in window.split("-"))
    start = date(year, month, 1)
    end = (date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1))
    return start, end


STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
STATE_CODES = set(STATE_NAMES.values())
ZIP_SUFFIX = r"(?:\s+\d{5}(?:-\d{4})?)?"
STATE_NAME_PATTERN = "|".join(sorted((re.escape(n) for n in STATE_NAMES), key=len, reverse=True))
TRAILING_CODE = re.compile(rf"^(?P<rest>.*?)\s*\b(?P<state>[A-Z]{{2}}){ZIP_SUFFIX}$")
TRAILING_NAME = re.compile(rf"^(?P<rest>.*?)\s*\b(?P<state>{STATE_NAME_PATTERN}){ZIP_SUFFIX}$", re.IGNORECASE)


def split_state(part):
    code = TRAILING_CODE.match(part)
    if code and code["state"] in STATE_CODES:
        return code["rest"].strip(" ,"), code["state"]
    name = TRAILING_NAME.match(part)
    if name:
        return name["rest"].strip(" ,"), STATE_NAMES[name["state"].lower()]
    return part, ""


def parse_location(text, city=None, state=None, neighborhood=None):
    if city:
        return {"city": city.strip(), "state": (state or "").strip(), "neighborhood": (neighborhood or "").strip()}
    text = re.sub(r"\([^)]*\)", " ", text or "")
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return {"city": "", "state": "", "neighborhood": (neighborhood or "").strip()}
    remainder, state_part = split_state(parts[-1])
    if state_part:
        city_part = remainder or (parts[-2] if len(parts) >= 2 else "")
    else:
        city_part = parts[-1]
    city_part = re.sub(r"\b(area|unincorporated)\b", "", city_part, flags=re.I).strip()
    return {"city": city_part, "state": state_part, "neighborhood": (neighborhood or "").strip()}


def location_key(loc):
    city = re.sub(r"[^a-z0-9]+", "_", (loc.get("city") or "unknown").lower()).strip("_")
    state = (loc.get("state") or "").lower()
    return f"{city}_{state}" if state else city


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
