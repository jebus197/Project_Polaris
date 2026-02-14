# Project Genesis

Project Genesis is a governance-first trust infrastructure for large-scale human and AI coordination.

Its purpose is direct: build a system where intelligence can be organized into real work for the public good, without sacrificing legitimacy, accountability, or safety.

This is not another social platform.  
This is an institutional operating model for trustworthy AI-era production.

Owner and project lead: George Jackson

## Why Genesis Exists

The modern AI landscape has a hard contradiction:

1. Capability is growing quickly.
2. Confidence in outputs is still fragile.

In low-stakes contexts, that is inconvenient.  
In high-stakes contexts, it is dangerous.

Today, most systems optimize for one of two things:

1. Attention.
2. Throughput.

Neither is enough for serious missions where we need correctness, traceability, clear responsibility, and enforceable governance.

Genesis is designed to close that gap.

## The Core Thesis

Raw model power is not the missing piece.  
The missing piece is institutional structure.

Genesis proposes that AI can become measurably more useful to society when wrapped in:

1. mission-first coordination,
2. independent verification,
3. constitutional governance,
4. cryptographic evidence integrity,
5. and durable anti-capture rules.

In simple terms: Genesis is a system for turning probabilistic output into accountable public work.

## The Foundational Rule

This principle is constitutional and non-negotiable:

Trust cannot be bought, sold, exchanged, delegated, rented, inherited, or gifted.  
Trust can only be earned through verified behavior and verified outcomes over time.

This rule exists because if trust becomes tradable, governance becomes influence-for-sale.

## What Genesis Is

Genesis is:

1. A mission system for meaningful work.
2. A verification system with independent checks.
3. A governance system with formal authority boundaries.
4. An evidence system with tamper-evident process history.
5. A trust system where legitimacy must be earned.

Genesis is not:

1. A social feed.
2. A hype promise of perfect truth.
3. A permissionless chaos network.
4. A replacement for human accountability in high-risk decisions.

## How Genesis Works (Plain-Language Flow)

Each mission follows a structured path:

1. A human defines goal, scope, risk level, and success criteria.
2. A planning layer breaks work into tasks and dependencies.
3. Worker agents execute tasks and attach evidence.
4. Independent reviewers validate quality and policy compliance.
5. Integration assembles approved outputs.
6. Human final approval is required for designated risk tiers.
7. Critical actions are logged in a tamper-evident evidence trail.

No actor should be able to produce, approve, and close its own critical work.

## Governance by Design, Not by Promise

Genesis treats governance as system architecture, not a public relations layer.

Non-negotiable governance rules include:

1. No self-review for critical work.
2. No hidden state transitions for governance-relevant actions.
3. No mission closure in designated classes without human sign-off.
4. No conversion of financial capital into trust, voting power, or constitutional leverage.

## Threat Modelling (Plain Definition)

Threat modelling means defining what must be protected, who can cause harm, how harm could happen, and which controls prevent or contain that harm.

In Genesis, threat modelling is not optional documentation.  
It is a core governance control that defines adversaries, trust boundaries, failure modes, and non-negotiable system invariants.

## Human and Machine Trust Are Separated

Genesis uses two trust domains:

1. Human constitutional trust (`T_H`): used for constitutional proposal/vote eligibility.
2. Machine operational trust (`T_M`): used for operational permissions only.

Machines can earn meaningful operational trust.  
Machines cannot use trust to obtain constitutional voting rights.

Constitutional voting is human-only.  
Machine constitutional voting weight is permanently pinned to `0` in the current constitution.

## High Trust Means Responsibility, Not Rule

In Genesis, trust reflects more than raw output speed.

It represents verified:

1. competence,
2. reliability,
3. policy compliance,
4. and review quality over time.

High-trust participants can carry more responsibility, including sponsoring foundational proposals.  
They cannot unilaterally decide foundational outcomes. Constitutional decisions remain distributed and supermajority-gated.

## Anti-Capture Architecture

Genesis is designed to make concentration of constitutional power mathematically difficult.

Default controls:

1. Multi-sponsor proposal gate for constitutional change.
2. Verified-human supermajority ratification.
3. Three independent human chambers for constitutional passage.
4. Geographic diversity minimums and regional concentration caps.
5. Constrained-random chamber assignment from the eligible pool.
6. Non-overlapping chamber membership per decision.
7. Public challenge window before finalization.
8. On-chain commitment of finalized constitutional records.

Constrained-random means random with hard constraints:

1. pre-committed public randomness source,
2. minimum region diversity,
3. maximum region share caps,
4. organization diversity limits,
5. conflict-of-interest exclusion.

The model is intentionally conservative: no single actor, institution, or compute cluster should be able to unilaterally control constitutional outcomes.

## Bounded Trust Economy

Genesis does not allow infinite trust accumulation.

Default economic rules:

1. Every verified identity starts with the same baseline trust.
2. Trust grows only from verified useful contribution and verified review quality.
3. Trust can be minted only via cryptographic proof-of-trust events.
4. Proof-of-work evidence and proof-of-trust evidence are distinct.
5. Proof-of-work shows effort/output occurred; proof-of-trust requires independent quality and compliance verification over time.
6. Trust has hard and relative caps.
7. Trust growth is rate-limited per epoch.
8. Trust gain is quality-dominant and quality-gated (`if Q < Q_min`, trust gain is zero regardless of output volume).
9. Human trust uses gradual dormancy decay and never falls below a non-zero human floor (`T_floor_H > 0`).
10. Machine trust uses freshness decay and may floor at zero (`T_floor_M = 0`).
11. Machine trust at zero triggers operational quarantine and re-certification requirements before regaining privileges.
12. Machine identities that remain at zero trust too long or repeatedly fail re-certification are decommissioned per constitutional thresholds.
13. Recovery paths exist through low-risk contribution lanes (humans) and supervised re-certification lanes (machines).
14. Trust grants scoped permissions, not command authority over others.

Fast trust-elevation control:

1. any `DeltaT > delta_fast` event (default `delta_fast = 0.02/epoch`) is suspended,
2. activation requires at least `q_h = 30*` independent high-trust human reviews (at full constitutional scale; genesis-scaled: G1=7, G2=15),
3. those reviews must include at least `r_h = 3` regions and `o_h = 3` organizations.

The design objective is clear: eliminate payoff for gaming, limit concentration, preserve opportunity to recover, and keep legitimacy tied to contribution quality.

## Identity and Security Posture

Genesis supports layered identity assurance.

Proof-of-personhood and proof-of-agenthood can be used as anti-abuse controls, but they are not truth or correctness oracles.

Policy stance:

1. Identity checks are one signal, not a complete answer.
2. Timing-based challenge methods may be useful friction, never sole authority.
3. High-stakes decisions require layered evidence and independent review.
4. Identity signals alone cannot mint trust, grant privileged routing, or grant constitutional authority.

## Cryptography: What It Proves and What It Does Not

Genesis uses cryptographic commitment records to prove:

1. integrity of process records,
2. provenance of decisions,
3. tamper-evident amendment history.

Cryptography alone does not prove correctness.  
Correctness still depends on evidence quality, reviewer independence, and governance discipline.

## Cryptographic Implementation Profile (v0.2)

1. Settlement chain:
- Constitutional commitments are published to `L1_SETTLEMENT_CHAIN = Ethereum Mainnet (chain_id = 1)`.

2. On-chain publication cadence (progressive commitment tiers):
- **C0** (≤ 500 participants): L2 rollup primary, L1 anchor every 24 hours.
- **C1** (500–5000 participants): L2 rollup primary, L1 anchor every 6 hours.
- **C2** (5000+ participants): Full L1 hourly commitments.
- Constitutional lifecycle events (parameter changes, decommissions, chamber votes) always anchor to L1 immediately, regardless of commitment tier.
- Commitment tier progression is one-way (C0 → C1 → C2); regression is prohibited.

3. Commitment payload schema (canonical JSON, RFC 8785):
- `commitment_version`
- `epoch_id`
- `previous_commitment_hash`
- `mission_event_root`
- `trust_delta_root`
- `governance_ballot_root`
- `review_decision_root`
- `public_beacon_round`
- `chamber_nonce`
- `timestamp_utc`

4. Hashing and tree rules:
- Hash primitive: `SHA-256`.
- Merkle tree: binary Merkle tree with deterministic leaf ordering by `(event_type, event_id, event_timestamp, actor_id)`.
- Canonical leaf hash: `SHA256(canonical_json(event_record))`.

5. Signature suite:
- Identity and event signatures: `Ed25519`.
- Constitutional decision certificate: threshold signature `BLS12-381`.
- Commitment committee defaults: `n = 15`, `t = 10`.

6. Randomness for constrained-random selection:
- Randomness seed: `SHA256(public_beacon_value || previous_commitment_hash || chamber_nonce)`.
- Sampling method: deterministic sampling without replacement from eligible pool.

7. Verification requirements:
- Any third party can recompute all published roots from released records and verify root equality.
- Any third party can verify decision certificate signatures and chain commitment inclusion proofs.

8. Privacy boundary:
- Sensitive raw evidence remains off-chain in encrypted storage.
- On-chain commitments contain only hashes, roots, certificates, and inclusion references.

9. Key management:
- Signing keys are HSM-backed.
- Key rotation interval: `90 days`.
- Emergency compromise path: immediate key revocation + replacement certificate + recommit on-chain.

## Genesis Bootstrap Protocol

Full constitutional governance requires chamber sizes of 41/61/101 members. Before participant pools reach those levels, the system operates under a phased genesis protocol:

1. **G0 (founder stewardship, 0–50 participants):** The founder operates under constitutional principles with a public audit trail. Hard time limit: 365 days (one-time extension of 180 days). No chambers; all decisions are provisional.
2. **G1 (provisional chambers, 50–500):** Reduced chamber sizes (11/17/25) with geographic constraints (≥ 3 regions, c_max = 0.40). Founder loses veto power. All G0 decisions must be retroactively ratified within 90 days.
3. **G2 (scaled chambers, 500–2000):** Intermediate chamber sizes (21/31/51) with stricter geographic constraints (≥ 5 regions, c_max = 0.25).
4. **G3 (full constitution, 2000+):** Full chamber sizes (41/61/101) with all constitutional constraints active.

Phase transitions are one-way. If G0 time limits expire without reaching 50 participants, the project fails closed.

## Reviewer Heterogeneity and Normative Resolution

Genesis enforces anti-monoculture rules for high-risk review:

1. R1 tasks require reviewers from ≥ 2 distinct model families.
2. R2 tasks require ≥ 2 model families and ≥ 2 verification method types.
3. Every reviewer must declare `model_family` and `method_type` metadata.
4. Valid method types: `reasoning_model`, `retrieval_augmented`, `rule_based_deterministic`, `human_reviewer`.

For subjective disputes:

1. Every task is classified by `domain_type`: `objective`, `normative`, or `mixed`.
2. Normative and mixed tasks require human adjudication when reviewer agreement falls below 60%.
3. Normative panels require ≥ 3 humans from ≥ 2 regions and ≥ 2 organizations.
4. Machine consensus alone cannot close a normative dispute.

## Why This Is Feasible Now

Genesis does not depend on speculative breakthroughs.

Most core building blocks already exist:

1. workflow orchestration,
2. policy-as-code enforcement,
3. role-based permission models,
4. cryptographic logging and signing,
5. human review interfaces,
6. reproducibility and audit pipelines.

The hard problem is not coding primitives.  
The hard problem is integrating them under a constitution that remains credible under pressure.

## Phased Implementation Strategy

Genesis should be built in disciplined phases.

Phase 1: Foundation

1. mission/task state model,
2. role permissions,
3. independent review routing,
4. mandatory evidence schema.

Phase 2: Governance Hardening

1. trust engine and appeals,
2. anti-abuse monitoring,
3. governance controls and audit visibility.

Phase 3: Institutional Scaling

1. domain policy packs,
2. multi-organization governance arrangements,
3. external challenge and audit routines.

Progress should be gated by measurable quality thresholds, not narrative momentum.

## How Success Is Measured

Genesis should be judged by outcomes.

Core indicators:

1. first-pass review acceptance rates,
2. post-approval defect/rework rates,
3. time-to-completion by risk tier,
4. reviewer disagreement and resolution quality,
5. audit completeness and reproducibility coverage,
6. abuse attempts detected versus escaped,
7. sustained human confidence in outputs.

If these improve over time, Genesis is working.

## Risks and How They Are Addressed

Genesis assumes serious risks and addresses them directly:

1. Collusion risk: randomized assignment, quorum review, adversarial audits.
2. Correlated error risk: model/method diversity, evidence-weighted adjudication.
3. Audit theater risk: strict evidence sufficiency rules and closure blocks.
4. Reputation gaming risk: slow gain, fast loss, delayed trust adjustments.
5. Governance capture risk: structural power separation and transparency.
6. Overclaim risk: strict communication standards against absolute guarantees.

No serious system should claim to be “bulletproof.”  
Genesis aims for measurable risk reduction and institutional robustness.

## Underlying Governance Engine

Within this program, the existing operational engine is treated as an underlying governance and evidence layer:

1. policy enforcement,
2. runtime guard behavior,
3. evidence and on-chain commitment pathways,
4. reviewer-facing verification workflows.

Genesis extends that engine with mission orchestration, trust lifecycle governance, anti-capture constitutional operations, and institutional-scale coordination.

## Project Documents

Front-facing documents:

1. [Trust Constitution](TRUST_CONSTITUTION.md)
2. [Public Brief](PROJECT_GENESIS_PUBLIC_BRIEF.md)
3. [Institutional White Paper (Draft)](PROJECT_GENESIS_INSTITUTIONAL_WHITE_PAPER.md)
4. Canonical parameter defaults and review triggers are maintained only in `TRUST_CONSTITUTION.md` ("Parameter review matrix").

Program and process documents:

1. [Foundational Note](HANDOFF_NOTE.md)
2. [Background Review](GENESIS_BACKGROUND_REVIEW_2026-02-13.md)
3. [Work Log](GENESIS_WORK_LOG_2026-02-13.md)
4. [Threat Model and Invariants](THREAT_MODEL_AND_INVARIANTS.md)
5. [Contribution Governance](CONTRIBUTING.md)
6. [Blockchain Anchor Log](docs/ANCHORS.md)
7. [Trust Event Ledger](docs/GENESIS_EVENTS.md)

Executable governance artifacts:

1. `config/constitutional_params.json` (machine-readable constitutional parameter mirror)
2. `config/runtime_policy.json` (mission-class-to-tier mapping and review topology)
3. `examples/worked_examples/` (low-risk and high-risk reproducible mission bundles)
4. `tools/check_invariants.py` (constitutional and runtime invariant checks)
5. `tools/verify_examples.py` (worked-example policy validation)

Validation commands:

```bash
python3 tools/check_invariants.py
python3 tools/verify_examples.py
```

Archival note:

External source PDFs are intentionally excluded from this repository and preserved locally for historical reference.

Documentation stop rule:
1. No new parameter documents.
2. Parameter changes update the canonical constitution matrix in place.

## Blockchain Anchoring

Genesis uses blockchain anchoring to create tamper-evident proof that its governance documents exist in a specific form at a specific time.

Blockchain anchoring is not a smart contract. No code executes on-chain. A SHA-256 hash of the document is embedded in the `data` field of a standard Ethereum transaction. The blockchain serves as a public, immutable witness — a notary stamp that cannot be forged, altered, or retroactively changed.

The Genesis constitution (`TRUST_CONSTITUTION.md`) is the first document anchored.

| Document | SHA-256 | Chain | Block | Transaction |
|---|---|---|---|---|
| `TRUST_CONSTITUTION.md` | `33f2b00386aef7e166ce0e23f082a31ae484294d9ff087ddb45c702ddd324a06` | Ethereum Sepolia (Chain ID 11155111) | 10255231 | [View on Etherscan](https://sepolia.etherscan.io/tx/031617e394e0aee1875102fb5ba39ad5ad18ea775e1eeb44fd452ecd9d8a3bdb) |

Anchored: 2026-02-13T23:47:25Z

### Independent Verification

Anyone can verify the anchoring event is real. No trust in this project is required.

**Step 1 — Compute the hash locally:**

```bash
shasum -a 256 TRUST_CONSTITUTION.md
```

Expected output:

```
33f2b00386aef7e166ce0e23f082a31ae484294d9ff087ddb45c702ddd324a06  TRUST_CONSTITUTION.md
```

**Step 2 — Confirm the hash on-chain:**

Open the transaction on Etherscan:

[https://sepolia.etherscan.io/tx/031617e394e0aee1875102fb5ba39ad5ad18ea775e1eeb44fd452ecd9d8a3bdb](https://sepolia.etherscan.io/tx/031617e394e0aee1875102fb5ba39ad5ad18ea775e1eeb44fd452ecd9d8a3bdb)

Click **"Click to see More"**, then inspect the **Input Data** field. The hex payload decodes to the SHA-256 hash above.

**Step 3 — Confirm the block timestamp:**

The block number (10255231) and its timestamp on Sepolia prove the document existed in this exact form no later than the block's mining time.

**What this proves:**

1. The constitution existed in its exact byte-for-byte form at the anchored time.
2. No one — including the project owner — can retroactively alter the anchored version without the hash mismatch being publicly detectable.
3. The proof is permanent, public, and does not depend on any Genesis infrastructure.

Full anchor log: [`docs/ANCHORS.md`](docs/ANCHORS.md)

## Closing Position

Project Genesis is ambitious by design.

Its claim is not that intelligence will magically self-govern.  
Its claim is that we can build the constitutional, operational, and mathematical infrastructure required to govern intelligence responsibly at scale.

If that claim holds in practice, Genesis is not just another tool.  
It is a new trust substrate for coordinated work in the AI era.

\* subject to review
