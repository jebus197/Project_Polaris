# Project Genesis - Trust Constitution

Date: February 13, 2026
Status: Foundational, non-negotiable
Author: George Jackson

## Core Rule

Trust cannot be bought, sold, exchanged, delegated, rented, inherited, or gifted.

Trust can only be earned through verified behavior and verified outcomes over time.

## Why this exists

Genesis is designed as a credibility system, not a market for influence.

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
- Financial capital has no role in trust scoring, proposal eligibility, or constitutional voting.
- Any optional operational collateral (if ever introduced) must be strictly separated from trust computation.

7. Identity-signal scope control:
- Proof-of-personhood, proof-of-agenthood, timing tests, or hardware attestations are support signals only.
- Identity signals cannot, by themselves, mint trust, grant privileged routing, or grant constitutional authority.

## Trust domains (required separation)

1. Machine operational trust:
- Machines can earn trust through verified behavior and verified outcomes.
- Machine trust governs operational permissions (task routing, review eligibility, and quality weighting).

2. Human constitutional trust:
- Only verified humans can hold constitutional voting rights.
- Machine-earned trust can never convert into constitutional voting power.

3. Constitutional voting lock:
- Machine constitutional voting weight is fixed at `w_M_const = 0`.
- Human constitutional voting weight is fixed at `w_H_const = 1`.
- Any constitutional voting configuration where `w_M_const > 0` is invalid and must be rejected.
- Machine trust may inform operational routing and quality weighting only; it has no vote in constitutional ballots.

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

## Threat modelling requirement

Threat modelling means defining:
1. what must be protected,
2. who can cause harm,
3. how harm can occur,
4. which controls prevent or contain harm.

Constitutional rule:
1. Threat modelling is mandatory for governance and trust-system changes.
2. Any change that alters trust, review, or constitutional flow must include threat-impact analysis.
3. High-severity incidents trigger mandatory threat-model review and invariant reassessment.

## Mathematical governance core (default model)

The constitutional system uses a mathematically distributed decision model.

1. Trust domains:
- Human constitutional trust score: `T_H(i) in [0,1]`.
- Machine operational trust score: `T_M(j) in [0,1]`.
- Only `T_H` can unlock constitutional proposal or vote rights.

2. Trust update equation:
- Human cap: `T_cap_H = min(T_abs_max_H, mean(T_H) + k_H * std(T_H))`.
- Machine cap: `T_cap_M = T_abs_max_M`.
- Human update: `T_H_next = clip(T_H_now + gain_H - penalty_H - dormancy_decay_H, T_floor_H, T_cap_H)`.
- Machine update: `T_M_next = clip(T_M_now + gain_M - penalty_M - freshness_decay_M, 0, T_cap_M)`.
- Human floor requirement: `T_floor_H > 0`.
- Machine floor requirement: `T_floor_M = 0`.
- `score_H = w_Q * Q_H + w_R * R_H + w_V * V_H`.
- `score_M = w_Q * Q_M + w_R * R_M + w_V * V_M`.
- Quality gate: if `Q_H < Q_min_H` then `gain_H = 0`; if `Q_M < Q_min_M` then `gain_M = 0`.
- `gain_H = min(alpha_H * score_H, u_max_H)` and `gain_M = min(alpha_M * score_M, u_max_M)`.
- `gain_H` and `gain_M` are minted only through cryptographic proof-of-trust records.
- Weight constraints: `w_Q + w_R + w_V = 1`, with `w_Q >= 0.70` and `w_V <= 0.10`.
- `penalty_H = beta_H * severe_fail + gamma_H * minor_fail`.
- `penalty_M = beta_M * severe_fail + gamma_M * minor_fail`.
- Freshness decay input for machines must include verification age and environment drift terms.
- Required shape: `beta_H >> alpha_H` and `beta_M >> alpha_M` (slow gain, fast loss).

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
- Default randomness source: `(public_beacon_round, previous_commitment_hash, chamber_nonce)` with deterministic sampling without replacement.
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
- On-chain commitment of amendment hash and final decision certificate hash.

## Cryptographic implementation requirements (binding defaults)

1. Settlement layer:
- Constitutional commitments must be posted to `L1_SETTLEMENT_CHAIN = Ethereum Mainnet (chain_id = 1)`.

2. On-chain publication timing:
- Commitment interval must be `EPOCH = 1 hour`.
- Additional immediate commitments are required for constitutional lifecycle events.

3. Commitment record schema (canonical JSON, RFC 8785):
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

4. Cryptographic primitives:
- Hash function: `SHA-256`.
- Identity/event signatures: `Ed25519`.
- Constitutional decision certificate: threshold signature `BLS12-381`.

5. Merkle and canonicalization rules:
- Merkle tree type: binary Merkle tree.
- Leaf ordering must be deterministic by `(event_type, event_id, event_timestamp, actor_id)`.
- Leaf hash must be `SHA256(canonical_json(event_record))`.

6. Constrained-random seed construction:
- Seed must be `SHA256(public_beacon_value || previous_commitment_hash || chamber_nonce)`.
- Chamber selection must use deterministic sampling without replacement.

7. Commitment committee defaults:
- Committee size: `n = 15`.
- Threshold: `t = 10`.

8. Key custody and rotation:
- Signing keys must be HSM-backed.
- Rotation interval must be `90 days`.
- Compromise protocol must revoke compromised keys immediately and publish replacement certificate commitments.

9. Verification obligations:
- Third parties must be able to recompute published roots from released records.
- Third parties must be able to verify certificate signatures and chain inclusion proofs from public data.

## Bounded trust economy (required model)

Genesis uses bounded earned trust, not unbounded hierarchy.

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
- Both evidence types must be cryptographically signed and blockchain-recorded.
- New trust units are minted only from proof-of-trust evidence.
- Proof-of-work evidence alone cannot mint trust.
- No unverified pathway can mint trust.

4. Human dormancy decay dynamics:
- Human dormancy applies slow decay after a grace period: `dormancy_decay_H > 0`.
- Human decay is gradual and reversible through renewed verified contribution.
- Human trust cannot decay below the human floor: `T_H >= T_floor_H`, with `T_floor_H > 0`.

5. Machine freshness decay dynamics:
- Machine trust decay is freshness-based, not task-count based.
- Freshness decay term: `freshness_decay_M = lambda_age * staleness + lambda_drift * env_drift`.
- No verified useful work over time causes a slow burn in machine trust.
- Machine trust may decay to zero: `T_M >= 0`.

6. Hard floors and hard ceilings:
- Human floor: `T_H >= T_floor_H`, with policy requirement `T_floor_H > 0`.
- Machine floor: `T_M >= 0`.
- Human cap: `T_H <= min(T_abs_max_H, mean(T_H) + k_H * std(T_H))`.
- Machine cap: `T_M <= T_abs_max_M`.

7. Rate limiter:
- Per-epoch increase is bounded separately for humans and machines.
- Human limiter: `T_H_next - T_H_now <= delta_max_H`.
- Machine limiter: `T_M_next - T_M_now <= delta_max_M`.
- Prevents sudden trust jumps from burst throughput.

8. Recovery lanes:
- The system must maintain low-risk tasks with low trust requirements for human recovery.
- Humans can rebuild trust from near-floor levels through verified small contributions.
- Machines can rebuild trust only through supervised re-certification and verified benchmark tasks.

9. Machine zero-trust quarantine rule:
- If `T_M = 0`, machine identity enters operational quarantine.
- Quarantined machine identities cannot receive privileged task routing or reviewer privileges.
- Re-entry requires successful re-certification with independent reviewer signatures and blockchain-logged evidence.
- Re-certification minimums:
  - `correctness >= RECERT_CORRECTNESS_MIN`,
  - `severe_error_rate <= RECERT_SEVERE_ERR_MAX`,
  - `reproducibility >= RECERT_REPRO_MIN`,
  - independent human reviewer signatures `>= RECERT_REVIEW_SIGS`.
- Re-certified machine identities must complete `RECERT_PROBATION_TASKS` low-risk tasks before privileged routing can be restored.
- Decommission triggers:
  - machine remains at `T_M = 0` for `>= M_ZERO_DECOMMISSION_DAYS` with no successful re-certification, or
  - machine records `>= M_RECERT_FAIL_MAX` failed re-certifications within `M_RECERT_FAIL_WINDOW_DAYS`, or
  - machine is proven malicious in a high-severity incident.
- Decommissioned machine identities cannot be reactivated in place; any re-entry must occur as a new identity with lineage linkage and extended probation.
- Identity reset must not bypass quarantine; machine lineage and signing identity continuity checks are mandatory.

10. Non-dominance rule:
- Trust does not grant command authority over other actors.
- Trust grants scoped permissions only; it never grants ownership or control of people, machines, or constitutional process.

11. Post-money governance rule:
- Money is not a governance primitive in Genesis.
- Financial capital cannot buy trust, votes, proposal rights, or constitutional leverage.

12. Integrity vs truth clarification:
- Cryptographic commitment records prove integrity of records and process history.
- It does not prove correctness by itself; correctness still depends on independent review and evidence quality.

## Parameter review matrix (canonical)

This is the single canonical parameter table for governance and crypto defaults.

| Parameter | Current value | Change trigger (mandatory human review) | Notes |
| --- | --- | --- | --- |
| `q_h` | `30*` | Any simulated-capture test above target bound, any real collusion incident, or quarterly review | Fast trust-jump human revalidation quorum |
| `r_h` | `3` | Regional concentration drift, geo-capture risk increase, or quarterly review | Minimum regions in fast revalidation set |
| `o_h` | `3` | Organization concentration drift, affiliation-capture signal, or quarterly review | Minimum organizations in fast revalidation set |
| `delta_fast` | `0.02 / epoch` | Elevated burst-gaming rate, false-positive suspension rate, or quarterly review | Trust-jump suspension threshold |
| `T_floor_H` | `> 0` | Constitutional amendment only | Human trust floor (non-zero by constitutional rule) |
| `T_floor_M` | `0.0` | Constitutional amendment only | Machine trust floor (zero by constitutional rule) |
| `freshness_decay_M` | `lambda_age * staleness + lambda_drift * env_drift` | Any stale-model incident, drift incident, or quarterly review | Machine slow-burn decay function |
| `delta_max_H` | `policy-set` | Trust-volatility review or quarterly review | Human per-epoch growth limiter |
| `delta_max_M` | `policy-set` | Trust-volatility review or quarterly review | Machine per-epoch growth limiter |
| `w_Q, w_R, w_V` | `0.75, 0.20, 0.05` | Evidence-quality drift, volume gaming signal, or quarterly review | Trust gain weights (`w_Q + w_R + w_V = 1`, `w_Q >= 0.70`, `w_V <= 0.10`) |
| `Q_min_H` | `0.70` | Human-review quality regression or quarterly review | Human minimum quality gate for trust gain |
| `Q_min_M` | `0.80` | Machine-review quality regression or quarterly review | Machine minimum quality gate for trust gain |
| `RECERT_CORRECTNESS_MIN` | `0.95` | Re-cert false-pass signal or quarterly review | Machine re-cert minimum correctness |
| `RECERT_SEVERE_ERR_MAX` | `0.005` | Safety incident trend or quarterly review | Machine re-cert maximum severe error rate |
| `RECERT_REPRO_MIN` | `0.99` | Reproducibility drift or quarterly review | Machine re-cert minimum reproducibility |
| `RECERT_REVIEW_SIGS` | `5` | Reviewer diversity concerns or quarterly review | Minimum independent human signatures for machine re-cert |
| `RECERT_PROBATION_TASKS` | `100` | Post-re-cert incident trend or quarterly review | Low-risk probation workload before privilege restoration |
| `M_ZERO_DECOMMISSION_DAYS` | `180` | Accumulating zero-trust inactive fleet or quarterly review | Maximum zero-trust duration before decommission |
| `M_RECERT_FAIL_MAX` | `3` | Re-cert abuse trend or quarterly review | Maximum failed re-cert attempts before decommission |
| `M_RECERT_FAIL_WINDOW_DAYS` | `180` | Re-cert abuse trend or quarterly review | Rolling window for failed re-cert threshold |
| `w_H_const` | `1.0` | Constitutional amendment only | Human constitutional voting weight |
| `w_M_const` | `0.0` | Constitutional amendment only | Machine constitutional voting weight (must remain zero) |
| `tau_vote` | `0.70` | Participation collapse, exclusion risk, or quarterly review | Human constitutional vote eligibility |
| `tau_prop` | `0.85` | Proposal spam or proposal starvation signal | Human constitutional proposal eligibility |
| `nP, kP` | `41, 28` | Chamber capture simulation degradation or repeated tie-failure | Proposal chamber size/threshold |
| `nR, kR` | `61, 41` | Chamber capture simulation degradation or repeated tie-failure | Ratification chamber size/threshold |
| `nC, kC` | `101, 61` | Challenge-window abuse pattern or challenge underuse pattern | Challenge chamber size/threshold |
| `R_min` | `8` | Regional participation shifts or geographic concentration increase | Minimum represented regions per chamber |
| `c_max` | `0.15` | Concentration increase or governance fairness regression | Maximum single-region chamber share |
| `EPOCH` | `1 hour` | Throughput bottleneck or audit-lag regression | Commitment interval and governance epoch |
| `G0_MAX_DAYS` | `365` | Bootstrap velocity review | Maximum G0 founder stewardship duration |
| `G0_EXTENSION_DAYS` | `180` | Bootstrap velocity review | One-time G0 extension if threshold not met |
| `G1_MAX_DAYS` | `730` | Bootstrap velocity review | Maximum G1 provisional governance duration |
| `G0_RATIFICATION_WINDOW` | `90 days` | G0 decision review backlog | Window for retroactive ratification of G0 decisions |
| `nP_g1, kP_g1` | `11, 8` | Genesis capture simulation | G1 provisional proposal chamber |
| `nR_g1, kR_g1` | `17, 12` | Genesis capture simulation | G1 provisional ratification chamber |
| `nC_g1, kC_g1` | `25, 15` | Genesis capture simulation | G1 provisional challenge chamber |
| `R_min_g1` | `3` | Genesis geographic coverage | G1 minimum regions per chamber |
| `c_max_g1` | `0.40` | Genesis concentration review | G1 maximum region share |
| `q_h_g1` | `7` | Genesis revalidation capacity | G1 fast-elevation quorum |
| `nP_g2, kP_g2` | `21, 14` | Growth-phase capture simulation | G2 proposal chamber |
| `nR_g2, kR_g2` | `31, 21` | Growth-phase capture simulation | G2 ratification chamber |
| `nC_g2, kC_g2` | `51, 31` | Growth-phase capture simulation | G2 challenge chamber |
| `R_min_g2` | `5` | Growth-phase geographic coverage | G2 minimum regions per chamber |
| `c_max_g2` | `0.25` | Growth-phase concentration review | G2 maximum region share |
| `q_h_g2` | `15` | Growth-phase revalidation capacity | G2 fast-elevation quorum |
| `L1_ANCHOR_INTERVAL_C0` | `24 hours` | Commitment cost vs. audit-lag tradeoff | C0 L1 anchor frequency |
| `L1_ANCHOR_INTERVAL_C1` | `6 hours` | Commitment cost vs. audit-lag tradeoff | C1 L1 anchor frequency |
| `H_R2_MODEL_FAMILIES` | `2` | Correlated-error incident or monoculture signal | R2 minimum distinct model families |
| `H_R2_METHOD_TYPES` | `2` | Verification method diversity regression | R2 minimum distinct method types |
| `NORMATIVE_AGREEMENT_THRESHOLD` | `0.60` | Normative dispute under-escalation or over-escalation rate | Escalation trigger for normative tasks |
| `NORMATIVE_PANEL_SIZE` | `3` | Normative dispute resolution quality review | Human adjudication panel size |
| `NORMATIVE_PANEL_REGIONS` | `2` | Panel geographic diversity review | Minimum regions on normative panel |
| `NORMATIVE_PANEL_ORGS` | `2` | Panel organizational diversity review | Minimum orgs on normative panel |
| `COMMITMENT_COMMITTEE (n,t)` | `(15,10)` | Signature latency failures, signer compromise risk, or liveness failures | Constitutional decision certification |
| `KEY_ROTATION` | `90 days` | Key compromise event or audit finding | Mandatory signing-key rotation interval |

Review protocol:
1. No parameter change is valid without multi-chamber verified-human ratification.
2. Every approved parameter change must be versioned, signed, and committed on-chain.
3. Emergency parameter changes expire automatically in 30 days unless ratified.

Calibration protocol (mandatory before production and at quarterly review):
1. Build replay datasets from completed missions across each risk tier (`R0`, `R1`, `R2`).
2. Run adversarial simulations for collusion, throughput gaming, low-quality flooding, and identity-farming paths.
3. Evaluate parameter sensitivity for:
- quality gates (`Q_min_H`, `Q_min_M`),
- trust weights (`w_Q`, `w_R`, `w_V`),
- re-certification thresholds,
- decommission thresholds.
4. Reject any parameter proposal that increases high-risk false-accept rate or weakens anti-capture guarantees.
5. Publish a calibration report containing:
- dataset composition,
- simulation assumptions,
- candidate parameter sets,
- selected set with rationale,
- rollback path.
6. Apply only after constitutional ratification and on-chain versioned parameter publication.

Executable governance artifacts:
1. Machine-readable parameter mirror: `config/constitutional_params.json`.
2. Runtime tier policy map: `config/runtime_policy.json`.
3. Invariant checks: `python3 tools/check_invariants.py`.
4. Worked-example verification: `python3 tools/verify_examples.py`.

## Genesis bootstrap protocol (constitutional)

The constitutional governance model requires chamber sizes, geographic diversity, and organizational breadth that cannot exist at network launch. This creates a cold-start problem. The genesis protocol solves it with a phased, time-bounded escalation from founder authority to full constitutional governance.

### Genesis phases

1. Phase G0 — Founder stewardship (0 to 50 verified humans):
- The founder (or a small founding group of up to 5 verified humans) holds provisional governance authority.
- All governance decisions made during G0 are logged, signed, and committed on-chain with the tag `genesis_provisional`.
- No constitutional amendments are permitted during G0. The founding constitution is frozen.
- Operational risk tiers R0 and R1 are active. R2 operates with reduced reviewer requirements (see genesis parameter overrides below). R3 (constitutional changes) is locked.
- Trust minting operates normally under standard quality gates.
- G0 expires automatically at `G0_MAX_DAYS = 365` days. If 50 verified humans have not been reached, the founder must publish a public status report and the deadline extends by `G0_EXTENSION_DAYS = 180` days (once only).

2. Phase G1 — Provisional chambers (50 to 500 verified humans):
- Constitutional governance activates with reduced chamber sizes:
  - Provisional proposal chamber: `nP_g1 = 11`, pass threshold `kP_g1 = 8` (>2/3).
  - Provisional ratification chamber: `nR_g1 = 17`, pass threshold `kR_g1 = 12` (>2/3).
  - Provisional challenge chamber: `nC_g1 = 25`, pass threshold `kC_g1 = 15` (3/5).
- Geographic constraints are relaxed:
  - Minimum regions per chamber: `R_min_g1 = 3`.
  - Maximum region share: `c_max_g1 = 0.40`.
- All other constitutional rules apply (human-only voting, constrained-random assignment, non-overlap, conflict recusal).
- The fast-elevation quorum is reduced: `q_h_g1 = 7`, `r_h_g1 = 2`, `o_h_g1 = 2`.
- G1 expires automatically at `G1_MAX_DAYS = 730` days from genesis. Transition to G2 requires reaching 500 verified humans OR the expiry deadline, whichever comes first.
- All G0 provisional decisions are automatically submitted for G1 ratification within `G0_RATIFICATION_WINDOW = 90` days of G1 activation. Any G0 decision not ratified is reversed.

3. Phase G2 — Scaled chambers (500 to 2000 verified humans):
- Chamber sizes increase to intermediate values:
  - Proposal chamber: `nP_g2 = 21`, pass threshold `kP_g2 = 14` (2/3).
  - Ratification chamber: `nR_g2 = 31`, pass threshold `kR_g2 = 21` (2/3).
  - Challenge chamber: `nC_g2 = 51`, pass threshold `kC_g2 = 31` (3/5).
- Geographic constraints tighten:
  - Minimum regions: `R_min_g2 = 5`.
  - Maximum region share: `c_max_g2 = 0.25`.
- Fast-elevation quorum scales: `q_h_g2 = 15`, `r_h_g2 = 3`, `o_h_g2 = 3`.

4. Phase G3 — Full constitutional governance (2000+ verified humans):
- Full chamber sizes activate as defined in the main constitution (`nP=41, nR=61, nC=101`).
- Full geographic constraints activate (`R_min=8, c_max=0.15`).
- Full fast-elevation quorum activates (`q_h=30*, r_h=3, o_h=3`).
- Genesis protocol terminates. All subsequent governance is fully constitutional.

### Genesis invariants (non-negotiable at every phase)

1. Machine constitutional voting weight remains `w_M_const = 0` at all genesis phases.
2. Trust cannot be bought, sold, or transferred at any genesis phase.
3. Quality gates for trust minting are active from day one.
4. All governance actions are signed, committed on-chain, and publicly auditable from day one.
5. No genesis phase may extend indefinitely; all have hard time limits.
6. The founder has no constitutional veto power once G1 activates.
7. Every G0 provisional decision must face retroactive ratification in G1.
8. Phase transitions are one-way; the system cannot regress to an earlier genesis phase.

### Genesis phase determination formula

The active genesis phase is determined by:
- Let `N_H` = count of verified human identities with `T_H >= T_floor_H`.
- If `N_H < 50`: phase = G0.
- If `50 <= N_H < 500`: phase = G1.
- If `500 <= N_H < 2000`: phase = G2.
- If `N_H >= 2000`: phase = G3 (full constitution).

Time-limit overrides:
- If G0 duration exceeds `G0_MAX_DAYS + G0_EXTENSION_DAYS` and `N_H < 50`, the network must be publicly declared non-viable and shut down or restructured with a new genesis.

## Progressive commitment strategy (constitutional)

Ethereum L1 hourly commitments are specified as the production target. However, L1 gas costs are variable and may be prohibitive during early operation. The commitment strategy must be economically sustainable without compromising integrity.

### Commitment tiers

1. Tier C0 — Genesis and early operation (`N_H < 500`):
- Primary commitment layer: `L2_COMMITMENT_CHAIN` (any EVM-compatible L2 rollup that settles to Ethereum L1, e.g., Arbitrum, Optimism, Base).
- L2 commitment cadence: every `EPOCH = 1 hour` (same as production spec).
- L1 anchor cadence: batched L1 anchor commitment every `L1_ANCHOR_INTERVAL_C0 = 24 hours`.
- L1 anchor payload: `SHA256(concatenation of all L2 commitment hashes in the anchor window)` plus latest constitutional state root.
- Constitutional lifecycle events (proposal pass, ratification pass, challenge close, amendment activation) are committed to L1 immediately regardless of tier.

2. Tier C1 — Growth phase (`500 <= N_H < 5000`):
- L2 commitment cadence: every `1 hour`.
- L1 anchor cadence: every `L1_ANCHOR_INTERVAL_C1 = 6 hours`.
- Constitutional lifecycle events: immediate L1 commitment.

3. Tier C2 — Production (`N_H >= 5000`):
- Full L1 commitment every `1 hour` as specified in the main constitution.
- Constitutional lifecycle events: immediate L1 commitment.

### Commitment integrity invariants

1. At every tier, all commitment payloads use the same schema, hash function, signature suite, and Merkle rules as the production spec.
2. L2 commitments must be independently verifiable using the same public verifier tooling.
3. The L2 rollup must settle to Ethereum L1; no independent L1 chains are permitted as primary settlement.
4. L1 anchor commitments must include a chained hash linking all L2 commitments in the anchor window, so that any L2 commitment can be proven as included in the L1 anchor.
5. Transition between commitment tiers is automatic based on `N_H` and is logged on-chain.
6. No commitment tier reduces the cryptographic strength of any commitment; only the L1 publication frequency changes.

### Cost projection (conservative estimates)

At current L2 fee levels (2026):
- L2 commitment: `$0.01-$0.10` per transaction.
- Daily L2 cost (24 hourly commits): `$0.24-$2.40`.
- Daily L1 anchor (1 per day at C0): `$2-$20` depending on gas.
- Monthly total at C0: `$70-$680` (well within zero-budget envelope).

## Reviewer heterogeneity requirements (constitutional)

Independent review must be orthogonal, not merely numerous. Correlated errors across reviewers sharing identical model families, training data, or reasoning methods can defeat consensus-based verification even with high reviewer counts.

### Heterogeneity rules by risk tier

1. R0 (low risk):
- No heterogeneity constraint. Single reviewer is sufficient.

2. R1 (moderate risk):
- Reviewers must not share the same `model_family` identifier (e.g., both using GPT-4o, or both using Claude Opus).
- If all available reviewers share a model family, one reviewer may be substituted with a deterministic/rule-based check or a human reviewer.

3. R2 (high risk):
- At least `H_R2_MODEL_FAMILIES = 2` distinct model families must be represented among the 5 reviewers.
- At least `H_R2_METHOD_TYPES = 2` distinct verification method types must be used. Method types are: `reasoning_model`, `retrieval_augmented`, `rule_based_deterministic`, `human_reviewer`.
- Evidence bundles must include intermediate reasoning artifacts, not only final judgments.

4. R3 (constitutional):
- Human-only. Model heterogeneity is not applicable; constitutional voting diversity is enforced through geographic and organizational constraints.

### Reviewer metadata requirements

Every reviewer record must include:
1. `reviewer_id`
2. `model_family` (for machine reviewers) or `"human"` (for human reviewers)
3. `method_type`: one of `reasoning_model`, `retrieval_augmented`, `rule_based_deterministic`, `human_reviewer`
4. `region`
5. `organization`

### Anti-monoculture design test

Design test: Can all reviewers on an R2 task share the same model family and verification method? If yes, reject design.

## Subjective and normative dispute resolution protocol (constitutional)

Consensus-based verification works for objective, testable claims. It is structurally unreliable for subjective, interpretive, ethical, or normative questions where reasonable people can legitimately disagree. Genesis must handle both domains without pretending consensus resolves the latter.

### Domain classification requirement

Every mission must be classified at intake with a `domain_type`:

1. `objective`: the task has testable, reproducible acceptance criteria (e.g., "does this code compile?", "does this calculation match the input data?").
2. `normative`: the task involves interpretation, ethical judgment, policy framing, or value-laden assessment (e.g., "is this risk assessment balanced?", "is this policy recommendation fair?").
3. `mixed`: the task contains both objective and normative components.

### Resolution rules by domain type

1. `objective` tasks:
- Standard reviewer consensus applies.
- Disagreement resolved by evidence sufficiency and reproducibility.

2. `normative` tasks:
- Reviewer consensus is advisory, not dispositive.
- Final resolution requires human adjudication.
- The human adjudicator must document the reasoning basis for the decision.
- The adjudication record must include: the advisory reviewer positions, the human decision, and the stated rationale.
- No normative task may be closed as `Completed` without a signed human adjudication record.

3. `mixed` tasks:
- Objective components are resolved by reviewer consensus.
- Normative components are escalated to human adjudication.
- The task cannot close until both resolution paths are satisfied.

### Dispute escalation triggers

A normative dispute is automatically escalated if:
1. Reviewer agreement is below `NORMATIVE_AGREEMENT_THRESHOLD = 0.60` (i.e., fewer than 60% of reviewers agree).
2. Any reviewer flags the task as `normative_dispute`.
3. The mission owner flags the task as `normative_dispute`.

### Normative adjudication panel (for R2 tasks)

For R2 normative disputes:
1. A panel of `NORMATIVE_PANEL_SIZE = 3` independent human adjudicators is assembled.
2. Panel members must span at least `NORMATIVE_PANEL_REGIONS = 2` regions and `NORMATIVE_PANEL_ORGS = 2` organizations.
3. Panel decision is by majority.
4. Dissenting opinions are recorded and published with the decision.
5. The panel decision is final for that task instance but does not set binding precedent for future tasks (each normative decision is case-specific).

### Design tests for subjective resolution

1. Can a normative task be closed by machine consensus alone without human adjudication? If yes, reject design.
2. Can a normative adjudication occur without documented reasoning? If yes, reject design.
3. Can a normative panel be assembled from a single region or organization? If yes, reject design.

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
14. Can human trust decay below `T_floor_H`? If yes, reject design.
15. Can trust be minted without cryptographic proof-of-trust evidence? If yes, reject design.
16. Can proof-of-work evidence alone mint trust? If yes, reject design.
17. Can constitutional chambers form without constrained-random geographic assignment constraints? If yes, reject design.
18. Can highest-trust actors unilaterally ratify constitutional changes? If yes, reject design.
19. Does any constitutional voting path assign non-zero machine voting weight (`w_M_const > 0`)? If yes, reject design.
20. Can constrained-random assignment run without a publicly auditable pre-committed randomness source? If yes, reject design.
21. Can a `DeltaT > delta_fast` event activate without meeting `q_h`, `r_h`, and `o_h` validation thresholds? If yes, reject design.
22. Can a machine identity with `T_M = 0` bypass quarantine and access privileged operations? If yes, reject design.
23. Can machine identity reset or key rotation be used to bypass zero-trust lineage controls? If yes, reject design.
24. Can trust increase when `Q_H < Q_min_H` or `Q_M < Q_min_M`? If yes, reject design.
25. Can high output volume compensate for failing quality gate thresholds? If yes, reject design.
26. Can a machine remain at `T_M = 0` beyond decommission thresholds and still retain active status? If yes, reject design.
27. Can a decommissioned machine identity regain privileged access without full re-entry controls? If yes, reject design.
28. Can identity-signal tests alone grant trust or constitutional authority? If yes, reject design.
29. Can the system operate without a defined genesis phase when participant count is below full constitutional thresholds? If yes, reject design.
30. Can a genesis phase extend indefinitely without a hard time limit? If yes, reject design.
31. Can the founder retain veto power after provisional chambers activate in G1? If yes, reject design.
32. Can G0 provisional decisions survive without retroactive ratification in G1? If yes, reject design.
33. Can the system regress from a later genesis phase to an earlier one? If yes, reject design.
34. Can all reviewers on an R2 task share the same model family and verification method? If yes, reject design.
35. Can a normative task be closed by machine consensus alone without human adjudication? If yes, reject design.
36. Can a normative adjudication occur without documented reasoning? If yes, reject design.
37. Can L1 commitment integrity be reduced at any commitment tier (C0/C1/C2)? If yes, reject design.

## Working interpretation for all future specs

When in doubt:
- Choose legitimacy over speed.
- Choose evidence over volume.
- Choose earned trust over purchased influence.
- Choose measurable risk reduction over absolute claims.

## Blockchain Anchoring Record

This constitution is anchored on-chain. The anchoring event creates permanent, tamper-evident proof that this document existed in its exact form at the recorded time.

Blockchain anchoring is not a smart contract. No code executes on-chain. The SHA-256 hash of this document is embedded in the `data` field of a standard Ethereum transaction. The blockchain serves as a public, immutable witness.

| Field | Value |
|---|---|
| Document | `TRUST_CONSTITUTION.md` |
| SHA-256 | `33f2b00386aef7e166ce0e23f082a31ae484294d9ff087ddb45c702ddd324a06` |
| Chain | Ethereum Sepolia (Chain ID 11155111) |
| Block | 10255231 |
| Sender | [`0xC3676587a06b33A07a9101eB9F30Af9Fb988F7CE`](https://sepolia.etherscan.io/address/0xC3676587a06b33A07a9101eB9F30Af9Fb988F7CE) |
| Transaction | [`031617e394e0aee1875102fb5ba39ad5ad18ea775e1eeb44fd452ecd9d8a3bdb`](https://sepolia.etherscan.io/tx/031617e394e0aee1875102fb5ba39ad5ad18ea775e1eeb44fd452ecd9d8a3bdb) |
| Anchored | 2026-02-13T23:47:25Z |

**Independent verification:**

```bash
shasum -a 256 TRUST_CONSTITUTION.md
# Expected: 33f2b00386aef7e166ce0e23f082a31ae484294d9ff087ddb45c702ddd324a06
```

Then open the transaction on [Etherscan](https://sepolia.etherscan.io/tx/031617e394e0aee1875102fb5ba39ad5ad18ea775e1eeb44fd452ecd9d8a3bdb) and confirm the Input Data field contains the same hash.

**Important:** The hash above corresponds to the version of this constitution that was anchored. Any subsequent edits to this document will change the hash. Future versions should be re-anchored and logged in [`docs/ANCHORS.md`](docs/ANCHORS.md).

## Documentation stop rule

To prevent document sprawl:
1. This constitution is the only canonical source for parameter defaults.
2. New docs are not created for parameter changes; existing canonical sections are updated in place.
3. A new standalone doc is allowed only for a new cryptographic primitive, a new constitutional chamber, or a new legal-risk class.

\* subject to review
