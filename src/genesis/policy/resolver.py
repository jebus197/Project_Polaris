"""Policy resolver — loads constitutional_params.json and runtime_policy.json
and exposes every runtime decision as a typed method call.

No magic. No defaults. If a value is missing from the config, it fails loud.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from genesis.models.mission import DomainType, MissionClass, RiskTier
from genesis.models.governance import Chamber, ChamberKind, GenesisPhase


@dataclass(frozen=True)
class TierPolicy:
    """Resolved policy for a single risk tier."""
    tier: RiskTier
    reviewers_required: int
    approvals_required: int
    human_final_gate: bool
    min_regions: int
    min_organizations: int
    constitutional_flow: bool
    min_model_families: int
    min_method_types: int


class PolicyResolver:
    """Loads and resolves all constitutional and runtime policy.

    Usage:
        resolver = PolicyResolver.from_config_dir(Path("config"))
        tier_policy = resolver.tier_policy(RiskTier.R2)
        chambers = resolver.chambers_for_phase(GenesisPhase.G1)
    """

    def __init__(
        self,
        params: dict[str, Any],
        policy: dict[str, Any],
        taxonomy: dict[str, Any] | None = None,
        skill_trust: dict[str, Any] | None = None,
        market_policy: dict[str, Any] | None = None,
        skill_lifecycle: dict[str, Any] | None = None,
        leave_policy: dict[str, Any] | None = None,
    ) -> None:
        self._params = params
        self._policy = policy
        self._taxonomy = taxonomy
        self._skill_trust = skill_trust
        self._market_policy = market_policy
        self._skill_lifecycle = skill_lifecycle
        self._leave_policy = leave_policy
        self._validate_versions()

    def _validate_versions(self) -> None:
        if "version" not in self._params:
            raise ValueError("constitutional_params.json missing version")
        if "version" not in self._policy:
            raise ValueError("runtime_policy.json missing version")

    # ------------------------------------------------------------------
    # Mission class → risk tier
    # ------------------------------------------------------------------

    def resolve_tier(self, mission_class: MissionClass) -> RiskTier:
        """Map a mission class to its risk tier."""
        mapping = self._policy["mission_class_to_tier"]
        tier_str = mapping.get(mission_class.value)
        if tier_str is None:
            raise ValueError(f"Unknown mission class: {mission_class.value}")
        return RiskTier(tier_str)

    # ------------------------------------------------------------------
    # Risk tier policy
    # ------------------------------------------------------------------

    def tier_policy(self, tier: RiskTier) -> TierPolicy:
        """Get the full policy for a risk tier."""
        tiers = self._policy["risk_tiers"]
        t = tiers.get(tier.value)
        if t is None:
            raise ValueError(f"Unknown risk tier: {tier.value}")
        return TierPolicy(
            tier=tier,
            reviewers_required=t["reviewers_required"],
            approvals_required=t["approvals_required"],
            human_final_gate=t["human_final_gate"],
            min_regions=t["min_regions"],
            min_organizations=t["min_organizations"],
            constitutional_flow=t["constitutional_flow"],
            min_model_families=t["min_model_families"],
            min_method_types=t["min_method_types"],
        )

    # ------------------------------------------------------------------
    # Trust weights and gates
    # ------------------------------------------------------------------

    def trust_weights(self) -> tuple[float, float, float, float]:
        """Return (w_Q, w_R, w_V, w_E) trust component weights."""
        tw = self._params["trust_weights"]
        return tw["w_Q"], tw["w_R"], tw["w_V"], tw["w_E"]

    def quality_gate(self, is_machine: bool) -> float:
        """Return the minimum quality score gate."""
        qg = self._params["quality_gates"]
        return qg["Q_min_M"] if is_machine else qg["Q_min_H"]

    def trust_floor(self, is_machine: bool) -> float:
        """Return the trust floor for the actor kind."""
        floors = self._params["trust_floors"]
        if is_machine:
            return floors["T_floor_M"]
        # Human floor is positive but the exact value is not fixed in config.
        # We return 0.01 as minimum positive value for humans.
        return 0.01 if floors["T_floor_H_positive"] else 0.0

    def delta_fast(self) -> float:
        """Return the fast-elevation threshold."""
        return self._params["fast_elevation"]["delta_fast"]

    def eligibility_thresholds(self) -> tuple[float, float]:
        """Return (tau_vote, tau_prop) eligibility thresholds."""
        el = self._params["eligibility"]
        return el["tau_vote"], el["tau_prop"]

    def effort_thresholds(self) -> dict[str, Any]:
        """Return effort-proportionality thresholds.

        Keys:
        - E_min_per_tier: dict mapping tier string to minimum effort score
        - E_suspicious_low: effort below this on any mission is a signal
        - E_max_credit: maximum effort credit (caps at 1.0)
        """
        return dict(self._params["effort_thresholds"])

    # ------------------------------------------------------------------
    # Constitutional voting weights
    # ------------------------------------------------------------------

    def constitutional_voting_weights(self) -> tuple[float, float]:
        """Return (w_H_const, w_M_const). w_M_const must be 0.0."""
        cv = self._params["constitutional_voting"]
        return cv["w_H_const"], cv["w_M_const"]

    # ------------------------------------------------------------------
    # Reviewer heterogeneity
    # ------------------------------------------------------------------

    def heterogeneity_requirements(self) -> tuple[int, int]:
        """Return (min_model_families, min_method_types) for R2."""
        het = self._params["reviewer_heterogeneity"]
        return het["H_R2_MODEL_FAMILIES"], het["H_R2_METHOD_TYPES"]

    def valid_method_types(self) -> set[str]:
        """Return the canonical set of valid reviewer method types."""
        return set(self._params["reviewer_heterogeneity"]["valid_method_types"])

    def valid_domain_types(self) -> set[str]:
        """Return the canonical set of valid domain types."""
        return set(self._policy["valid_domain_types"])

    # ------------------------------------------------------------------
    # Normative resolution
    # ------------------------------------------------------------------

    def normative_agreement_threshold(self) -> float:
        """Return the normative agreement threshold for escalation."""
        return self._params["normative_resolution"]["NORMATIVE_AGREEMENT_THRESHOLD"]

    def normative_panel_requirements(self) -> dict[str, int]:
        """Return normative adjudication panel requirements."""
        nr = self._params["normative_resolution"]
        return {
            "panel_size": nr["NORMATIVE_PANEL_SIZE"],
            "panel_regions": nr["NORMATIVE_PANEL_REGIONS"],
            "panel_orgs": nr["NORMATIVE_PANEL_ORGS"],
        }

    # ------------------------------------------------------------------
    # Genesis protocol
    # ------------------------------------------------------------------

    def genesis_time_limits(self) -> dict[str, int]:
        """Return genesis phase time limits in days."""
        g = self._params["genesis"]
        return {
            "G0_MAX_DAYS": g["G0_MAX_DAYS"],
            "G0_EXTENSION_DAYS": g["G0_EXTENSION_DAYS"],
            "G1_MAX_DAYS": g["G1_MAX_DAYS"],
            "G0_RATIFICATION_WINDOW_DAYS": g["G0_RATIFICATION_WINDOW_DAYS"],
        }

    def genesis_phase_thresholds(self) -> dict[str, int]:
        """Return population thresholds for genesis phase transitions."""
        return dict(self._params["genesis"]["phase_thresholds"])

    def chambers_for_phase(self, phase: GenesisPhase) -> dict[ChamberKind, Chamber]:
        """Return chamber definitions for a given governance phase."""
        if phase == GenesisPhase.G0:
            raise ValueError("G0 is founder stewardship — no chambers")

        if phase == GenesisPhase.G3:
            # Full constitution
            raw = self._params["full_constitution"]["chambers"]
        else:
            key = f"{phase.value}_chambers"
            raw = self._params["genesis"][key]

        result: dict[ChamberKind, Chamber] = {}
        for name in ("proposal", "ratification", "challenge"):
            kind = ChamberKind(name)
            c = raw[name]
            result[kind] = Chamber(
                kind=kind,
                size=c["size"],
                pass_threshold=c["pass_threshold"],
            )
        return result

    def geo_constraints_for_phase(self, phase: GenesisPhase) -> tuple[int, float]:
        """Return (R_min, c_max) geographic constraints for a phase."""
        if phase == GenesisPhase.G0:
            raise ValueError("G0 has no formal geo constraints")
        if phase == GenesisPhase.G3:
            geo = self._params["full_constitution"]["geo"]
        else:
            geo = self._params["genesis"][f"{phase.value}_geo"]
        return geo["R_min"], geo["c_max"]

    def fast_elevation_quorum(self, phase: GenesisPhase) -> tuple[int, int, int]:
        """Return (q_h, r_h, o_h) fast-elevation revalidation quorum."""
        if phase == GenesisPhase.G0:
            raise ValueError("G0 has no formal fast-elevation quorum")
        if phase == GenesisPhase.G3:
            fe = self._params["full_constitution"]["fast_elevation"]
        else:
            fe = self._params["genesis"][f"{phase.value}_fast_elevation"]
        return fe["q_h"], fe["r_h"], fe["o_h"]

    # ------------------------------------------------------------------
    # Commitment tiers
    # ------------------------------------------------------------------

    def epoch_hours(self) -> int:
        """Return the epoch duration in hours."""
        return self._params["commitment_tiers"]["EPOCH_HOURS"]

    def commitment_tier_thresholds(self) -> dict[str, int]:
        """Return population thresholds for commitment tier progression."""
        ct = self._params["commitment_tiers"]
        return {
            "C0_max_humans": ct["C0_max_humans"],
            "C1_max_humans": ct["C1_max_humans"],
        }

    def l1_anchor_interval_hours(self, tier: str) -> int:
        """Return L1 anchor interval for a commitment tier."""
        ct = self._params["commitment_tiers"]
        key = f"{tier}_L1_anchor_interval_hours"
        if key not in ct:
            raise ValueError(f"Unknown commitment tier: {tier}")
        return ct[key]

    def commitment_committee(self) -> tuple[int, int]:
        """Return (n, t) — committee size and threshold."""
        cc = self._params["commitment_committee"]
        return cc["n"], cc["t"]

    # ------------------------------------------------------------------
    # Machine lifecycle
    # ------------------------------------------------------------------

    def recertification_requirements(self) -> dict[str, Any]:
        """Return machine recertification thresholds."""
        return dict(self._params["machine_recertification"])

    def decommission_rules(self) -> dict[str, Any]:
        """Return machine decommission rules."""
        return dict(self._params["machine_decommission"])

    def key_rotation_days(self) -> int:
        """Return key rotation period in days."""
        return self._params["key_management"]["KEY_ROTATION_DAYS"]

    # ------------------------------------------------------------------
    # Quality assessment
    # ------------------------------------------------------------------

    def quality_worker_weights(self) -> tuple[float, float, float]:
        """Return (w_consensus, w_evidence, w_complexity) for worker quality."""
        qw = self._params["quality_assessment"]["worker_weights"]
        return qw["consensus"], qw["evidence"], qw["complexity"]

    def quality_reviewer_weights(self) -> tuple[float, float]:
        """Return (w_alignment, w_calibration) for reviewer quality."""
        rw = self._params["quality_assessment"]["reviewer_weights"]
        return rw["alignment"], rw["calibration"]

    def evidence_expectations(self) -> dict[str, int]:
        """Return expected evidence count per risk tier."""
        return dict(self._params["quality_assessment"]["evidence_expectations"])

    def complexity_multipliers(self) -> dict[str, float]:
        """Return complexity factor per risk tier."""
        return dict(self._params["quality_assessment"]["complexity_multipliers"])

    def reviewer_alignment_scores(self) -> dict[str, float]:
        """Return alignment score table for reviewer quality assessment."""
        return dict(self._params["quality_assessment"]["reviewer_alignment_scores"])

    def calibration_config(self) -> tuple[int, int]:
        """Return (min_history, window_size) for reviewer calibration."""
        qa = self._params["quality_assessment"]
        return qa["calibration_min_history"], qa["calibration_window_size"]

    # ------------------------------------------------------------------
    # Identity signals
    # ------------------------------------------------------------------

    def identity_signals(self) -> dict[str, Any]:
        """Return identity signal policy."""
        return dict(self._policy["identity_signals"])

    # ------------------------------------------------------------------
    # Skill taxonomy (optional — pre-labour-market mode if absent)
    # ------------------------------------------------------------------

    def has_skill_taxonomy(self) -> bool:
        """Check if a skill taxonomy config file was loaded."""
        return self._taxonomy is not None

    def skill_taxonomy_data(self) -> dict[str, Any]:
        """Return raw skill taxonomy data for SkillTaxonomy construction.

        Returns empty dict if no taxonomy is loaded (pre-labour-market mode).
        """
        if self._taxonomy is None:
            return {}
        return dict(self._taxonomy)

    # ------------------------------------------------------------------
    # Domain-specific trust (optional — requires skill_trust_params.json)
    # ------------------------------------------------------------------

    def has_skill_trust_config(self) -> bool:
        """Check if domain trust config was loaded."""
        return self._skill_trust is not None

    def domain_trust_weights(self) -> tuple[float, float, float, float]:
        """Return (w_Q, w_R, w_V, w_E) for domain trust computation.

        Falls back to global trust weights if no domain-specific config.
        """
        if self._skill_trust is None:
            return self.trust_weights()
        dtw = self._skill_trust["domain_trust_weights"]
        return dtw["w_Q"], dtw["w_R"], dtw["w_V"], dtw["w_E"]

    def inactivity_decay_config(self) -> dict[str, Any]:
        """Return inactivity decay configuration.

        Raises ValueError if no skill trust config is loaded.
        """
        if self._skill_trust is None:
            raise ValueError("No skill trust config loaded")
        return dict(self._skill_trust["inactivity_decay"])

    def half_life_days(self, is_machine: bool) -> float:
        """Return the inactivity decay half-life for an actor kind.

        HUMAN: longer (e.g. 365 days) — realistic human timescales.
        MACHINE: shorter (e.g. 90 days) — silence likely means deprecated.
        Falls back to 365 if no config loaded.
        """
        if self._skill_trust is None:
            return 365.0
        decay = self._skill_trust["inactivity_decay"]
        if is_machine:
            return float(decay["half_life_days_machine"])
        return float(decay["half_life_days_human"])

    def global_score_aggregation(self) -> dict[str, Any]:
        """Return global score aggregation configuration."""
        if self._skill_trust is None:
            return {"method": "weighted_mean", "recency_weight": 0.3, "volume_weight": 0.7}
        return dict(self._skill_trust["global_score_aggregation"])

    # ------------------------------------------------------------------
    # Skill matching (optional — requires skill_trust_params.json)
    # ------------------------------------------------------------------

    def skill_matching_config(self) -> dict[str, Any]:
        """Return skill matching configuration.

        Keys:
        - min_relevance_score: minimum relevance to be considered (default 0.3)
        - proficiency_weight: weight for proficiency in relevance score
        - domain_trust_weight: weight for domain trust in relevance score
        - worker_allocation_weights: {relevance, global_trust, domain_trust}

        Falls back to defaults if no skill trust config loaded.
        """
        if self._skill_trust is None:
            return {
                "min_relevance_score": 0.3,
                "proficiency_weight": 0.60,
                "domain_trust_weight": 0.40,
                "worker_allocation_weights": {
                    "relevance": 0.50,
                    "global_trust": 0.20,
                    "domain_trust": 0.30,
                },
            }
        return dict(self._skill_trust.get("skill_matching", {}))

    # ------------------------------------------------------------------
    # Skill lifecycle (optional — requires skill_lifecycle_params.json)
    # ------------------------------------------------------------------

    def has_skill_lifecycle_config(self) -> bool:
        """Check if skill lifecycle config was loaded."""
        return self._skill_lifecycle is not None

    def skill_lifecycle_params(self) -> dict[str, Any]:
        """Return skill lifecycle parameters.

        Keys: skill_half_life_days_human, skill_half_life_days_machine,
              skill_decay_floor, skill_prune_threshold,
              endorsement: {base_boost, min_endorser_proficiency, ...},
              outcome_updates: {approval_boost, rejection_penalty, ...}
        """
        if self._skill_lifecycle is None:
            return {
                "skill_half_life_days_human": 365.0,
                "skill_half_life_days_machine": 90.0,
                "skill_decay_floor": 0.01,
                "skill_prune_threshold": 0.01,
                "endorsement": {
                    "base_boost": 0.05,
                    "min_endorser_proficiency": 0.5,
                    "max_endorsements_per_skill": 10,
                },
                "outcome_updates": {
                    "approval_boost": 0.05,
                    "rejection_penalty": 0.02,
                    "complexity_multipliers": {
                        "R0": 1.0, "R1": 1.5, "R2": 2.0, "R3": 2.5,
                    },
                },
            }
        return dict(self._skill_lifecycle)

    # ------------------------------------------------------------------
    # Market policy (optional — requires market_policy.json)
    # ------------------------------------------------------------------

    def has_market_config(self) -> bool:
        """Check if market policy config was loaded."""
        return self._market_policy is not None

    def market_allocation_weights(self) -> dict[str, float]:
        """Return market bid allocation weights.

        Keys: relevance, global_trust, domain_trust.
        Falls back to skill_matching config if no market config.
        """
        if self._market_policy is not None:
            return dict(self._market_policy.get("allocation_weights", {}))
        # Fall back to skill matching worker_allocation_weights
        sm = self.skill_matching_config()
        return dict(sm.get("worker_allocation_weights", {
            "relevance": 0.50,
            "global_trust": 0.20,
            "domain_trust": 0.30,
        }))

    def market_listing_defaults(self) -> dict[str, Any]:
        """Return default listing configuration.

        Keys: max_bids_per_listing, bid_window_hours,
              min_skill_requirements, auto_close_on_allocation.
        """
        if self._market_policy is None:
            return {
                "max_bids_per_listing": 50,
                "bid_window_hours": 48,
                "min_skill_requirements": 0,
                "auto_close_on_allocation": True,
            }
        return dict(self._market_policy.get("listing_defaults", {}))

    def market_bid_requirements(self) -> dict[str, Any]:
        """Return bid submission requirements.

        Keys: min_trust_to_bid, min_relevance_to_bid,
              allow_multiple_bids_per_worker.
        """
        if self._market_policy is None:
            return {
                "min_trust_to_bid": 0.10,
                "min_relevance_to_bid": 0.0,
                "allow_multiple_bids_per_worker": False,
            }
        return dict(self._market_policy.get("bid_requirements", {}))

    # ------------------------------------------------------------------
    # Protected leave policy (optional)
    # ------------------------------------------------------------------

    def has_leave_config(self) -> bool:
        """Check if leave policy config was loaded."""
        return self._leave_policy is not None

    def leave_adjudication_config(self) -> dict[str, Any]:
        """Return leave adjudication parameters.

        Keys: min_quorum, min_approve_to_grant, min_adjudicator_trust,
              min_domain_trust, max_adjudicators, adjudicator_diversity.
        """
        if self._leave_policy is None:
            return {
                "min_quorum": 3,
                "min_approve_to_grant": 2,
                "min_adjudicator_trust": 0.40,
                "min_domain_trust": 0.30,
                "max_adjudicators": 5,
                "adjudicator_diversity": {
                    "min_organizations": 2,
                    "min_regions": 2,
                },
            }
        return dict(self._leave_policy.get("adjudication", {}))

    def leave_category_config(self, category: str) -> dict[str, Any]:
        """Return config for a specific leave category.

        Keys: required_adjudicator_domains, max_duration_days, renewable.
        Raises ValueError for unknown categories.
        """
        if self._leave_policy is None:
            from genesis.models.leave import CATEGORY_REQUIRED_DOMAINS
            if category not in CATEGORY_REQUIRED_DOMAINS:
                raise ValueError(f"Unknown leave category: {category}")
            return {
                "required_adjudicator_domains": CATEGORY_REQUIRED_DOMAINS[category],
                "max_duration_days": None,
                "renewable": True,
            }
        cats = self._leave_policy.get("leave_categories", {})
        if category not in cats:
            raise ValueError(f"Unknown leave category: {category}")
        return dict(cats[category])

    def leave_anti_gaming_config(self) -> dict[str, Any]:
        """Return anti-gaming protection parameters.

        Keys: cooldown_days_between_leaves, max_leaves_per_year,
              adjudicator_cannot_self_approve.
        """
        if self._leave_policy is None:
            return {
                "cooldown_days_between_leaves": 30,
                "max_leaves_per_year": 4,
                "adjudicator_cannot_self_approve": True,
            }
        return dict(self._leave_policy.get("anti_gaming", {}))

    def leave_trust_freeze_config(self) -> dict[str, Any]:
        """Return trust freeze parameters.

        Keys: freeze_trust_score, freeze_domain_scores,
              freeze_skill_decay, reset_last_active_on_return.
        """
        if self._leave_policy is None:
            return {
                "freeze_trust_score": True,
                "freeze_domain_scores": True,
                "freeze_skill_decay": True,
                "reset_last_active_on_return": True,
            }
        return dict(self._leave_policy.get("trust_freeze", {}))

    def leave_duration_config(self) -> dict[str, Any]:
        """Return duration limit parameters.

        Keys: default_max_days, category_overrides,
              extension_requires_new_adjudication.
        """
        if self._leave_policy is None:
            return {
                "default_max_days": None,
                "category_overrides": {
                    "pregnancy": 365,
                    "child_care": 365,
                },
                "extension_requires_new_adjudication": True,
            }
        return dict(self._leave_policy.get("duration_limits", {}))

    @classmethod
    def from_config_dir(cls, config_dir: Path) -> PolicyResolver:
        """Load from the canonical config directory."""
        params = _load_json(config_dir / "constitutional_params.json")
        policy = _load_json(config_dir / "runtime_policy.json")

        # Skill taxonomy is optional — system works without it
        taxonomy_path = config_dir / "skill_taxonomy.json"
        taxonomy = None
        if taxonomy_path.exists():
            taxonomy = _load_json(taxonomy_path)

        # Skill trust params are optional — system works without them
        skill_trust_path = config_dir / "skill_trust_params.json"
        skill_trust = None
        if skill_trust_path.exists():
            skill_trust = _load_json(skill_trust_path)

        # Market policy is optional — system works without it
        market_path = config_dir / "market_policy.json"
        market_policy = None
        if market_path.exists():
            market_policy = _load_json(market_path)

        # Skill lifecycle params are optional — system works without them
        lifecycle_path = config_dir / "skill_lifecycle_params.json"
        skill_lifecycle = None
        if lifecycle_path.exists():
            skill_lifecycle = _load_json(lifecycle_path)

        # Leave policy is optional — system works without it
        leave_path = config_dir / "leave_policy.json"
        leave_policy = None
        if leave_path.exists():
            leave_policy = _load_json(leave_path)

        return cls(
            params, policy,
            taxonomy=taxonomy,
            skill_trust=skill_trust,
            market_policy=market_policy,
            skill_lifecycle=skill_lifecycle,
            leave_policy=leave_policy,
        )


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file or raise with clear path."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
