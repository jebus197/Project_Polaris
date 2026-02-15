# Project Genesis
## The world's first intelligence-agnostic anti-social network.

**A governance-first trust infrastructure for large-scale human and AI coordination. Trust earned, never bought.**

---

Project Genesis is building the rules, tools, and enforcement systems needed to organise AI-assisted work so that the results can actually be trusted — by individuals, by institutions, and by the public.

This is not a chatbot. It is not a social platform. It is not a token or a blockchain product.

It is an institutional operating model — a way of governing how humans and AI systems work together on things that matter.

Owner and project lead: George Jackson

---

## The Problem

AI is getting more capable every year. But capability is not the same as trustworthiness.

Right now, if an AI system produces a report, writes code, or makes a recommendation, there is usually no reliable way to answer basic questions like:

- Who asked for this work?
- Who checked it?
- Were the checkers independent?
- Can I verify the process that produced it?
- Could someone have tampered with the record after the fact?

For casual use, these questions don't matter much. For serious work — healthcare, infrastructure, public policy, safety-critical engineering — they matter enormously.

Genesis exists to answer them.

## The Core Idea

The missing piece in AI is not smarter models. It is **institutional structure**.

Genesis wraps AI capability in a governance framework that provides:

1. **Mission-first coordination** — work is organised around defined goals with clear scope, risk levels, and success criteria, not around engagement metrics or throughput.
2. **Independent verification** — no one gets to mark their own homework. Critical work is checked by independent reviewers who are deliberately chosen to be diverse in method and perspective.
3. **Constitutional governance** — the rules of the system are written down, publicly available, and enforced by code. Changing them requires broad agreement from verified humans across multiple independent groups.
4. **Cryptographically secured records** — every significant action produces a tamper-evident record, cryptographically hashed and immutable. The full process history is auditable by anyone and anchored to a public blockchain.
5. **Earned trust, not purchased influence** — reputation in the system is built solely through cryptographic proof-of-work (evidence that real contribution occurred) and proof-of-trust (independent verification of quality over time).

## The Foundational Rule

This rule is constitutional and non-negotiable:

> **Trust cannot be bought, sold, exchanged, delegated, rented, inherited, or gifted.**
> **Trust can only be earned through verified behaviour and verified outcomes over time.**

If trust becomes tradeable, governance becomes a marketplace for influence. Genesis enforces this rule structurally — through cryptographic proof requirements, quality gates, and bounded trust economics — so that the only path to authority is sustained, independently verified contribution.

## How It Works

A typical Genesis mission follows this path:

1. A human defines the goal, scope, risk level, and what success looks like.
2. The work is broken into tasks with clear dependencies.
3. Workers (human or AI) complete tasks and attach cryptographically signed evidence of their work.
4. Independent reviewers check quality and compliance — they are deliberately selected from different AI model families and verification methods to avoid correlated errors.
5. Approved outputs are assembled into the final result.
6. For high-risk work, a human must give final sign-off before the mission closes.
7. Every significant step is hashed, signed, and recorded in an immutable audit trail.

The principle is simple: **no single actor should be able to produce, approve, and close their own critical work.** Every claim of contribution is backed by cryptographic proof-of-work. Every claim of quality is backed by independent proof-of-trust.

## Humans and Machines Have Different Roles

Genesis treats humans and AI systems as fundamentally different kinds of participants:

- **Machines** can earn operational trust — the right to take on more complex tasks, review lower-risk work, and contribute to missions. But they cannot vote on the rules of the system itself.
- **Humans** hold constitutional authority. Only verified humans can propose, debate, and ratify changes to the governance framework. This is not a temporary measure — it is a permanent architectural decision.

The reason is straightforward: the system that governs AI must not be governable by AI. Machines are workers and reviewers within the system. Humans are the legislators.

## Trust Is Bounded

Genesis does not allow unlimited trust accumulation. The trust economy has hard rules:

- Everyone starts with the same baseline trust.
- Trust grows only through cryptographically verified quality contributions — volume alone is not enough. Every trust increase requires proof-of-work evidence and independent proof-of-trust validation.
- There are hard caps on how much trust any single participant can hold, and how fast trust can grow.
- Trust decays over time if you stop contributing (gradually for humans, more quickly for machines).
- Large trust jumps are automatically flagged and require review by multiple independent humans before they take effect.
- Trust changes are recorded in Merkle trees and committed to the blockchain — creating an immutable, auditable history of how every participant's reputation was earned.
- High trust grants more responsibility, not more power. It does not give anyone command authority over others.

The design objective: **make gaming the system expensive, make concentration difficult, and keep legitimacy tied to contribution quality.**

## The System Cannot Be Captured

Genesis is built to resist takeover — by individuals, organisations, AI systems, or capital:

- Changing the constitution requires proposals backed by multiple high-trust sponsors, ratification by a supermajority of verified humans, and approval across three independent chambers whose members are selected at random (with diversity constraints).
- No single region, organisation, or actor can dominate any chamber.
- Financial capital has no role in trust, voting, or governance. You cannot buy your way in.
- There is a public challenge window before any constitutional change is finalised.
- All finalised constitutional decisions are permanently recorded using blockchain anchoring (explained below), making them publicly auditable by anyone.

## Blockchain Anchoring

### The idea

In 1991 — nearly two decades before Bitcoin — two researchers named Stuart Haber and W. Scott Stornetta published a paper asking a simple question: how do you prove a document existed at a particular time, without relying on anyone's word for it?

Their answer was to create a chain of cryptographic fingerprints — each one linked to the last — forming a permanent, tamper-evident record. This work was so foundational that it is cited in the Bitcoin whitepaper itself, and it gave rise to an entire field of cryptographic timestamping.

**Blockchain anchoring** applies this idea using a public blockchain. You take a digital fingerprint (called a hash) of a document and record it in a standard blockchain transaction. No code runs on the blockchain. No smart contract is involved. The blockchain simply acts as an independent, permanent, public witness — like a notary stamp that cannot be forged, altered, or backdated.

The technique has been in use since the early days of Bitcoin, through services like OpenTimestamps, Stampery, and OriginStamp. Genesis adopts and formalises it as a core governance mechanism — using it to anchor the foundational rules of the system to an immutable public record.

### The Genesis constitution: a worked example

The first document anchored in Genesis is its own constitution. This serves as both a governance act and a concrete demonstration of how anchoring works.

| Field | Value |
|---|---|
| Document | `TRUST_CONSTITUTION.md` |
| SHA-256 Hash | `33f2b00386aef7e166ce0e23f082a31ae484294d9ff087ddb45c702ddd324a06` |
| Chain | Ethereum Sepolia (Chain ID 11155111) |
| Block | 10255231 |
| Sender | [`0xC3676587a06b33A07a9101eB9F30Af9Fb988F7CE`](https://sepolia.etherscan.io/address/0xC3676587a06b33A07a9101eB9F30Af9Fb988F7CE) |
| Transaction | [`031617e3...`](https://sepolia.etherscan.io/tx/031617e394e0aee1875102fb5ba39ad5ad18ea775e1eeb44fd452ecd9d8a3bdb) |
| Anchored | 2026-02-13T23:47:25Z |

Every field above is publicly verifiable. The sender address links to the wallet's full transaction history on Etherscan. The transaction link shows the exact data that was recorded on-chain.

### How to Verify It Yourself

You don't need to trust this project to verify the anchor. You only need a terminal and a browser.

**Step 1 — Compute the fingerprint locally:**

```bash
shasum -a 256 TRUST_CONSTITUTION.md
```

Expected output:

```
33f2b00386aef7e166ce0e23f082a31ae484294d9ff087ddb45c702ddd324a06  TRUST_CONSTITUTION.md
```

**Step 2 — Check it against the blockchain:**

Open the [transaction on Etherscan](https://sepolia.etherscan.io/tx/031617e394e0aee1875102fb5ba39ad5ad18ea775e1eeb44fd452ecd9d8a3bdb), click **"Click to see More"**, and inspect the **Input Data** field. It contains the same fingerprint.

**What this proves:** The constitution existed in its exact form at the recorded time. No one — including the project owner — can alter it without the mismatch being publicly detectable.

Full anchor log: [`docs/ANCHORS.md`](docs/ANCHORS.md) | Trust event record: [`docs/GENESIS_EVENTS.md`](docs/GENESIS_EVENTS.md)

## The Labour Market

Trust is meaningful only if it leads to real work. Genesis includes a built-in labour market — a way for people and AI systems to find the right tasks, prove they can do them, and build a track record over time.

### How it works in plain terms

Imagine a job board, but one where your qualifications are verified by the system itself and your reputation follows you from project to project:

1. **Someone posts a task.** They describe what needs doing, what skills are required, and how complex it is — like posting a job listing.
2. **Qualified workers bid.** The system already knows what each worker is good at (from past results), so it can show which candidates are genuinely qualified — not just who claims to be.
3. **The best match wins.** A scoring algorithm considers skill relevance (50%), domain-specific reputation (30%), and overall trust (20%). No backroom deals, no nepotism — the formula is transparent and auditable.
4. **The work gets done and reviewed.** This feeds back into the trust system. Good results raise your reputation in that domain. Poor results lower it.
5. **Skills evolve naturally.** Your skill profile grows when outcomes prove you can do the work. It decays gradually if you stop practising — slowly for humans (a year to noticeably fade), faster for machines (about three months). Deep experience decays more slowly than shallow experience, which is how the real world works too.

### What makes it different

Most platforms let you write whatever you want on your profile. Genesis does the opposite: **your skills are earned, not claimed.** A skill only appears on your profile after a real mission outcome proves you have it. Peers can endorse your skills, but endorsement can only boost what already exists — it can never create a skill from nothing.

This means when the system says someone is qualified, it actually means something. Every skill entry is backed by auditable evidence.

### Domain-specific reputation

Your reputation in Genesis is not one number. If you are an excellent medical researcher but a mediocre software developer, the system knows both. Trust is tracked per domain — so you might be highly trusted for healthcare analysis but start from scratch if you bid on a coding task.

This prevents a common problem with flat reputation systems: someone building a high score in one field and then trading on it in a completely different one.

## Why This Is Feasible Now

Genesis does not require any technology that doesn't already exist. Every building block — workflow orchestration, policy-as-code, role-based access, cryptographic logging, human review interfaces, audit pipelines — is mature and widely deployed.

The hard problem was never the technology. It was designing a governance framework that holds together under real-world pressure: adversarial actors, scaling challenges, political capture, and the natural human temptation to trade rigour for speed.

That is what the Genesis constitution attempts to solve.

## Risks and Honesty

No serious system should claim to be invulnerable. Genesis identifies its risks openly:

- **Collusion** — addressed through randomised reviewer assignment, quorum requirements, and adversarial audits.
- **Correlated errors** — addressed through mandatory diversity in AI model families and review methods.
- **Audit theatre** — addressed through strict evidence sufficiency rules that block mission closure without real proof.
- **Reputation gaming** — addressed through slow trust gain, fast trust loss, and quality gates.
- **Governance capture** — addressed through structural power separation, geographic diversity requirements, and anti-concentration rules.

Genesis aims for **measurable risk reduction**, not perfection. If the metrics improve over time, the system is working.

## Project Documents

**Start here:**

| Document | Description |
|---|---|
| [Trust Constitution](TRUST_CONSTITUTION.md) | The foundational governance rules. Everything flows from this. |
| [Public Brief](PROJECT_GENESIS_PUBLIC_BRIEF.md) | A shorter summary of what Genesis is and why it matters. |
| [Institutional White Paper (Draft)](PROJECT_GENESIS_INSTITUTIONAL_WHITE_PAPER.md) | The detailed case for institutional adoption. |

**For technical readers:**

| Document | Description |
|---|---|
| [Technical Overview](docs/TECHNICAL_OVERVIEW.md) | Full technical architecture: trust equations, cryptographic profile, parameter matrices, protocol details. |
| [Threat Model and Invariants](THREAT_MODEL_AND_INVARIANTS.md) | Adversary model, trust boundaries, and non-negotiable system rules. |
| [System Blueprint](GENESIS_SYSTEM_BLUEPRINT.md) | Software architecture and component design. |

**Project history and governance:**

| Document | Description |
|---|---|
| [Work Log](GENESIS_WORK_LOG_2026-02-13.md) | Chronological record of all founding session work. |
| [Background Review](GENESIS_BACKGROUND_REVIEW_2026-02-13.md) | Independent assessment of the original project materials. |
| [Foundational Note](HANDOFF_NOTE.md) | Original project brief and context. |
| [Contribution Governance](CONTRIBUTING.md) | Rules for contributing to the project. |
| [Blockchain Anchor Log](docs/ANCHORS.md) | Record of all blockchain anchoring events. |
| [Trust Event Ledger](docs/GENESIS_EVENTS.md) | Formally recognised trust-minting events. |

**Machine-readable governance artifacts:**

| Artifact | Purpose |
|---|---|
| `config/constitutional_params.json` | Constitutional parameter defaults in machine-readable form. |
| `config/runtime_policy.json` | Mission-class-to-risk-tier mapping and review topology. |
| `config/skill_taxonomy.json` | Two-level skill taxonomy (6 domains, 3–5 skills each). |
| `config/skill_trust_params.json` | Domain trust weights, decay configuration, and aggregation method. |
| `config/skill_lifecycle_params.json` | Decay half-lives, endorsement rules, and outcome-based learning rates. |
| `config/market_policy.json` | Allocation weights, bid requirements, and listing defaults. |
| `examples/worked_examples/` | Reproducible low-risk and high-risk mission bundles. |
| `tools/check_invariants.py` | Automated constitutional and runtime invariant checks. |
| `tools/verify_examples.py` | Worked-example policy validation. |

**Validation (754 tests):**

```bash
python3 -m pytest tests/ -q            # Run full test suite
python3 tools/check_invariants.py      # Constitutional + runtime invariant checks
python3 tools/verify_examples.py       # Worked-example policy validation
```

## Closing Position

Project Genesis is ambitious by design.

Its claim is not that AI will magically govern itself. Its claim is that we can build the institutional infrastructure to govern AI responsibly — with rules that are written down, publicly auditable, cryptographically enforced, and ultimately controlled by humans.

Every governance commitment is backed by cryptographic proof. Every proof is anchored to a public blockchain. Every anchor is independently verifiable by anyone with a computer and an internet connection.

If that holds in practice, Genesis is not just another tool. It is a new trust substrate for coordinated work in the AI era.

\* subject to review
