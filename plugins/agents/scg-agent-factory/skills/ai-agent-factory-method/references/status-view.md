# Project progress template

Use this bundled template for one maintained progress page per project or
delivery scope. It also works without a Factory team. Keep existing ownership
and the owning backlog. The page presents work; it does not authorise it.

## Create or reuse the page

1. Find the existing page and its source. Reuse their stable locations.
2. For a new page, copy [blank.json](../assets/status/blank.json) into the project's output folder.
3. Map the owning work records into that file. Keep their stable IDs and source links.
4. Fill the outcome, owner, next step and first observable requirement for each item.
5. Build the page with the bundled helper:

```sh
python3 <skill-folder>/scripts/build_status.py --data <project-output>/status.json --output <project-output>/status.html
```

The helper uses the Python standard library. It creates one HTML file with
its data, style, behaviour and screenshots inside. No server, network request
or other skill is required to display it. Keep this durable file even when
the host supports an HTML artifact. Update the same artifact where the host
supports that operation; otherwise link the local file. Test the actual host
before claiming artifact support.

Keep generated project data outside this reusable package and outside product
commit history. Record its location in the existing project state. Changes to
the renderer belong in this plugin, not in individual project copies. Existing
product source adapters stay with their projects.

[example.json](../assets/status/example.json) demonstrates the fields with
synthetic records. It is not a starter for real reporting. The builder and
renderer reject example records outside template mode.

## Keep the page easy to read

The first screen answers: What will this give me? Can I use it? What needs my
input? What happens next? Use three views: `Overview`, `Your input`, `All work`.
The overview shows human questions first, four progress counts, active team
work and up to three recent changes. Further questions remain in `Your input`.

Write for someone who builds with AI and knows little software terminology.
Use concrete actions and familiar words. Say `test version`, `ready to publish`
and `user check`. Keep identifiers, commits, test runs and internal coordination
out of the main view. Do not expose an agent roster as an organisation chart.

Each card has a short outcome, one owner and one next step. Name an agent owner
plainly, such as `Engineering (agent team)`. Selecting the card opens its full
explanation. Keep task IDs, detailed ownership and evidence under the closed
`Technical details` control. Missing optional sections need no filler text.

Human input is explicit. Put a genuine reserved decision, user check or
person-only blocker in `decisions` with `audience: "human"`, its named owner
and exact question in `text`. Add short context and choices when useful.
Record the answer in `result` when it arrives. Routine agent work, missing
proof and incomplete metadata do not become questions for the user.

## Preserve the evidence

Use schema version 1 and the established feature fields. Unknown facts stay
empty or `Not recorded`; do not invent owners, dates, release or acceptance.

| Record | Required meaning |
| --- | --- |
| `project` | Title, specific outcome, source link and actual last evidence check in `checked`. Name the live environment; default is `Production`. |
| `id`, `title`, `outcome` | Stable source ID, useful result and who benefits. |
| `scope`, `kind` | `active`, `deferred` or `replaced`; `implementation` or a separate `acceptance` task. |
| `build` | `Not recorded`, `Planned`, `Building`, `In review`, `Merged`. Merged means saved in the team's shared source. |
| `releases` | One record per environment: state, intended audience, exact revision and evidence. |
| `acceptance` | State, named human checker in `owner`, `acceptedAt` timestamp, environment, matching release revision and evidence. |
| `owner`, `nextAction`, `nextActionOwner` | One accountable owner, one concrete next step and who acts next. |
| `target`, `blocker`, `dependencies` | Only agreed dates, actual blockers and linked dependencies. Preserve the last known build state. |
| `criteria` | Observable requirements with stable IDs, recorded result and supporting evidence. |
| `tasks`, `commits`, `checks`, `evidence` | Source work and technical proof. Evidence entries contain `label` and an HTTPS `url` or a precise local `reference`. |
| `decisions` | Question in `text`, named owner, human/team audience, agreed due date if any, result and reason. |
| `screenshots` | Local image, description, environment, capture date, revision and the requirement it illustrates. |
| `sourceState`, `note` | Preserve the source's original state and explain any mapping. |

Release states: `Not recorded`, `Not released`, `Partial`, `Released`, `Rolled back`.
User-check states: `Not recorded`, `Pending`, `Accepted`, `Reopened`.

`Done` requires a named person's recorded acceptance, passed requirements and
the matching complete live release. Copy acceptance only from that person's
record. The agent's tests, screenshots or opinion cannot supply it. Missing
acceptance dates and placeholder evidence cannot establish completion. A blocker
or open dependency prevents Done even when an older acceptance record exists.
Verify the referenced source itself. A valid-looking link or path alone is
not proof. Local references display as text and must remain available to readers.

Count active implementation features separately from user-check and build tasks.
Keep unknown, deferred and replaced work visible without counting them as done.
Preserve separate build, release and user-check records; never combine them
into one completion percentage. For non-code work, explain the equivalent
artifact/version mapping once in `project.sourceMapping`.

Keep source check time separate from page update time. Set `project.staleDays`
only when the project has an agreed evidence review window. Do not invent
deadlines or refresh timestamps to clear a warning.

Use PNG, JPEG or WebP files under `img/` or `screenshots/` beside the data file.
The builder embeds them. Use actual screenshots with approved test data. Label
mockups and synthetic data. A picture alone proves neither availability nor
correctness. Remove secrets and private data before sharing.

## Maintain and verify

At completed milestones and commits, reconcile source records and refresh
changed reader-visible facts. Include review, integration, release, acceptance,
scope changes and handoffs. Batch interim activity. Idle projects need no
status-only work. Never create an update loop from the generated page itself.

Check the saved output after each change: source parity, counts, human questions,
tabs, filters, empty states, detail panels and evidence. Check desktop and phone
widths, light and dark modes, keyboard access and long text when changing layout.
Invalid records must show an error, not stale success. A rebuilt page does not
prove the source or evidence was checked again.

Use the existing authorised delivery surface and audience for shared pages.
Read back the actual published view. A local edit does not update a shared page.
Keep urgent faults and questions in chat; the final report still states the
outcome, material limits and next action, with a link to the page.
