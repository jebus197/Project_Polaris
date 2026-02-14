# Project Genesis — Technical Overview

This document covers the full technical architecture of Project Genesis. It is intended for engineers, researchers, auditors, and anyone who wants to understand how the system actually works beneath the governance principles described in the [README](../README.md).

The [Trust Constitution](../TRUST_CONSTITUTION.md) is the canonical source for all parameter values. This document explains the reasoning behind them.

---

## Table of Contents

1. [Trust Model](#trust-model)
2. [Bounded Trust Economy](#bounded-trust-economy)
3. [Risk Tiers and Review Requirements](#risk-tiers-and-review-requirements)
4. [Reviewer Heterogeneity](#reviewer-heterogeneity)
5. [Normative Dispute Resolution](#normative-dispute-resolution)
6. [Anti-Capture Architecture](#anti-capture-architecture)
7. [Genesis Bootstrap Protocol](#genesis-bootstrap-protocol)
8. [Cryptographic Implementation Profile](#cryptographic-implementation-profile)
9. [Blockchain Anchoring](#blockchain-anchoring)
10. [Identity and Security Posture](#identity-and-security-posture)
11. [Success Metrics](#success-metrics)
12. [Governance Engine Architecture](#governance-engine-architecture)

---

## Trust Model

Genesis maintains two separate trust domains because humans and machines play fundamentally different roles in the system.

### Human trust (`T_H`)

Human trust determines both operational permissions (which tasks you can take on, which reviews you can conduct) and constitutional authority (whether you can propose or vote on governance changes).

The trust score is a weighted sum of four components:

```
T_H = w_Q · Q_H  +  w_R · R_H  +  w_V · V_H  +  w_E · E_H
```

Where:
- `Q_H` = quality score — derived from review outcomes on work you've produced.
- `R_H` = review reliability — how consistent and accurate your reviews are, measured against subsequent outcomes.
- `V_H` = verification record — your track record of providing valid evidence and following process requirements.
- `E_H` = effort score — measures reasoning effort proportional to mission complexity tier.

Default weights: `w_Q = 0.70`, `w_R = 0.20`, `w_V = 0.05`, `w_E = 0.05`.

These weights mean quality dominates. An actor who produces high volumes of mediocre work will not accumulate meaningful trust, because `Q` stays low regardless of volume. The effort component (`E`) adds a further cost dimension: each risk tier has a minimum effort threshold that increases monotonically (R0: 0.10, R1: 0.30, R2: 0.50, R3: 0.70). This makes gaming more expensive — an attacker cannot simply stamp "approve" on high-risk work without investing proportional reasoning effort. Crucially, effort alone cannot mint trust: the quality gate still applies, so effort without quality produces zero gain.

### Machine trust (`T_M`)

Machine trust uses the same formula but grants only operational permissions. The constitution permanently pins machine constitutional voting weight at zero (`w_M_const = 0`). This means no amount of operational excellence by a machine can translate into governance authority.

Why? Because the system that governs AI must not be governable by AI. This is a permanent architectural boundary, not a tuning parameter.

### Trust eligibility thresholds

Two thresholds gate participation in governance:

- `tau_vote = 0.60` — minimum trust to vote on constitutional matters.
- `tau_prop = 0.75` — minimum trust to propose constitutional changes.

These are deliberately high. Proposing a constitutional change is the most consequential action in the system, so it requires a sustained track record.

---

## Bounded Trust Economy

Unbounded trust accumulation creates the same problem as unbounded wealth accumulation: concentration of power. Genesis prevents this through hard structural limits.

### Starting position

Every verified identity — human or machine — enters the system with the same baseline trust: `T_baseline = 0.10`. This is enough to participate in low-risk tasks but not enough for any governance role.

### Growth rules

- Trust increases only through verified quality contributions. Volume without quality produces zero trust gain because of the quality gate (see below).
- Trust growth is rate-limited: no actor can gain more than a defined amount per epoch. This prevents sudden trust spikes from gaming or coordinated manipulation.

### Quality gate

This is one of the most important controls in the system:

```
If Q < Q_min, then trust gain = 0 (regardless of output volume)
```

Default thresholds: `Q_min_H = 0.60` for humans, `Q_min_M = 0.70` for machines (machines face a higher bar because their failure modes are different — they can produce large volumes of superficially correct but subtly wrong output).

The quality gate means you cannot grind your way to high trust through bulk production. Every contribution must pass a quality threshold before it counts toward trust at all.

### Hard caps

- `T_cap_abs = 0.95` — no actor can exceed this trust level under any circumstances.
- `T_cap_rel` — relative cap that limits any single actor's trust relative to the population, preventing dominance even in small pools.

### Decay

Trust is not permanent. It decays over time if you stop contributing:

- **Human decay** is gradual ("dormancy decay") with a grace period. Humans who step away don't lose trust instantly — the system acknowledges that people take breaks, change jobs, or have life events. However, trust never falls below a non-zero human floor (`T_floor_H > 0`), recognising that a human's accumulated track record has lasting value.
- **Machine decay** is faster ("freshness decay") and the floor is zero (`T_floor_M = 0`). Machines that stop being validated go stale quickly, because an unmonitored AI system's reliability cannot be assumed. A machine at zero trust enters operational quarantine and must be re-certified before regaining privileges.

### Fast-elevation control

If any actor's trust jumps by more than `delta_fast = 0.02` in a single epoch, the jump is automatically suspended. Activation requires:

- At least `q_h = 30` independent high-trust human reviews (scaled down during genesis phases: G1 = 7, G2 = 15).
- Those reviews must come from at least `r_h = 3` regions and `o_h = 3` organisations.

This prevents both gaming (artificially inflating a single actor's trust) and systemic error (a bug or exploit causing unintended trust spikes).

### Recovery

Trust loss is not a death sentence:

- Humans can recover through a low-risk contribution lane — doing small, verified tasks that gradually rebuild their score.
- Machines can recover through supervised re-certification — a structured process with heightened oversight.
- Actors that remain at zero trust beyond decommission thresholds are retired from the system. For machines, this means permanent decommission. For humans, the floor prevents this scenario entirely.

---

## Risk Tiers and Review Requirements

Not all work requires the same level of oversight. Genesis classifies every mission into one of four risk tiers, each with escalating review requirements.

| Tier | Description | Approvals Required | Human Gate | Evidence |
|---|---|---|---|---|
| R0 | Low risk, routine | 1 reviewer | No | Hash + signature |
| R1 | Moderate risk | 2 reviewers, ≥ 2 model families | No | Hash + signature + provenance |
| R2 | High risk | 3 reviewers, ≥ 2 model families, ≥ 2 method types | Yes | Full evidence chain |
| R3 | Critical / safety | Full panel, human-majority | Yes | Full evidence chain + external audit |

The mapping from mission class to risk tier is defined in `config/runtime_policy.json`. This mapping is itself a constitutional artifact — changing it requires governance approval.

### What "model families" and "method types" mean

- **Model family** refers to the underlying AI system: GPT-4o, Claude Opus, Gemini, Llama, etc. Requiring reviewers from different model families prevents correlated errors — if one model has a systematic blind spot, a different model is likely to catch it.
- **Method type** refers to the verification approach: `reasoning_model` (chain-of-thought analysis), `retrieval_augmented` (grounded in external sources), `rule_based_deterministic` (formal rule checking), or `human_reviewer`. Requiring different method types prevents methodological monoculture.

---

## Reviewer Heterogeneity

For high-risk work, Genesis enforces anti-monoculture rules in reviewer selection:

- **R1 tasks**: reviewers must come from ≥ 2 distinct model families.
- **R2 tasks**: reviewers must come from ≥ 2 model families AND ≥ 2 verification method types.
- Every reviewer must declare their `model_family` and `method_type` metadata at assignment time.

Additionally, the reviewer router enforces:

- **Self-review block**: no actor can review their own work, at any risk tier.
- **Geographic diversity**: reviewers must come from multiple regions (specific minimums depend on the genesis phase).
- **Organisational diversity**: reviewers must come from multiple organisations, preventing any single institution from controlling review outcomes.

These rules are enforced by code in the reviewer routing engine, not by policy documents. The system will refuse to complete a review cycle that violates heterogeneity requirements.

---

## Normative Dispute Resolution

Not all questions have objectively correct answers. Genesis distinguishes between three domain types:

- **Objective** — questions with verifiable right/wrong answers (e.g., "does this code compile?").
- **Normative** — questions involving values, ethics, priorities, or subjective judgement (e.g., "is this policy fair?").
- **Mixed** — questions with both objective and normative components.

For normative and mixed domains, special rules apply:

1. If reviewer agreement falls below 60%, the dispute escalates to a human adjudication panel.
2. Normative panels require ≥ 3 humans from ≥ 2 regions and ≥ 2 organisations.
3. Machine consensus alone can never close a normative dispute — human judgement is required.
4. All normative adjudications must include documented reasoning.

This reflects a core design principle: machines are excellent at checking objective facts but should not be the final authority on questions of values.

---

## Anti-Capture Architecture

"Capture" means a single actor, faction, or interest group gaining disproportionate control over governance. Genesis treats capture as the primary long-term threat and uses structural defences rather than relying on good behaviour.

### Three-chamber model

Constitutional decisions pass through three independent human chambers:

- **Proposal chamber** — evaluates whether a proposal is well-formed and merits consideration.
- **Ratification chamber** — votes on whether to adopt the proposal.
- **Challenge chamber** — provides a final check during a public challenge window.

Each chamber is populated through **constrained-random selection** from the eligible pool. "Constrained-random" means:

1. Members are drawn randomly (using a pre-committed public randomness source for verifiability).
2. But hard constraints are enforced: minimum regional diversity, maximum regional concentration caps, organisation diversity limits, and conflict-of-interest exclusions.
3. No actor can serve on more than one chamber for the same decision.

Chamber sizes scale with the genesis phase (see below).

### Constitutional change requirements

To change the Genesis constitution:

1. A proposal must be sponsored by multiple high-trust participants (not just one person with high trust).
2. The proposal chamber must accept it.
3. The ratification chamber must approve by supermajority (strict majority is not enough).
4. A public challenge window must pass without successful challenge from the challenge chamber.
5. The finalised decision is cryptographically committed to a public blockchain.

No single actor — no matter how high their trust — can unilaterally change the rules.

### Financial isolation

Financial capital has zero role in Genesis governance:

- Money cannot increase trust.
- Money cannot purchase voting power.
- Money cannot buy constitutional authority.
- Sponsorship, donation, or investment create no governance privileges.

This is a deliberate break from most real-world governance systems, where money eventually translates into influence. Genesis treats this as a corruption vector and blocks it structurally.

---

## Genesis Bootstrap Protocol

The full constitutional governance model requires large participant pools (chamber sizes of 41/61/101). Before those numbers are reached, the system operates under a phased bootstrap protocol with reduced thresholds and additional safeguards.

| Phase | Participants | Chamber Sizes | Regions Required | Max Regional Share | Key Rules |
|---|---|---|---|---|---|
| **G0** | 0 – 50 | No chambers | N/A | N/A | Founder stewardship. All decisions provisional. Public audit trail. Hard time limit: 365 days (one extension of 180 days). |
| **G1** | 50 – 500 | 11 / 17 / 25 | ≥ 3 | 0.40 | Provisional chambers activate. Founder loses veto. All G0 decisions must be retroactively ratified within 90 days. |
| **G2** | 500 – 2,000 | 21 / 31 / 51 | ≥ 5 | 0.25 | Intermediate chambers. Stricter geographic constraints. |
| **G3** | 2,000+ | 41 / 61 / 101 | Full | Full | Full constitutional governance. All constraints active. |

Critical rules:

- Phase transitions are **one-way**. The system cannot regress from G2 to G1, or from G1 to G0.
- If G0 time limits expire without reaching 50 participants, **the project fails closed** — it does not limp along indefinitely under founder control.
- The founder's authority is explicitly time-limited and structurally eliminated in G1.

---

## Cryptographic Implementation Profile

This section describes the specific cryptographic mechanisms Genesis uses. Version: v0.2.

### Settlement chain

Constitutional commitments are published to Ethereum Mainnet (`chain_id = 1`) for production. Development and testing use Ethereum Sepolia (`chain_id = 11155111`).

### Commitment tiers (progressive on-chain publication)

On-chain publication is expensive at scale. Genesis uses a tiered approach:

| Tier | Participants | Strategy | L1 Anchor Frequency |
|---|---|---|---|
| **C0** | ≤ 500 | L2 rollup primary | Every 24 hours |
| **C1** | 500 – 5,000 | L2 rollup primary | Every 6 hours |
| **C2** | 5,000+ | Full L1 commitments | Hourly |

**Exception:** Constitutional lifecycle events — parameter changes, decommissions, chamber votes — always anchor to L1 immediately, regardless of commitment tier.

Tier progression is one-way (C0 → C1 → C2). Regression is prohibited.

### Commitment payload

Each commitment is a canonical JSON object (RFC 8785) containing:

| Field | Purpose |
|---|---|
| `commitment_version` | Schema version for forward compatibility. |
| `epoch_id` | The time period this commitment covers. |
| `previous_commitment_hash` | Links to the prior commitment, forming a verifiable chain. |
| `mission_event_root` | Merkle root of all mission events in this epoch. |
| `trust_delta_root` | Merkle root of all trust changes in this epoch. |
| `governance_ballot_root` | Merkle root of all governance votes in this epoch. |
| `review_decision_root` | Merkle root of all review decisions in this epoch. |
| `public_beacon_round` | External randomness source identifier (for constrained-random selection). |
| `chamber_nonce` | Anti-replay value for chamber operations. |
| `timestamp_utc` | When the commitment was generated. |

### Hashing and Merkle trees

- **Hash function:** SHA-256 throughout.
- **Merkle tree structure:** Binary Merkle tree with deterministic leaf ordering by `(event_type, event_id, event_timestamp, actor_id)`. This means anyone with the raw records can independently reconstruct the tree and verify the root matches the published commitment.
- **Leaf hash:** `SHA-256(canonical_json(event_record))` — the event is serialised to canonical JSON before hashing, ensuring deterministic output regardless of field ordering.

### Signature suite

| Use Case | Algorithm | Notes |
|---|---|---|
| Identity and event signatures | Ed25519 | Fast, compact, well-audited. |
| Constitutional decision certificates | BLS12-381 threshold signature | Allows a committee to produce a single valid signature. Default: `n = 15` committee members, `t = 10` threshold (two-thirds). |

### Randomness for constrained-random selection

The randomness used for chamber selection must be publicly verifiable and not manipulable by any participant:

```
seed = SHA-256(public_beacon_value || previous_commitment_hash || chamber_nonce)
```

- `public_beacon_value` — from an external, pre-committed randomness source (e.g., drand).
- `previous_commitment_hash` — ties the randomness to the chain state.
- `chamber_nonce` — prevents replay across different selection events.

Selection uses deterministic sampling without replacement from the eligible pool, constrained by the diversity requirements described above.

### Verification

Any third party can:

1. Recompute all published Merkle roots from released event records and verify they match the on-chain commitments.
2. Verify decision certificate signatures against the known committee public keys.
3. Verify chain commitment inclusion proofs.

No Genesis infrastructure is required for verification. The proofs are self-contained.

### Privacy boundary

- Sensitive raw evidence (e.g., personal data, proprietary content) remains off-chain in encrypted storage.
- On-chain commitments contain only hashes, Merkle roots, certificates, and inclusion references — never raw content.

### Key management

- Signing keys are HSM-backed (hardware security modules).
- Key rotation interval: 90 days.
- Emergency compromise path: immediate key revocation, replacement certificate issuance, and recommitment on-chain.

---

## Blockchain Anchoring

### Historical foundations

The idea of using cryptography to prove a document existed at a particular time predates blockchain technology by nearly two decades.

In 1991, Stuart Haber and W. Scott Stornetta published *"How to Time-Stamp a Digital Document"*, proposing a system in which documents are hashed and the hashes linked into a chain — each entry referencing the previous one — creating a tamper-evident chronological record. Their follow-up work introduced Merkle trees to batch multiple timestamps efficiently. These two papers are among the most cited references in Satoshi Nakamoto's 2008 Bitcoin whitepaper, which extended the concept by replacing a trusted timestamping authority with a decentralised proof-of-work consensus mechanism.

From 1995 onward, a company called Surety put these ideas into practice, publishing hash chains in the *New York Times* classified section — making it the longest-running cryptographic timestamp chain in history.

Once Bitcoin launched in 2009, the blockchain itself became a natural public timestamping medium. Bitcoin's `OP_RETURN` opcode (available since Bitcoin Core 0.9.0, March 2014) formalised the practice of embedding arbitrary data — including document hashes — into transactions. Services emerged to make this accessible:

- **OpenTimestamps** — an open protocol that uses Bitcoin as a timestamp notary, batching many hashes into a single daily transaction via Merkle aggregation.
- **Stampery** — published a formal Blockchain Timestamping Architecture (BTA) in 2014.
- **OriginStamp** — a multi-chain timestamping service anchoring to Bitcoin, Ethereum, and others simultaneously.

The existing field uses various terms — "blockchain timestamping", "data anchoring", "cryptographic stamping" — but the underlying technique is the same: embed a hash in a public blockchain transaction, and the blockchain serves as a permanent, independent witness to the document's existence at that point in time.

### What blockchain anchoring is

Blockchain anchoring is the practice of embedding a cryptographic hash of a document into a standard blockchain transaction, creating permanent, public, tamper-evident proof that the document existed in a specific form at a specific time.

The process is deliberately simple:

1. Compute the SHA-256 hash of the document.
2. Send a standard Ethereum transaction where the `data` field contains that hash.
3. The transaction is mined into a block with a timestamp.
4. The hash is now permanently recorded on a public, immutable ledger.

No code executes on-chain. No smart contract is deployed. The blockchain is a passive witness — a notary, not an actor.

### How it differs from smart contracts

This distinction matters because the two are frequently confused:

| | Blockchain Anchoring | Smart Contracts |
|---|---|---|
| **What's on-chain** | A hash (32 bytes of data) | Executable code and state |
| **What executes** | Nothing — the blockchain is a passive witness | The contract code runs on every node |
| **Cost** | Minimal (one standard transaction) | High (proportional to computation and storage) |
| **Complexity** | Trivial — hash a document, send a transaction | Significant — requires Solidity/Vyper, auditing, gas optimisation |
| **Purpose** | Prove a document existed at a point in time | Execute logic on-chain (token transfers, DeFi, DAOs) |

Genesis uses anchoring, not smart contracts. The blockchain is a witness, not an actor.

### How Genesis uses anchoring

Genesis adopts and formalises blockchain anchoring as a core governance primitive. The first document anchored — the Genesis constitution (`TRUST_CONSTITUTION.md`) — serves as both a governance act and a concrete demonstration of the technique.

**What was anchored:**

| Field | Value |
|---|---|
| Document | `TRUST_CONSTITUTION.md` |
| SHA-256 | `33f2b00386aef7e166ce0e23f082a31ae484294d9ff087ddb45c702ddd324a06` |
| Chain | Ethereum Sepolia (Chain ID 11155111) |
| Block | 10255231 |
| Sender | [`0xC3676587a06b33A07a9101eB9F30Af9Fb988F7CE`](https://sepolia.etherscan.io/address/0xC3676587a06b33A07a9101eB9F30Af9Fb988F7CE) |
| Transaction | [`031617e3...`](https://sepolia.etherscan.io/tx/031617e394e0aee1875102fb5ba39ad5ad18ea775e1eeb44fd452ecd9d8a3bdb) |
| Anchored | 2026-02-13T23:47:25Z |

**What this proves:**

1. The constitution existed in its exact byte-for-byte form at the recorded time.
2. No party — including the project owner — can alter the anchored version without the mismatch being publicly detectable.
3. The proof is permanent, does not expire, and does not depend on any Genesis infrastructure.

This anchoring event is formally recognised as the first trust-minting event in Genesis history (see [`docs/GENESIS_EVENTS.md`](GENESIS_EVENTS.md)).

### Verification process

Any third party can verify an anchoring event independently. No trust in Genesis is required — only a hash function and a block explorer.

1. Compute the SHA-256 hash of the document locally: `shasum -a 256 TRUST_CONSTITUTION.md`
2. Look up the transaction on Etherscan (or any Ethereum block explorer).
3. Inspect the transaction's Input Data field — it contains the hash.
4. If the locally computed hash matches the on-chain hash, the document is verified as unchanged since the anchor time.
5. The block timestamp proves when the anchor was recorded.

The verification depends only on SHA-256 (a public standard) and the Ethereum blockchain (a public ledger). No API calls, no Genesis software, no trust in any party.

### Why anchoring matters for governance

Traditional institutions prove the integrity of their founding documents through physical custody, legal witnesses, and institutional reputation. All of these depend on trusting the institution itself — the very thing that may need to be verified.

Blockchain anchoring breaks this circularity. The proof is mathematical, the witness is a public network with no relationship to Genesis, and verification can be performed by anyone with a computer. This means Genesis can credibly commit to its own rules in a way that does not require anyone to take its word for it.

For a project whose foundational principle is that trust must be earned rather than assumed, this is not just a technical feature — it is the first act of practising what it preaches.

---

## Identity and Security Posture

Genesis supports layered identity assurance but treats identity signals with deliberate caution.

### What identity checks can do

- Proof-of-personhood and proof-of-agenthood can serve as anti-abuse controls (e.g., preventing mass creation of fake accounts).
- Timing-based challenge methods can add useful friction against automated attacks.

### What identity checks cannot do

- Identity signals alone cannot mint trust, grant privileged routing, or grant constitutional authority.
- Passing an identity check does not make someone trustworthy — it makes them verified as a distinct participant.
- High-stakes decisions require layered evidence and independent review, not identity checks.

The position is: identity verification tells you *who someone is*, not *whether they should be trusted*. Trust comes from behaviour over time.

---

## Success Metrics

Genesis defines success through measurable outcomes, not narrative claims.

| Metric | What It Measures | Why It Matters |
|---|---|---|
| First-pass review acceptance rate | How often work passes review on the first attempt | Indicates overall production quality |
| Post-approval defect/rework rate | How often approved work turns out to be wrong | Catches failures in the review process |
| Time-to-completion by risk tier | How long missions take at each risk level | Tracks operational efficiency vs. governance overhead |
| Reviewer disagreement rate | How often reviewers reach different conclusions | High disagreement may signal ambiguous criteria or poor task design |
| Resolution quality | How well disputes are resolved (measured by subsequent outcomes) | Tests whether the adjudication process works |
| Audit completeness | Percentage of actions with full evidence trails | Measures whether the logging system is actually working |
| Abuse detection vs. escape rate | How many gaming attempts are caught vs. missed | Tests the effectiveness of anti-capture controls |
| Sustained human confidence | Whether human participants continue to trust the system over time | The ultimate measure — if humans lose confidence, nothing else matters |

If these metrics improve over time, the system is working. If they don't, the governance framework needs revision — and the constitution provides the mechanism to do that.

---

## Governance Engine Architecture

The runtime software implements the governance framework described above. The codebase is organised as follows:

```
src/genesis/
├── models/          Data models (mission, trust, commitment, governance)
├── policy/          Policy resolver (loads constitutional and runtime config)
├── engine/          Mission state machine, evidence validation, reviewer routing
├── trust/           Trust scoring, decay, quality gates, fast-elevation control
├── governance/      Genesis phase controller (G0→G1→G2→G3 progression)
├── crypto/          Merkle trees, commitment builder, blockchain anchoring, epoch service
├── review/          Actor roster, constrained-random reviewer selector
├── persistence/     Event log (append-only JSONL) and state store (JSON)
├── service.py       Unified service facade (orchestrates all subsystems)
└── cli.py           Command-line interface
```

Key design principles:

1. **Fail-closed**: if the system encounters an ambiguous state, it blocks rather than proceeding. A mission that cannot prove compliance stays open.
2. **Parameter-driven**: all constitutional values are loaded from `config/constitutional_params.json`. No magic numbers in code.
3. **Auditable transitions**: every state change in the mission lifecycle is an explicit, logged event.
4. **Self-review impossible**: the reviewer router structurally prevents any actor from reviewing their own work.

All constitutional invariants are tested automatically. The test suite (212 tests) covers every critical rule described in this document.

```bash
python3 -m pytest tests/ -v
```

---

*This document describes the technical architecture as of the founding session (2026-02-13). It will evolve as the system develops, but changes to constitutional parameters require governance approval as described above.*

\* subject to review
