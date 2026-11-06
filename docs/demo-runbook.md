# Demo runbook: two folders and Renton

Every timing and number below comes from one full run on the real Claude CLI path on 6 November 2026, driven in the browser with the buttons on the cards. Times are seconds after the drop. Hypothesis ids (H-0001 and so on) and wording change between runs, so find each proposal by the series it links, not by id. Screenshots from this run are in `docs/demo-shots/`.

## Before you start
1. Reset to empty (see Rehearsal), then run `bin/dev` and open http://127.0.0.1:8000/. The graph must say "Empty graph. Drop a folder of reports to begin" and the agent console "0 events".
2. Browser window 1440 wide, hard reloaded (Cmd+Shift+R) so it has the current page.
3. A Finder window beside the browser showing `data/demo-folders` (folder-1, folder-2) and `data/demo-inputs` (renton-a, renton-b). Every input is a drag from Finder onto the drop zone at top left.
4. **Never reload the page during the demo.** The graph and cards come back, but the agent console starts empty.
5. Do not click anything for the first 10 seconds after a drop. The graph is still arranging itself.
6. **Wait for the next steps before the next click.** After each Accept, a "next steps" list arrives 10 to 15 seconds later and the review panel redraws and jumps. A click made in that window can land on the wrong button.
7. The cards are long. To reach Accept, Reject and More, scroll the review panel down past the critic's reasons on that card.

## Script

| Step | Do | Expected | Say |
|---|---|---|---|
| 1 | Drag `folder-1` onto the drop zone | First case at 10s, then case nodes with their places, vehicles and dates appear one by one. All 53 by 139s. Header shows the run timer. | "Fifty three police reports from different departments, dropped in as one folder. Nobody has told the system which belong together." |
| 2 | Wait for "Finder reviewed 6 clusters and found 5 hypotheses" at about 212s | Orange hexagons with dashed lines appear from 156s. Strip: 5 proposed, "5 of 5 proposed". | "The system grouped reports that look alike. One agent argued each group, a second agent challenged it. Five groups came out, and all five match series the police linked." |
| 3 | Accept the **Renton restaurants** (2 cases, 0.60, critic holds) | Camera closes in, a green Series node forms. Strip: 1 accepted, 2 cases. Next steps arrive about 12s later. | "Two restaurants in Renton. Both times a stolen black Jeep was backed through the glass front. That method is rare. I take it." |
| 4 | Click the **NEW-048** chip on the Renton card | The detail drawer at bottom right shows report.txt and a police camera still. The card also shows the still. | "Each case keeps its sources. This is the camera still released with the report." Point at the photo in the drawer. |
| 5 | Accept **New Orleans businesses** (3 cases, 0.55, critic holds) | Second green Series node. Strip: 2 accepted, 5 cases. | "Three businesses in New Orleans in five days, forced doors, and a white Nissan Xterra in every report. I take that too." |
| 6 | Reject the **Long Beach commercial** group (4 cases, 0.60, critic weak) | Card turns red, "Rejected by detective". Strip: 4 proposed, "4 of 4". | "Four Long Beach businesses, front door, cash or electronics. That describes half the burglaries in any city. The critic calls it generic and I agree. Not yet." |
| 7 | Leave **Lower Moreland** (3 homes, 0.65, weak) and **New Canaan** (3 homes, 0.50, weak) pending | Both stay amber. | "These two I park. The critic says the evidence is thin, and I want more before I sign." |
| 8 | Drag `folder-2` onto the drop zone | 52 more cases (105 total). Last case at 116s. Proposals from 140s. "Finder reviewed 9 clusters and found 6 hypotheses" at about 192s. Strip: 10 proposed, "10 of 10". | "A second batch arrives. The question is whether the first findings hold and what the new reports add." |
| 9 | Accept **Renton** (4 cases, 0.70, holds) | Camera closes in on Renton. The existing Renton series absorbs the two new cases. Strip: 3 accepted, 7 cases. | "Two more Renton businesses, the same Jeep method, days apart. They join the series I already own." |
| 10 | Wait for next steps, then accept **Rochester restaurants** (2 cases, 0.55, holds) | Third green Series node. Strip: 4 accepted, 9 cases. | "This one is new. Two restaurants in northwest Rochester, two days apart, a saw used to get at the cash, a bicycle at both." |
| 11 | Leave the other four pending: **New Orleans** (6 cases, 0.50, weak), **Lower Moreland** (6, 0.70, weak), **New Canaan** (4, 0.55, weak), **Long Beach** (6, 0.50, weak) | All stay amber. | "Bigger groups, but the critic still finds the shared facts ordinary or second hand. I leave them for now." |
| 12 | Drag `renton-a` onto the drop zone | Console shows the report and two still thumbnails at once. Photo notes by 31s. One proposal at 83s, critic holds at 94s, "Run finished in 93.9s with 1 hypothesis". | "One new report arrives alone: a short note and two camera stills. Watch where it lands." Point at the thumbnails in the console. |
| 13 | Scroll the review panel to the card with the **NEW-106** chip and two photos (it is in the middle of the list, not the top). Accept it (5 cases, 0.60, holds) | Camera closes in on the Renton cluster, then eases out. Strip: 106 cases, 11 proposed, 5 accepted, 10 cases, "11 of 11". | "A fifth storefront, the same method, within days of the others. This series was built from reports that arrived separately." |
| 14 | Click the **NEW-106** chip | Drawer shows the report and both stills. | "And here are the two stills it came in with." |

## What to accept, what to reject
- **Accept** proposals the critic marks "holds". In this run all of them matched the police record: Renton (three times as it grew), New Orleans with three cases, and Rochester.
- **Reject** the Long Beach commercial group. It rests on a front door and cash or electronics, which are common.
- **New Orleans with six cases came back weak** in this run, even though the three-case version held. The critic noted that no report says how the Xterra relates to the break-ins. I left it pending. If you prefer to accept it as an extension of the series you already own, say so plainly: "the critic is cautious here, I take it because it extends a series I already accepted."
- **Be honest on a weak true link.** Every weak proposal in this run, including Long Beach, matched the police record. Do not claim the critic was wrong. Say: "The critic flags thin evidence and the detective decides."
- **Leave pending** anything weak you do not want to reject. Pending proposals do not count as accepted.

## Honest limits to keep in mind
- The confidence on each card is the linking agent's own rating, not a probability. The card says so.
- "Series accepted" on the strip counts accepted proposals. At the end it says 5, but the graph has 3 series nodes (Renton, New Orleans, Rochester), because Renton was accepted three times as it grew. Say "five proposals accepted, three series".
- "Matching a police-linked series" means the proposed group is part of a series the police linked. It does not mean the police confirmed the agent's reasoning.
- The number of police series touched (3 of 14) is not on the strip. Quote it only if asked.
- The system makes no claim about who did it. The critic and the next steps say this in their own words.

## Final numbers from this run
- Tests: 128 passed.
- Folder 1: 53 cases, 6 clusters reviewed, 5 hypotheses, 212.0s. Accepted 2, rejected 1, pending 2.
- Folder 2: 105 cases, 9 clusters reviewed, 6 more hypotheses, 191.8s. Accepted 2 more, 6 pending in total.
- Renton A: 106 cases, 1 hypothesis, 93.9s.
- Final strip: 106 cases in graph, 11 proposed, 5 accepted, 10 cases in accepted series, 11 of 11 proposed match a police-linked series.
- From the API only: 5 of 5 accepted agree, 3 of 14 known series touched, 3 series nodes.

## Camera moments
For the 60 to 90 second video, these are the stretches worth recording. Times are seconds after each drop or click.

1. **Empty graph, then folder-1 lands** (0 to 25s after the drop). Cases pop in with their places, vehicles and dates around them. Shot: `01-empty-graph.jpg`, `02-first-cases-landing.jpg`.
2. **First proposals** (about 156 to 165s after the folder-1 drop). Orange hexagons and dashed lines appear across the graph. Shot: `03-folder1-proposals.jpg`.
3. **Renton series forms** (0 to 3s after the first Accept). Camera closes in and the green Series node appears. Shot: `04-renton-series-accepted.jpg`.
4. **A police still in the drawer** (click NEW-048). Shot: `06-renton-photo-in-detail-drawer.jpg`.
5. **Renton A arrives with its stills** (0 to 15s after the renton-a drop). The console shows both thumbnails. Shot: `10-renton-a-landing-with-stills.jpg`.
6. **Renton A joins the series and the strip moves to 11 of 11** (0 to 8s after the last Accept). Shots: `12-renton-a-accepted-closeup.jpg`, `13-final-metrics-and-renton-a-photos.jpg`.

Avoid recording the graph at full overview after folder-2. At that zoom the labels shorten to "NEW-0..." and it reads as a tangle.

## Rehearsal
- Fast import skips the Claude CLI and reads each incident's `record.json`. On the page press Shift+F, then 1 or 2 within two seconds (a hidden chord, there is no button). Or POST `/api/bulk` with `{"folder": "folder-1", "fast": true}`. The console says "fast import".
- The fast path gives different proposals and timings from the real run. In an earlier run folder 1 took 58s and gave 7 proposals. Use it to rehearse clicks, never to quote numbers.
- Reset to empty: stop the server, delete `runs/graph.json` and `runs/audit.jsonl`, run `bin/dev` again.
- A second server on another port must start with `CASE_GRAPH_API=http://127.0.0.1:<port>`. Without it the linking agent queries the server on port 8000.

## If something goes wrong
- **A run.error line in the console.** None appeared in this run. If one does, say "one of the agents timed out, I will run it again". Reset and start the folder again. If it fails twice, press Shift+F then 1 or 2 and tell the audience this is a stored extraction.
- **Broken image icons in the console during a folder drop.** In this run every console thumbnail failed to load during folder-1 and folder-2. The photos on the cards and in the detail drawer worked. Unless this has been fixed, do not point at the console during folder drops. Show photos through the NEW-048 chip instead. Renton A thumbnails in the console worked.
- **The strip says "10 of 10" after Renton A finishes.** In this run the right-hand number stayed at 10 of 10 until the Accept, while "series proposed" already read 11. Do not point at the strip until after you accept.
- **A click did nothing, or the panel jumped.** The next steps arrived and redrew the panel. Wait a few seconds, scroll back to the card and click again. Check the console shows "YOU ... accept" before you speak.
- **A hypothesis does not appear.** Wait until the console says "Finder reviewed N clusters". In this run the Renton proposal in folder-1 came last, 25 seconds before that message. If a series you planned to accept is missing after the message, accept the other holds and talk through the missing one as "the system chose not to propose this one yet".
- **The linking agent proposes nothing for Renton A.** Wait the full 2 minutes. If the run finishes with 0 hypotheses, say "the new report is too thin to link on its own" and move to the final numbers. Drag `renton-b` in once as a second attempt, never `renton-a` twice.
- **A folder of one incident** (files directly inside, like `renton-a`) runs as a single case. A folder of folders runs as a bulk import. The folder name becomes the run label in the console.
- **How long to wait.** Folder runs took 3 to 3.5 minutes. Wait 5 minutes before you decide anything is wrong, 7 before you move on. Renton A took about 1.5 minutes. Wait 2.5.
- **Different numbers.** Counts and critic verdicts can change between runs. In the earlier run New Canaan with four homes held and New Orleans with six held. In this run both were weak. Accept by series and critic verdict, not by count.
