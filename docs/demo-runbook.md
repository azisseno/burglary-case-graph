# Demo runbook: two folders and Renton

Timings are from a real run on the Claude CLI path (haiku extraction). Hypothesis ids and wording differ between runs, so find each one by the series it links.

## Before you start
1. `bin/dev`, open http://127.0.0.1:8000/. The graph must be empty (see Reset below).
2. Window at 1440 wide. Open the agent console.

## Script

| Step | Click | Expected | Say |
|---|---|---|---|
| 1 | Folder 1 | 30 cases appear; about 90s to the last case, finder ends at about 110s. Camera stays wide, graph re-lays out every few seconds. | "These are 30 reports from different departments, dropped in as a folder. Nobody has told the system which ones belong together." |
| 2 | Wait for "Finder reviewed 5 clusters" in the console | 3 proposals. Strip reads "agrees with public record: 3 of 3". | "The system grouped cases that look alike, then asked an analyst agent and a critic agent to argue it. Three groups survived." |
| 3 | Accept the Renton restaurant rammings (2 cases, 0.55) | Cases pull into a series node, camera eases back out. | "Two restaurants, glass front rammed by a stolen dark SUV, five weeks apart. I take that." |
| 4 | Accept the New Orleans commercial burglaries (3 cases, 0.50, white Nissan Xterra) | Second series forms. | "Three forced doors in four days and the same white Xterra. Thin, but worth owning." |
| 5 | Reject the New Canaan pair (2 cases, 0.50) | Hypothesis greyed out. | "Same town, jewellery, upstairs entry, but the entry field says not reported. I will not sign off on that yet." |
| 6 | Folder 2 | 29 more cases; about 110s to finder end. Six clusters reviewed, 4 new proposals. | "Now a second batch arrives. Watch whether the first findings hold." |
| 7 | Accept the larger Renton proposal (5 cases, 0.70) and the larger New Orleans proposal (6 cases, 0.60) | Existing series absorb the new members (still 3 series nodes, not 5); cases covered goes from 5 to 14 after also accepting the New Canaan group of 4 (0.60). | "The new reports join the series I already accepted. The New Canaan pair I rejected comes back with two more cases, and now the pattern is there." |
| 8 | Renton A (single case) | About 75s. One proposal linking the new case to the five Renton cases. | "A single new report comes in on its own. It lands next to the Renton series." |
| 9 | Accept it | Camera closes in on the cluster, then eases out. Strip: 6 accepted, 6 of 6 agree with public record, 15 cases covered. | "A fifth rammed storefront. This is the series, built from reports that arrived separately." |

Critic verdict was "weak" on every proposal in this run. Say so: the critic is there to show what is missing, not to approve.

## Final numbers from the validation run
- Folder 1: 30 cases, 3 hypotheses, 3 of 3 agree, 108s.
- Folder 2: 59 cases total, 4 new hypotheses, 6 of 6 agree, 113s.
- After Renton A: 60 cases, 7 proposed, 6 accepted, 6 of 6 agree, 15 cases covered, 3 of 14 known series touched.

## Rehearsal
- Fast import skips the Claude CLI and reads each incident's `record.json`: press Shift+F then 1 or 2 on the page, or POST `/api/bulk` with `{"folder": "folder-1", "fast": true}`. The console says "fast import". Folder 1 took 40s and gave 4 proposals (not the same set as the real path), so use it for rehearsing clicks, not for quoting numbers.
- Reset to empty: stop the server, `rm runs/graph.json runs/audit.jsonl`, run `bin/dev` again.
- If you run a second server on another port, start it with `CASE_GRAPH_API=http://127.0.0.1:<port>`. The analyst agent reaches the graph through that variable and defaults to port 8000.
