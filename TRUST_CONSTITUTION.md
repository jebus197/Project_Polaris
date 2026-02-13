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
- In governance-sensitive mixed models, human trust weight must remain significantly above machine trust weight.
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
- High-impact trust elevation requires broad independent verification by high-trust humans.

5. Steward limits:
- Stewards administer process integrity only.
- Stewards cannot unilaterally amend constitutional text or exercise permanent governing authority.

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
- Any rapid trust jump requires broad independent validation by trusted humans across regions before effect.

9. Cryptographic finalization requirements:
- Signed ballots and chamber results.
- Threshold signature for final decision certificate.
- On-chain anchor of amendment hash and final decision certificate hash.

## Bounded trust economy (required model)

Polaris uses bounded earned trust, not unbounded hierarchy.

1. Universal baseline:
- Every verified identity starts with the same baseline trust `T0`.
- Baseline issuance requires anti-Sybil identity verification.

2. Contribution-only growth:
- Trust increases only from verified useful contribution quality.
- Trust cannot increase from wealth, sponsorship, status, or idle possession.

3. Cryptographic proof-of-trust minting:
- New trust units are minted only from verified contribution events.
- Every mint event must have cryptographic proof-of-trust evidence (signed evidence bundle + anchored record).
- Design intent: this is a governance analogue of cryptographic proof-of-work, reframed as cryptographic proof-of-trust.
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

## Design tests (must pass)

1. Can an identity pay to gain trust? If yes, reject design.
2. Can trust be transferred or sold? If yes, reject design.
3. Can trust rise without verified evidence? If yes, reject design.
4. Can severe proven misconduct avoid trust loss? If yes, reject design.
5. Can trust decisions occur without audit trail? If yes, reject design.
6. Can machine trust be converted into constitutional voting rights? If yes, reject design.
7. Can one high-throughput actor gain constitutional influence without broad trusted-human verification? If yes, reject design.
8. Can a steward group amend constitutional text alone? If yes, reject design.
9. Can a constitutional vote pass without meeting geographic diversity thresholds? If yes, reject design.
10. Can a constitutional vote pass without independent chamber non-overlap? If yes, reject design.
11. Can any identity exceed the configured trust caps? If yes, reject design.
12. Can trust be used to command or control other actors directly? If yes, reject design.
13. Can financial resources increase constitutional influence? If yes, reject design.
14. Can trust decay below `T_floor`? If yes, reject design.
15. Can trust be minted without cryptographic proof-of-trust evidence? If yes, reject design.

## Working interpretation for all future specs

When in doubt:
- Choose legitimacy over speed.
- Choose evidence over volume.
- Choose earned trust over purchased influence.
