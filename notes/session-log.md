# Bob (plugin) — Session Log

## 2026-09-03 — Designing a feedback loop for a product that phones nothing home

**What we built.** Nothing shipped; the deliverable was a design. Once someone installs the Bob
plugin, Rachel sees nothing about what they do with it, and the only feedback path Bob offers is one
landing-page link that says "Something broke → open an issue." We designed `/bob-feedback`: a short
interview Claude runs on the user's own machine, which classifies what it hears into one of five
kinds and routes it to the right place — without Bob ever transmitting anything on its own. The
design is written up at `notes/specs/2026-09-03-bob-feedback-design.md`; sections 1 and 2 are
approved, section 3 is drafted and still needs a read.

**Technical changes.** No code this session.
- `notes/specs/2026-09-03-bob-feedback-design.md` — new. The full design, with the open questions
  marked as open rather than resolved.
- `notes/` — new directory. `docs/` in this repo is the published GitHub Pages site
  (`docs/index.html` → rkroft.github.io/bob/), so internal notes cannot live there.

**Decisions & tradeoffs.**

- **Decision:** No telemetry. Nothing leaves the user's machine without them pressing send.
  **Why:** Bob's differentiator is a sentence — *"no server, no account, Bob's author holds nothing
  of yours."* An endpoint contradicts it, has to be defended, and at an install base in the dozens
  buys exactly one meaningful number (did they come back for a second scan); every other metric is
  noise at that sample size.
  **Alternatives:** opt-in anonymous counters (Cloudflare Worker + D1, ~$0–5/mo, 2–3 days); the same
  plus error text and volumes (4–5 days). The second was the tempting one, because a real traceback
  from a stranger beats fifty counters — but Bob raises errors while parsing mailboxes, so its
  tracebacks carry email addresses.
  **Tradeoff accepted:** silent churn is now structurally invisible. Anyone who installs Bob, hits
  friction and stops will never appear in any report. The design's only answer is one question —
  "what stopped you?" — asked of the subset who choose to speak.

- **Decision:** An interview, not a form. Claude reads local state first, asks at most three
  questions keyed to what it sees, then classifies — and the user confirms the classification rather
  than picking it up front.
  **Why:** Bob runs inside Claude Code, so the user is already mid-conversation with an agent that
  can read `intros.csv`. That turns "how was your experience?" into "who's missing from these 12?"
  Self-selecting a category at the start would collapse it back into a form.
  **Alternatives:** a plain `/bob-feedback` that opens a prefilled issue; better issue templates and
  nothing in the plugin at all.
  **Tradeoff accepted:** the report quality is now non-deterministic and depends on the model running
  the interview well. Harder to test than a form, and it can drift between model versions — hence the
  four scripted walkthroughs in section 3.

- **Decision:** Five categories — miss / mistake / break / snag / wish — and the category routes
  rather than describes.
  **Why:** each maps to a different fix location (detection heuristics / code / copy / roadmap) and a
  different required payload. `snag` was added mid-design because "I nearly gave up at setup" is
  neither a break nor a wish, and its fix is words, not code. The sharper half of this: the category
  also picks public-vs-private, because a miss reads as a contribution and a snag reads as an
  admission — filing a snag publicly is socially expensive, so it defaults private.
  **Alternatives:** four categories with friction folded into `wish`; merging miss and mistake into
  one "wrong" bucket.
  **Tradeoff accepted:** five labels to maintain, and a misclassification routes a report to the
  wrong place. The user-confirm step reduces that, doesn't remove it.

- **Decision:** Anonymize on the user's machine; only the fixture travels.
  **Why:** the highest-value contribution a user can make is an example of an intro Bob missed — and
  that is a real email, the most private artifact they own. Claude reads it locally, builds a
  structurally identical fixture with invented people, shows them both, and only the invented one
  moves. That is possible only because Bob runs inside an agent sitting on their machine.
  **Tradeoff accepted:** anonymization correctness became a safety-critical property with no
  server-side backstop. Section 3 makes it a test: no string from the source message's address fields
  or headers may appear in the fixture.

**Concepts in play.**
- *Custody as a product feature* — when the promise is the differentiator, a feature that weakens it
  costs far more than its build time.
- *Survivorship bias in feedback* — the people who quit never file. A feedback channel is a biased
  sample by construction; knowing which direction it's biased is the only real mitigation.
- *Compose → persist → transmit* — write the artifact to disk before attempting any network step, so
  a failed send never eats the user's typed text.
- *Router-not-label taxonomy* — a classification earns its keep when it changes downstream behavior
  (destination, required fields, who fixes it), not when it merely describes.
- *Progressive disclosure of consent* — showing the exact payload before it moves is itself the trust
  demonstration, not overhead on top of one.
- *Carrying cost of a channel* — an unanswered feedback channel is worse than no channel.

**Open threads.**
- Section 3 (report format, routing fallbacks, error handling, testing) is drafted and unapproved.
- `snag` as a fifth category: proposed, question asked, not answered.
- The dedicated feedback address was chosen in principle and does not exist yet.
- No implementation plan. `writing-plans` was never reached.
- Two adjacent quick wins untouched: `CONTRIBUTING.md`, and a landing-page CTA that speaks to anyone
  other than a user whose Bob broke.
- The five GitHub labels don't exist.
- The GitHub MCP server failed to connect this session ("Authorization header is badly formatted"),
  so the existing issues and labels were never actually read — the repo-state claims here come from
  the working tree and the landing page HTML, not from the GitHub API.

**Stories worth keeping.**
- *(product/AI → product-judgment)* — turning down analytics for my own product, on the arithmetic.
- *(product/AI → product-judgment)* — the feedback form that became an interview, because the product
  lives inside an agent.
- *(technical → story-bank)* — none. No code was written.
