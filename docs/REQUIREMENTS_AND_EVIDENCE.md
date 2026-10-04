# FinTech Problem 2: requirements and evidence

The authoritative source is the latest supplied [HacKU 2026 Problem Statements](problem-statements/HacKU_2026_Problem_Statements.pdf), **Financial Technology Problem 2 — Recognise Value That Gets Overlooked**. The separate [planning PDF](problem-statements/FinTech_Problem_2_Planning.pdf) is the team's early interpretation, not additional organizer requirements.

## Required scope

The organizer asks teams to identify overlooked value, define what is contributed/exchanged and who benefits, state a fairness rule, demonstrate a disagreement/withdrawal/imbalance, show consistent operation across more than one case, explain who the rule protects and costs, and state where it breaks. A currency, token or blockchain is explicitly unnecessary.

| Required element | Campus Commons answer | Observable evidence | Boundary |
| --- | --- | --- | --- |
| Overlooked value | Idle equipment, space, skills and people capacity. | Published resource type, capability, owner, availability and capacity. | Ownership and availability are entered by demo users. |
| Economic activity | Temporary resource sharing can replace external rental or repeated procurement and reduce coordination. | Bookings, sharing hours and reference-cost estimates. | No real-user savings or payment settlements are established. |
| Contributions and beneficiaries | Providers supply capacity; borrowers gain access; organizations accumulate contribution and reliability records. | Organization profiles, availability/share events and credit events. | Reliability credit is not financial credit or money. |
| Fairness rule | Five-input ranking, then each Mission's ranked complete plans, with time/capacity eligibility checks. | Decision snapshots, preferences, policy weights and booked resources. | Greedy allocation is not a globally optimal solver. |
| Disagreement/withdrawal/imbalance | Resource competition and waitlisting, requester withdrawal, unavailable resources and compensation disputes. | Real Mission states, released reservations, credit penalties and dispute resolution. | Some teaching narratives differ from live actions; use source/README for actual behavior. |
| Multiple cases | Repeatable live competition and withdrawal tests, plus four scripted teaching scenarios. | Business records and decision history from live tests; animated explanatory frames. | Teaching report assertions are not executed allocation assertions. |
| Trade-offs and failure conditions | Protect low-access/low-alternative requests while acknowledging cost to others, scarcity and inaccurate inputs. | Explain using fairness components and the cases below. | Current data is demonstration data, not a field evaluation. |

## Repeatable live evaluation

Use a fresh local SQLite demo or a dedicated shared test database. Live actions change records. Log in as admin through **Alt/Option + Shift + A** using the private configured/local generated password. Record the resource ID, Mission IDs, cutoffs, preferences, outcomes and history for each case.

### Case 1: two organizations compete for one resource

1. Under a provider organization, publish an equipment resource with capacity **1**, capability **camera, 4K video**, and a future availability covering the entire requested period.
2. Choose a period outside the seed resources' availability so the new camera is the only feasible camera. Check each generated plan; do not assume this from its name.
3. Under two different requester organizations, submit **camera** Missions for the same period. Save the acceptable camera plan preferences for both.
4. Show that both Missions are open and no booking exists before allocation. Compare the organizations' fairness inputs; use a non-suspended provider/requester.
5. Run **Dashboard → Run allocation batch** for an immediate demonstration. Explain that this manual action overrides cutoff; it is not evidence that the automatic scheduler fired.
6. Inspect decisions and booking records: one Mission is allocated, the other waitlisted; the capacity-one resource must not be allocated twice for the overlapping interval.
7. Explain which inputs account for priority. If scores tie, deadline is the implemented tie-break; do not imply randomized allocation.

### Case 2: withdrawal releases capacity for the waitlist

1. Continue Case 1. As the winning requester, withdraw the allocated Mission.
2. Show the withdrawn state, released booking and live **−3** requester credit event.
3. Run another manual batch. The previously waitlisted Mission can now acquire the resource if it remains eligible and its accepted plan is feasible.
4. Show the new booking, both decision snapshots and withdrawal history. A release alone does not promise automatic immediate reassignment.

These two cases exercise the actual engine and persistent state, unlike the animation. Capture the observed outcomes during your evaluation; this document does not claim an unrecorded production test has already passed.

### Optional: automatic cutoff scheduling

Use **Demo studio → Scheduler and policy settings**, choose **Automatic**, set an interval and save. A shorter cutoff can be supplied through the Mission API for a controlled test; the normal UI defaults to usage start minus 24 hours. Leave the backend running. Verify no normal batch allocates before cutoff and check the result after the next scheduler interval. Settings changes may wait until the previous sleeping interval ends. Do not press the manual Run button during this check. Restore Manual afterward if several collaborator backends share the database.

### Optional: evidence and compensation dispute

After an allocated Mission, submit a provider fault dispute with an evidence file and positive requested compensation. Admin review can approve the compensation, penalize/freeze the provider and place the dispute in `awaiting_victim`. The affected organization confirms resolution; verify the dispute is settled and the provider is unfrozen only if no other approved compensation dispute remains unresolved. Inspect private evidence through the admin endpoint. This records compensation status; it does not transfer funds.

## Teaching demonstration

Admin **Demo studio** contains competition, withdrawal, provider failure/replacement and preference-order scenarios. Recording view and local playback make the sequence visible without a cloud round trip per frame. Reports use illustrative participants, outcomes and assertions. They do not perform those transactions against live business tables. The regression test checks report consistency and business-data isolation, not the correctness of a scripted winner.

## Trade-offs and failure conditions

- The rule protects low-access organizations and requests with fewer alternatives or imminent cutoffs, while recognizing contribution and reliability. An earlier applicant, high-credit organization or applicant with many alternatives can lose a preferred resource.
- New organizations have a favorable initial access component but little contribution history. There is no automatic below-70 credit exclusion; explicit suspension controls eligibility.
- Greedy fairness ordering may satisfy fewer requests than a global optimization. Limited plan generation and keyword parsing can omit good alternatives.
- Self-reported availability, capabilities, costs and urgency can be wrong or manipulated. The MVP does not independently verify identities or physical resources.
- Chronic scarcity cannot be solved by score weights. When every request is urgent, the rule still must deny some requests.
- Process-local locking does not prevent concurrent allocation by separate backends. One active scheduling backend and a running host are required for the prototype; a database-coordinated worker is future work.

## Economic evidence status

No real users have validated cost or coordination savings. Impact values use demonstration bookings, reference costs and a fixed time-saving assumption. Do not describe these as proven business outcomes. The proposed free-access → advertising/sponsorship → optional premium-tools roadmap is a future plan; no monetization module or revenue is implemented.

## Engineering verification

See [README validation](../README.md#validation-and-troubleshooting). The current 24-test suite covers adapters, transaction lifecycle, launcher/diagnostic behavior, serializer equivalence, query-count stability and isolated reports. Local HTTP verification covered a complete resource-to-Mission-to-allocation path. These engineering checks and live evaluation instructions support review but do not substitute for a real-user study or production concurrency evaluation.

## Recorded local business-flow verification

On **2026-10-04**, the unchanged allocation implementation was exercised against a fresh temporary SQLite database, separate from the public site and shared cloud project. The fixture used a camera with capacity 1, two different requester organizations, one accepted plan each, and overlapping usage windows outside seed-resource availability. Manual `force=True` batches were used; this does not verify automatic scheduler timing.

| Case | Observed outcome |
| --- | --- |
| Competition | One Mission allocated, one waitlisted; exactly one active booking for the capacity-one camera. |
| Withdrawal and reconsideration | Winning requester withdrew; active booking count became zero and credit fell by 3. A subsequent batch allocated the waitlisted Mission and restored exactly one active booking. |

These checks exercised the real business functions and database records, rather than scripted Demo frames. They establish these two local cases only, not successful production cloud access, multi-backend concurrency or real-user value.
