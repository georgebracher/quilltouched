# 04 — Guilds & Professions

Scope: profession guilds as regulators (adventurer, merchant, smith, healer, scribe) — hall anatomy, F→SSS rank plates, scheduled quarterly rank-up trials, rank-gated legal permissions, and the deliberate gap between guild-certified KNOWN rank and System-minted titles (roadmap §3.11). **v1 (B1, Sprint 1): the adventurers' guild in full at Harrowdown depth; the other four guilds sketched.** Later sprints deepen the non-adventurer guilds and the Severwick seat.

## Guilds are regulators

Five chartered guilds operate in the kingdom: adventurers, merchants, smiths, healers, scribes. A guild does not hand out quests. It licenses who may do what, certifies quality it cannot always verify, and adjudicates when its members collide. Every guild is a KNOWN-sheet builder: its ranks, seals, and dossiers are institutional claims about people and things, and all of them can be wrong.

Presence in Harrowdown:

| Guild | Local presence |
|---|---|
| Adventurers | A hall on Market Row. One clerk, one board, no resident examiner. |
| Merchants | A Severwick factor visits on market days and issues stall tokens. |
| Healers | None. Nearest chapter house is Severwick. The vale uses hedge-craft and prays the wound is honest. |
| Smiths | None. The town farrier works uncertified, legally, below the guild-work threshold. |
| Scribes | None. Sister Odile does the town's letters, which the scribes' guild resents from four carriage-days away. |

## The Harrowdown hall

One room and a back office (`loc.harrowdown.guild_hall`). By the door, the **plate rail**: pegs where members hang their plates while inside — the rail is how a stranger reads the room in one glance. Along the north wall, **the board** (`prop.harrowdown.guild_board`), three columns: postings, warrants, notices. A **ledger desk** where Fenn Bracey (`npc.harrowdown.fenn_bracey`) keeps the rolls, the coin chest, and the proof-scales for bounty tails. In the corner, the **trophy nook**: a single wyvern tail-barb, mounted without a plaque. Members know what it cost. The back room takes contract signings and the quiet conversations that precede them.

## Registration (F plate)

Any hall, any day, 20 pennies plus a 50-penny plate deposit. The ritual is short and public: state a name for the roll, press an inked thumb beside it, and swear the three duties aloud —

1. Report what you saw, true.
2. Finish the posting or hand it back.
3. Answer a levy.

The clerk stamps an F plate then and there. The thumb-print matters more than the name; plenty of members registered under names their mothers would not recognize. The guild does not care. The guild cares whether the thumb comes back.

## The ladder: F → SSS

Rank is the guild's certified KNOWN, never a reading of true capability. It gates what a member may legally take on, and that is all it gates.

| Rank | Legal permissions |
|---|---|
| F | Parish postings: vermin, deliveries, escort within a day's walk. |
| E | Road escort between halls. Beast postings graded E or below. |
| D | May hold a posting alone. Beast postings to grade D. |
| C | May lead a registered party. Monster postings to grade C. Countersigns F registrations. |
| B | Cross-region postings. May post bounties on the board as a private party. |
| A | Named-threat warrants, with seat approval. Eligible to examine. |
| S | May command a royal levy. Sealed-site escort licenses. |
| SS | Standing warrant authority: may declare a named threat without a seat vote. |
| SSS | Charter tier. May close a road, a border, or a war. The charter lists three living holders; none has been seen in this kingdom in a generation. |

Grades on postings refer to the guild's own monster grading (`09-bestiary.md`), which is a KNOWN sheet with all the failure modes that implies. A D-grade posting can conceal a C-grade problem. The guild's liability rules exist because this happens.

**Rank dies with the holder.** Plates return to the hall; heirs start at F under whatever weight the surname carries. The guild certifies people, never bloodlines.

## Trials

Rank-up trials run once a season, at the seats, on the Quarterdays. For the vale that means Severwick, four carriage-days south. Exam fee is 100 pennies, forfeit on failure. The next trials sit **fifty-one days out** as of this file's world-date; the guild wagon leaves Harrowdown seven days before (see the board, `prop.harrowdown.guild_board`).

A failed trial is a witnessed deed. It travels home faster than the candidate does, and the vale has long memory for the difference between "failed the sword-court" and "failed the ethics chair." Members plan training blocks against the Quarterday calendar for exactly this reason.

## Two recognition systems

The System mints titles from witnessed deeds. The guild certifies rank from scheduled tests. They measure different things and they are allowed to disagree: the System may know a member as a wyvern-slayer while the guild holds them at D because they never sat an exam. The guild's official position is that its ledger is the one a magistrate will read. The System's position is not on record. The gap between the two is where most of the vale's adventurer stories live — including the ones about Jorun Pike (`npc.harrowdown.jorun_pike`), C plate, twenty years carried, who stopped sitting exams nine years ago and will not say which system he thinks was right about him.
