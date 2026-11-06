import re

SCRUBS = [
    (r",? which NOPD says connects this incident to the others", ""),
    (r"[;,] police compared it with witness accounts to connect the cases", ""),
    (r"Witness accounts compared by police with video to connect the cases", "Witness accounts were taken"),
    (r"[;,] police say video was used to identify the suspect responsible for the burglaries", ""),
    (r"A fingerprint on an office drawer came back as an apparent match to the Seattle man", "A fingerprint was lifted from an office drawer"),
    (r"; the crime lab matched it to the Seattle man", ""),
    (r"The same car appeared", "A car appeared"),
    (r"Cell tower records allegedly placed the car owner's phone moving from one crime scene to the other", "Cell tower records allegedly placed a phone at the scene"),
    (r"Entry through the second floor, the pattern of the series\.", "Entry was made through the second floor."),
    (r"Home Depot security video", "a retail store's security video"),
    (r", published with a KOMO photo caption", ""),
    (r", including a custom Sounders ring and a Seahawks ring believed to belong to the entertainer", ""),
    (r" that police say shows the suspect involved in the burglaries; two stills published", " showing the suspect"),
    (r"NOPD classes it as an burglary", "police class it as a burglary"),
    (r"NOPD classes it as an attempted burglary", "police class it as an attempted burglary"),
    (r"\bNOPD\b", "police"),
    (r"an burglary", "a burglary"),
    (r" where the defendant had reportedly been staying", ""),
]

UNKNOWN_DROP = re.compile(r"fps-|\bothers\b|versus|caption|published|identity of the original group|which store matches", re.I)


def scrub(text):
    for pattern, replacement in SCRUBS:
        text = re.sub(pattern, replacement, text)
    return text.strip().rstrip(".")
