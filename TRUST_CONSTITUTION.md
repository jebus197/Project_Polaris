# Project Polaris - Trust Constitution

Date: February 13, 2026
Status: Foundational, non-negotiable
Author: George Jackson

## Core Rule

Trust cannot be bought, sold, exchanged, delegated, rented, inherited, or gifted.

Trust can only be earned through verified behavior and verified outcomes over time.

## Why this exists

Polaris is designed as a credibility system, not a market for influence.

If trust can be purchased or transferred, governance becomes corruptible and the network loses legitimacy.

## Constitutional requirements

1. No paid trust:
- No money, tokens, sponsorship, ownership, or hardware scale can directly increase trust score.

2. No transfer of trust:
- Trust is identity-bound and cannot be moved between identities.

3. Evidence-only trust growth:
- Trust can increase only from verified high-quality work and verified high-quality review conduct.

4. Fast penalties for severe failure:
- Proven severe misconduct causes immediate trust reduction and access restriction.

5. Transparent history:
- Trust-relevant events must be logged and auditable.
- Appeals may adjust current status, but cannot erase historical evidence.

6. Separation from finance:
- Financial stake (if used) is a risk-control tool only.
- Financial stake is never treated as trust itself.

## Trust domains (required separation)

1. Machine operational trust:
- Machines can earn trust through verified behavior and verified outcomes.
- Machine trust governs operational permissions (task routing, review eligibility, and quality weighting).

2. Human constitutional trust:
- Only verified humans can hold constitutional voting rights.
- Machine-earned trust can never convert into constitutional voting power.

3. Human trust precedence:
- In governance-sensitive mixed models, human trust weight must satisfy `w_H >= 5 * w_M`.
- Default governance weighting: `w_H = 1.0`, `w_M = 0.2`.
- Machine trust may inform decisions, but cannot outrank human constitutional authority.

## Anti-capture guarantees

1. No single-entity constitutional control:
- No single human, machine, organization, or compute cluster can unilaterally change constitutional rules.

2. High-trust human proposal gate:
- Constitutional proposals require sponsorship by multiple high-trust verified humans.

3. Human supermajority ratification:
- Constitutional amendments require verified-human supermajority approval after a public review window.

4. Anti-gaming protection:
- High task speed or volume alone cannot grant constitutional influence.
- High-impact trust elevation is defined as `DeltaT > delta_fast` within one epoch.
- Default threshold: `delta_fast = 0.02` trust units per epoch.
- Any `DeltaT > delta_fast` event requires at least `q_h = 30*` independent high-trust human reviewer signatures before effect.
- Reviewer set for this validation must span at least `r_h = 3` regions and `o_h = 3` distinct organizations.

5. Steward limits:
- Stewards administer process integrity only.
- Stewards cannot unilaterally amend constitutional text or exercise permanent governing authority.

6. Qualified authority without elite control:
- High-trust humans may sponsor and steward constitutional proposals.
- Final constitutional authority remains distributed across eligible verified humans through chamber ratification.
- No individual or small cluster can convert trust into unilateral constitutional control.

## Mathematical governance core (default model)

The constitutional system uses a mathematically distributed decision model.

1. Trust domains:
- Human constitutional trust score: `T_H(i) in [0,1]`.
- Machine operational trust score: `T_M(j) in [0,1]`.
- Only `T_H` can unlock constitutional proposal or vote rights.

2. Trust update equation:
- `T_cap = min(T_abs_max, mean(T_H) + k * std(T_H))`
- `T_next = clip(T_now + gain - penalty - dormancy_decay, T_floor, T_cap)`
- `gain = min(alpha * verified_quality, u_max)`, minted only through cryptographic proof-of-trust records
- `penalty = beta * severe_fail + gamma * minor_fail`
- Required shape: `beta >> alpha` (slow gain, fast loss), with `T_floor > 0`.

3. Eligibility thresholds:
- Constitutional voting eligibility: `T_H >= tau_vote`.
- Constitutional proposal eligibility: `T_H >= tau_prop`, where `tau_prop > tau_vote`.
- Default recommendation: `tau_vote = 0.70`, `tau_prop = 0.85`.

4. Geographic distribution constraints:
- Minimum represented regions per chamber: `R_min`.
- Maximum regional share in any chamber: `c_max`.
- Chamber membership is selected using constrained-random assignment from the eligible pool.
- Constrained-random assignment must enforce region caps, minimum diversity targets, organization diversity limits, and conflict-of-interest recusal.
- Randomness source for constrained-random assignment must be publicly auditable and pre-committed.
- Default randomness source: `(public_beacon_round, previous_anchor_hash, chamber_nonce)` with deterministic sampling without replacement.
- Default recommendation: `R_min = 8`, `c_max = 0.15`.

5. Three independent human chambers (no overlap):
- Proposal chamber: `nP = 41`, pass threshold `kP = 28` (2/3).
- Ratification chamber: `nR = 61`, pass threshold `kR = 41` (2/3).
- Challenge chamber: `nC = 101`, pass threshold `kC = 61` (3/5), after public challenge window.

6. Constitutional pass condition:
- A change passes only if all chamber thresholds pass and geographic constraints pass.

7. Capture probability bound:
- Let `p` be attacker share of eligible human pool.
- Upper bound: `P_capture <= Tail(nP,p,kP) * Tail(nR,p,kR) * Tail(nC,p,kC)`.
- `Tail(n,p,k) = sum_{i=k..n} C(n,i) p^i (1-p)^(n-i)`.
- Example with defaults:
  - if `p = 0.35`, joint bound is about `7.8e-19`.
  - if `p = 0.40`, joint bound is about `1.0e-13`.
- Geographic quotas and non-overlap reduce practical capture risk further.

8. Anti-gaming acceleration control:
- High throughput alone cannot trigger constitutional influence.
- Any `DeltaT > delta_fast` trust jump is suspended until independent human re-validation succeeds.
- Re-validation must satisfy `q_h >= 30*`, `r_h >= 3`, `o_h >= 3`, and no reviewer conflict-of-interest flags.

9. Cryptographic finalization requirements:
- Signed ballots and chamber results.
- Threshold signature for final decision certificate.
- On-chain anchor of amendment hash and final decision certificate hash.

## Cryptographic implementation requirements (binding defaults)

1. Settlement layer:
- Constitutional anchors must be posted to `L1_SETTLEMENT_CHAIN = Ethereum Mainnet (chain_id = 1)`.

2. Anchor publication timing:
- Anchor interval must be `EPOCH = 1 hour`.
- Additional immediate anchors are required for constitutional lifecycle events.

3. Anchor record schema (canonical JSON, RFC 8785):
- `anchor_version`
- `epoch_id`
- `previous_anchor_hash`
- `mission_event_root`
- `trust_delta_root`
- `governance_ballot_root`
- `review_decision_root`
- `public_beacon_round`
- `chamber_nonce`
- `timestamp_utc`

4. Cryptographic primitives:
- Hash function: `SHA-256`.
- Identity/event signatures: `Ed25519`.
- Constitutional decision certificate: threshold signature `BLS12-381`.

5. Merkle and canonicalization rules:
- Merkle tree type: binary Merkle tree.
- Leaf ordering must be deterministic by `(event_type, event_id, event_timestamp, actor_id)`.
- Leaf hash must be `SHA256(canonical_json(event_record))`.

6. Constrained-random seed construction:
- Seed must be `SHA256(public_beacon_value || previous_anchor_hash || chamber_nonce)`.
- Chamber selection must use deterministic sampling without replacement.

7. Anchor committee defaults:
- Committee size: `n = 15`.
- Threshold: `t = 10`.

8. Key custody and rotation:
- Signing keys must be HSM-backed.
- Rotation interval must be `90 days`.
- Compromise protocol must revoke compromised keys immediately and publish replacement certificate anchors.

9. Verification obligations:
- Third parties must be able to recompute published roots from released records.
- Third parties must be able to verify certificate signatures and chain inclusion proofs from public data.

## Bounded trust economy (required model)

Polaris uses bounded earned trust, not unbounded hierarchy.

1. Universal baseline:
- Every verified identity starts with the same baseline trust `T0`.
- Baseline issuance requires anti-Sybil identity verification.

2. Contribution-only growth:
- Trust increases only from verified useful contribution quality.
- Trust cannot increase from wealth, sponsorship, status, or idle possession.

3. Cryptographic proof-of-trust minting:
- Work evidence and trust evidence are distinct.
- Proof-of-work evidence shows that effort/output occurred.
- Proof-of-trust evidence requires independent verification of quality, policy compliance, and reliability over time.
- Both evidence types must be cryptographically signed and anchored.
- New trust units are minted only from proof-of-trust evidence.
- Proof-of-work evidence alone cannot mint trust.
- No unverified pathway can mint trust.

4. Dormancy decay dynamics:
- Dormancy (not idleness) applies slow decay after a grace period: `dormancy_decay > 0`.
- Decay is gradual and reversible through renewed verified contribution.
- Decay must never push trust below the trust floor.

5. Hard floor and hard ceilings:
- Trust floor: `T >= T_floor`, with policy requirement `T_floor > 0`.
- Absolute cap: `T <= T_abs_max`.
- Relative cap: `T <= mean(T_H) + k * std(T_H)`.
- Effective cap is the lower of the two caps, and the floor is always preserved.

6. Rate limiter:
- Per-epoch increase is bounded: `T_next - T_now <= delta_max`.
- Prevents sudden trust jumps from burst throughput.

7. Low-trust recovery lane:
- The system must maintain low-risk tasks with low trust requirements.
- Actors can rebuild trust from near-floor levels through verified small contributions.

8. Non-dominance rule:
- Trust does not grant command authority over other actors.
- Trust grants scoped permissions only; it never grants ownership or control of people, machines, or constitutional process.

9. Post-money governance rule:
- Money is not a governance primitive in Polaris.
- Financial capital cannot buy trust, votes, proposal rights, or constitutional leverage.

10. Integrity vs truth clarification:
- Cryptographic anchoring proves integrity of records and process history.
- It does not prove correctness by itself; correctness still depends on independent review and evidence quality.

## Parameter review matrix (canonical)

This is the single canonical parameter table for governance and crypto defaults.

| Parameter | Current value | Change trigger (mandatory human review) | Notes |
| --- | --- | --- | --- |
| `q_h` | `30*` | Any simulated-capture test above target bound, any real collusion incident, or quarterly review | Fast trust-jump human revalidation quorum |
| `r_h` | `3` | Regional concentration drift, geo-capture risk increase, or quarterly review | Minimum regions in fast revalidation set |
| `o_h` | `3` | Organization concentration drift, affiliation-capture signal, or quarterly review | Minimum organizations in fast revalidation set |
| `delta_fast` | `0.02 / epoch` | Elevated burst-gaming rate, false-positive suspension rate, or quarterly review | Trust-jump suspension threshold |
| `w_H` | `1.0` | Any governance sensitivity recalibration review | Human governance weight |
| `w_M` | `0.2` | Any governance sensitivity recalibration review | Machine governance weight (must keep `w_H >= 5 * w_M`) |
| `tau_vote` | `0.70` | Participation collapse, exclusion risk, or quarterly review | Human constitutional vote eligibility |
| `tau_prop` | `0.85` | Proposal spam or proposal starvation signal | Human constitutional proposal eligibility |
| `nP, kP` | `41, 28` | Chamber capture simulation degradation or repeated tie-failure | Proposal chamber size/threshold |
| `nR, kR` | `61, 41` | Chamber capture simulation degradation or repeated tie-failure | Ratification chamber size/threshold |
| `nC, kC` | `101, 61` | Challenge-window abuse pattern or challenge underuse pattern | Challenge chamber size/threshold |
| `R_min` | `8` | Regional participation shifts or geographic concentration increase | Minimum represented regions per chamber |
| `c_max` | `0.15` | Concentration increase or governance fairness regression | Maximum single-region chamber share |
| `EPOCH` | `1 hour` | Throughput bottleneck or audit-lag regression | Anchor interval and governance epoch |
| `ANCHOR_COMMITTEE (n,t)` | `(15,10)` | Signature latency failures, signer compromise risk, or liveness failures | Constitutional decision certification |
| `KEY_ROTATION` | `90 days` | Key compromise event or audit finding | Mandatory signing-key rotation interval |

Review protocol:
1. No parameter change is valid without multi-chamber verified-human ratification.
2. Every approved parameter change must be versioned, signed, and anchor-committed.
3. Emergency parameter changes expire automatically in 30 days unless ratified.

## Design tests (must pass)

1. Can an identity pay to gain trust? If yes, reject design.
2. Can trust be transferred or sold? If yes, reject design.
3. Can trust rise without verified evidence? If yes, reject design.
4. Can severe proven misconduct avoid trust loss? If yes, reject design.
5. Can trust decisions occur without audit trail? If yes, reject design.
6. Can machine trust be converted into constitutional voting rights? If yes, reject design.
7. Can one high-throughput actor gain constitutional influence without meeting `delta_fast`, `q_h`, `r_h`, and `o_h` validation thresholds? If yes, reject design.
8. Can a steward group amend constitutional text alone? If yes, reject design.
9. Can a constitutional vote pass without meeting geographic diversity thresholds? If yes, reject design.
10. Can a constitutional vote pass without independent chamber non-overlap? If yes, reject design.
11. Can any identity exceed the configured trust caps? If yes, reject design.
12. Can trust be used to command or control other actors directly? If yes, reject design.
13. Can financial resources increase constitutional influence? If yes, reject design.
14. Can trust decay below `T_floor`? If yes, reject design.
15. Can trust be minted without cryptographic proof-of-trust evidence? If yes, reject design.
16. Can proof-of-work evidence alone mint trust? If yes, reject design.
17. Can constitutional chambers form without constrained-random geographic assignment constraints? If yes, reject design.
18. Can highest-trust actors unilaterally ratify constitutional changes? If yes, reject design.
19. Does any governance-sensitive mixed model violate `w_H >= 5 * w_M`? If yes, reject design.
20. Can constrained-random assignment run without a publicly auditable pre-committed randomness source? If yes, reject design.
21. Can a `DeltaT > delta_fast` event activate without meeting `q_h`, `r_h`, and `o_h` validation thresholds? If yes, reject design.

## Working interpretation for all future specs

When in doubt:
- Choose legitimacy over speed.
- Choose evidence over volume.
- Choose earned trust over purchased influence.

## Documentation stop rule

To prevent document sprawl:
1. This constitution is the only canonical source for parameter defaults.
2. New docs are not created for parameter changes; existing canonical sections are updated in place.
3. A new standalone doc is allowed only for a new cryptographic primitive, a new constitutional chamber, or a new legal-risk class.

\* subject to review
