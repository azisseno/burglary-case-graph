import re

MARKER_PATTERN = re.compile(r"</?case_data>|<<<EVIDENCE|EVIDENCE>>>|</?hypothesis_data>", re.IGNORECASE)


def defang(text):
    return MARKER_PATTERN.sub(lambda match: f"[{match.group(0).strip('<>/')}]", str(text))
