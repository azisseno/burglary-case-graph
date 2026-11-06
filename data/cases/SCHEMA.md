# Case data layout

Every series is a folder. Every incident inside it is a folder. Evidence files live beside a structured record of the public facts.

```
data/cases/
  <series-slug>/
    series.json
    <incident-slug>/
      record.json
      record.txt
      photos/
        <file>.jpg
        sources.txt
      audio/
        <file>.mp3
        sources.txt
      documents/
        <file>.pdf
        sources.txt
```

Slugs are lowercase, hyphenated, ASCII. Series slug: `<city>-<theme>-<year>`, for example `seattle-athlete-homes-2025`. Incident slug: `<series-short>-<nn>`, for example `sah-01`, numbered in date order.

Only create `photos`, `audio`, or `documents` when there is at least one file. Each of those folders has a `sources.txt` with one line per file: `<filename> <tab> <source URL> <tab> <publisher> <tab> <one line description>`.

## series.json

```json
{
  "series_id": "seattle-athlete-homes-2025",
  "label": "Athlete and entertainer home burglaries, Seattle area, 2025",
  "area": "Seattle, Maple Valley, Capitol Hill, WA",
  "period": {"start": "2025-01-01", "end": "2025-06-30"},
  "scene_types": ["residence"],
  "sources": [{"url": "https://...", "publisher": "King County Prosecuting Attorney", "date": "2025-08-01", "kind": "press_release"}],
  "ground_truth": {
    "status": "linked_by_police",
    "linked_incidents": ["sah-01", "sah-02"],
    "unlinked_incidents": ["sah-09"],
    "linking_evidence": ["vehicle description shared across scenes", "jewelry recovered at resale store"],
    "notes": "Outlets disagree on the date of sah-03. Police would not say whether the two defendants worked together."
  },
  "outcome": {"summary": "Two defendants charged; jewelry recovered Aug 2025", "date": "2025-08-01"},
  "data_policy": "Public sources only. No suspect or victim names, ages, or exact addresses."
}
```

`ground_truth.status` is one of `linked_by_police`, `partly_linked`, `not_linked`, `unknown`. It records what the public sources say, never our own inference. Incidents that police never tied to the series go in `unlinked_incidents` so the demo can test over-linking.

## record.json

Same shape as the team's existing evidence.json, extended with a series reference and media list.

```json
{
  "id": "sah-01",
  "series_id": "seattle-athlete-homes-2025",
  "date": "2025-02-14",
  "time": "02:30",
  "time_precision": "reported",
  "location": "4200 block of SW Morgan St, Seattle, WA",
  "location_precision": "block",
  "scene_type": "business",
  "evidence": [
    {"type": "forced_entry", "description": "Evidence of break-in", "provenance": "SPD public report", "source_url": "https://..."},
    {"type": "vehicle", "description": "Dark SUV seen on camera leaving the scene", "provenance": "SPD public report", "source_url": "https://..."}
  ],
  "items_taken": ["jewelry", "cash"],
  "unknowns": ["tool identity", "surveillance availability"],
  "media": [{"path": "photos/still-01.jpg", "kind": "surveillance_still", "source_url": "https://...", "publisher": "Fairfax County Police"}],
  "notes": "Date differs between two outlets; the earlier date is used here."
}
```

Evidence `type` values: `forced_entry`, `entry_damage`, `safe_access`, `alarm`, `theft`, `vehicle`, `tool`, `clothing`, `footage`, `witness`, `fingerprint`, `dna`, `phone_location`, `plate_reader`, `property_recovered`, `document_found`, `other`. Use `other` with a clear description when nothing fits.

`time_precision` is `reported`, `approximate`, `window`, or `unknown`. `location_precision` is `block`, `neighborhood`, or `city`.

## record.txt

A plain text version of the same record for people and for the extraction demo, in this order: header line with id, series, date, time, location, scene type; then one line per evidence item; then items taken; then unknowns; then source URLs; then notes. Our own words, no article text copied.

## Rules

- Public sources only. Government sources first for media: police, sheriff, prosecutor, city, DOJ. News images are not downloaded; link them in `sources` instead.
- No suspect or victim names, ages, or exact street addresses anywhere. Block or neighborhood level only.
- No invented values. Unknown fields are `null` in JSON and `not reported` in text.
- Every evidence item has a source URL.
