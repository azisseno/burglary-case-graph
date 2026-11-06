# Demo runbook: two folders and Renton

Every timing and number below comes from one full run on the real Claude CLI path. Hypothesis ids (H-0001 and so on) and wording change between runs, so find each proposal by the series it links, not by id.

## Before you start
1. Reset to empty (see Rehearsal), then run `bin/dev` and open http://127.0.0.1:8000/. The graph must show 0 cases and "0 events" in the agent console.
2. Browser window 1440 wide, hard reloaded (Cmd+Shift+R) so it has the current page. Open the agent console and the review panel on the right.
3. A Finder window beside the browser showing `data/demo-folders` (folder-1, folder-2) and `data/demo-inputs` (renton-a, renton-b, decoy-cannabis). The page has no sample buttons, so every input is a drag from Finder.
4. Do not click anything for the first 10 seconds after a folder starts. The graph is still arranging itself.

## Script

| Step | Do | Expected | Say |
|---|---|---|---|
| 1 | Drag `folder-1` from Finder onto the drop zone | 53 cases appear one by one. Last case at about 98s. Review ends at about 155s. | "Fifty three reports from different departments, dropped in as one folder. Nobody has told the system which belong together." |
| 2 | Wait for "Finder reviewed 8 clusters and found 5 hypotheses" | 5 proposals. First ones show at about 115s. Strip: "5 of 5 proposed" match the police record. | "The system grouped reports that look alike. An analyst agent argued each group and a critic agent challenged it. Five groups survived." |
| 3 | Accept the Renton restaurants (2 cases, 0.60, critic holds) | Series node forms. Next steps appear in the console 10 to 15s later (12 items). | "Two restaurants, glass front rammed by a stolen black Jeep, five weeks apart. Strong method, same vehicle. I take that." |
| 4 | Accept the New Orleans businesses (3 cases, 0.60, critic holds) | Second series node. Strip: 2 accepted, 5 cases covered. | "Three forced doors in five days and the same white Nissan Xterra each time. I take that too." |
| 5 | Reject the Long Beach commercial group (4 cases, 0.55, critic weak) | Hypothesis greys out. Strip: "4 of 4 proposed". | "Four Long Beach businesses, forced front door, cash or electronics. That describes half the burglaries in any city. The critic says the evidence is generic and I agree. Not yet." |
| 6 | Leave Lower Moreland (3 cases, 0.60, weak) and New Canaan (2 cases, 0.55, weak) pending | Both stay amber. | "These two I park. The critic says the evidence is thin, and I want more before I sign." |
| 7 | Drag `folder-2` onto the drop zone | 52 more cases (105 total). Last case at about 87s. Review ends at about 157s. 6 new proposals, strip "10 of 10". | "A second batch arrives. The question is whether the first findings hold and what the new reports add." |
| 8 | Accept Renton (4 cases, 0.70, holds), New Orleans (6 cases, 0.60, holds), New Canaan (4 cases, 0.60, holds) and Rochester bicycle thefts (3 cases, 0.55, holds) | Series nodes stay at 4, not 7. Existing series absorb the new members. Strip: 6 accepted, 17 cases covered. | "The new reports join the series I already own. New Canaan was thin with two homes. With four, second floor entry and jewellery both repeat, and the critic now agrees. Rochester is new: a thief on a bicycle, three businesses." |
| 9 | Leave Lower Moreland (6 cases, 0.60, weak) and Long Beach commercial (6 cases, 0.50, weak) pending | Both stay amber. | "Bigger groups, but the shared facts are still ordinary. Leave them." |
| 10 | Drag `renton-a` onto the drop zone | About 70s. One proposal, 0.72, critic holds, linking the new case to four Renton cases (5 in total). | "One new report arrives alone, from a camera still and a short note. Watch where it lands." |
| 11 | Accept it | Camera closes in on the Renton cluster, then eases out. Strip: 7 accepted, "11 of 11 proposed", 18 cases covered, 4 of 14 series touched. | "A fifth rammed storefront, the same Jeep method. This series was built from reports that arrived separately." |

## What to accept, what to reject
- **Accept** proposals the critic marks "holds". In this run all of them agreed with the police record: Renton, New Orleans, New Canaan (four homes) and Rochester.
- **Reject** the Long Beach commercial group of 4. It rests on a forced front door and cash or electronics, which are common. The critic said weak for that reason.
- **Be honest on a weak true link.** The Long Beach group, New Canaan with two homes and Lower Moreland all matched the police record, yet the critic marked them weak. Do not claim the critic was wrong. Say: "The critic flags thin evidence and the detective decides."
- **Leave pending** anything weak that you do not want to reject. Pending proposals do not count as accepted.

## Final numbers from this run
- Tests: 127 passed.
- Folder 1: 53 cases, 5 hypotheses, 154.6s. Accepted 2, rejected 1, pending 2.
- Folder 2: 105 cases, 6 more hypotheses, 157.0s. Accepted 4 more, pending 4 in total.
- Renton A: 106 cases, 1 hypothesis, 69.6s.
- Final: 11 proposed, 11 agree. 7 accepted, 7 agree. 18 cases covered. 4 of 14 known series touched. 4 series nodes.

## Rehearsal
- Fast import skips the Claude CLI and reads each incident's `record.json`. On the page press Shift+F, then 1 or 2 within two seconds (a hidden chord, there is no button). Or POST `/api/bulk` with `{"folder": "folder-1", "fast": true}`. The console says "fast import".
- What differs on the fast path: folder 1 took 58s, not 155s. It gave 7 proposals, not 5, and strip read "6 of 7" instead of "5 of 5". The extra groups were Fairfax Hybla Valley (3 cases, 0.70, holds), New Canaan (3 cases), and a 12 case Long Beach group (weak). Use it to rehearse clicks, never to quote numbers.
- Reset to empty: stop the server, delete `runs/graph.json` and `runs/audit.jsonl`, run `bin/dev` again.
- A second server on another port must start with `CASE_GRAPH_API=http://127.0.0.1:<port>`. Without it the analyst agent queries the server on port 8000.

## If something goes wrong
- **A run.error line in the console.** Say "one of the agents timed out, I will run it again". Reset and start the folder again. If it fails twice, press Shift+F then 1 or 2 and tell the audience this is a stored extraction.
- **A hypothesis does not appear.** Wait until the console says "Finder reviewed N clusters". Proposals can arrive up to 40s before that message. If a series you planned to accept is missing after the message, accept the other holds and talk through the missing one as "the system chose not to propose this one yet".
- **The Linker proposes nothing for Renton A.** Wait the full 90s. If the run finishes with 0 hypotheses, say "the new report is too thin to link on its own" and move to the final numbers. Drag `renton-b` in once as a second attempt, never `renton-a` twice.
- **A folder of one incident** (files directly inside, like `renton-a`) runs as a single case. A folder of folders runs as a bulk import. The folder name becomes the run label in the console.
- **How long to wait.** Folder runs: 3 minutes before you decide anything is wrong, 6 minutes before you move on. Renton A: 2 minutes.
- **Different numbers.** Counts may differ by one or two proposals from this run. Accept by series and critic verdict, not by count.
