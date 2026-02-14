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

    def __init__(self, params: dict[str, Any], policy: dict[str, Any]) -> None:
        self._params = params
        self._policy = policy
        self._validate_versions()

    @classmethod
    def from_config_dir(cls, config_dir: Path) -> PolicyResolver:
        """Load from the canonical config directory."""
        params = _load_json(config_dir / "constitutional_params.json")
        policy = _load_json(config_dir / "runtime_policy.json")
        return cls(params, policy)

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


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file or raise with clear path."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
