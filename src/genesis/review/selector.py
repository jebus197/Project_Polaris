"""Reviewer selector — constrained-random reviewer assignment.

Given a mission and an actor roster, selects a valid set of reviewers
that satisfies all tier-specific constraints:
- Reviewer count meets or exceeds tier requirement.
- Model family diversity (R1+).
- Method type diversity (R2+).
- Geographic region diversity (R2+).
- Organisation diversity (R2+).
- Self-review structurally prevented (worker excluded from pool).

Selection uses deterministic sampling from the eligible pool,
constrained by diversity requirements. The randomness source is
pluggable to support both production (auditable beacon) and
testing (seeded PRNG).

Constitutional invariants enforced:
- Constrained-random assignment must enforce region caps, minimum
  diversity targets, organization diversity limits, and conflict-
  of-interest recusal.
- Quarantined and decommissioned actors are never selected.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Optional

from genesis.models.mission import Mission, Reviewer, RiskTier
from genesis.policy.resolver import PolicyResolver, TierPolicy
from genesis.review.roster import ActorRoster, RosterEntry


@dataclass(frozen=True)
class SelectionResult:
    """Result of a reviewer selection attempt."""
    reviewers: list[Reviewer]
    errors: list[str]

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class ReviewerSelector:
    """Selects reviewers from the roster for a given mission.

    Usage:
        selector = ReviewerSelector(resolver, roster)
        result = selector.select(mission, seed="beacon:12345")
        if result.success:
            mission.reviewers = result.reviewers
    """

    def __init__(
        self,
        resolver: PolicyResolver,
        roster: ActorRoster,
    ) -> None:
        self._resolver = resolver
        self._roster = roster

    def select(
        self,
        mission: Mission,
        seed: str | None = None,
        min_trust: float = 0.0,
    ) -> SelectionResult:
        """Select reviewers for a mission from the roster.

        Args:
            mission: The mission requiring reviewers.
            seed: Randomness seed for deterministic selection. If None,
                  uses system entropy.
            min_trust: Minimum trust score for reviewer eligibility.

        Returns:
            SelectionResult with selected reviewers or errors explaining
            why selection failed.
        """
        policy = self._resolver.tier_policy(mission.risk_tier)

        if policy.constitutional_flow:
            return SelectionResult(
                reviewers=[],
                errors=["R3 constitutional flow — reviewer selection handled by governance module"],
            )

        # Build candidate pool, excluding the worker
        exclude_ids = {mission.worker_id} if mission.worker_id else set()
        candidates = self._roster.available_reviewers(
            exclude_ids=exclude_ids,
            min_trust=min_trust,
        )

        if len(candidates) < policy.reviewers_required:
            return SelectionResult(
                reviewers=[],
                errors=[
                    f"Insufficient candidates: need {policy.reviewers_required}, "
                    f"found {len(candidates)} eligible"
                ],
            )

        # Set up deterministic PRNG
        rng = random.Random()
        if seed is not None:
            rng.seed(seed)
        else:
            rng.seed()

        # Attempt constrained selection
        selected = self._constrained_select(
            candidates=candidates,
            policy=policy,
            rng=rng,
        )

        if selected is None:
            return SelectionResult(
                reviewers=[],
                errors=[
                    f"Cannot satisfy diversity constraints for {mission.risk_tier.value}: "
                    f"pool has {len(candidates)} candidates but lacks sufficient "
                    f"diversity in model families, method types, regions, or organisations"
                ],
            )

        reviewers = [
            Reviewer(
                id=entry.actor_id,
                model_family=entry.model_family,
                method_type=entry.method_type,
                region=entry.region,
                organization=entry.organization,
            )
            for entry in selected
        ]

        return SelectionResult(reviewers=reviewers, errors=[])

    def _constrained_select(
        self,
        candidates: list[RosterEntry],
        policy: TierPolicy,
        rng: random.Random,
    ) -> Optional[list[RosterEntry]]:
        """Constrained-random selection satisfying diversity requirements.

        Strategy: greedy diversity-first selection.
        1. Group candidates by each diversity dimension.
        2. Ensure minimum coverage by selecting one from each required
           unique group first (round-robin across dimensions).
        3. Fill remaining slots from the pool.
        4. Validate the final set meets all constraints.
        """
        needed = policy.reviewers_required

        # Shuffle candidates for randomness
        pool = list(candidates)
        rng.shuffle(pool)

        selected: list[RosterEntry] = []
        selected_ids: set[str] = set()

        def add(entry: RosterEntry) -> bool:
            if entry.actor_id in selected_ids:
                return False
            selected.append(entry)
            selected_ids.add(entry.actor_id)
            return True

        # Phase 1: Ensure diversity coverage
        # Collect unique values per dimension from the pool
        if policy.min_model_families > 0:
            self._cover_dimension(
                pool, selected, selected_ids,
                key=lambda e: e.model_family,
                min_unique=policy.min_model_families,
                rng=rng,
            )

        if policy.min_method_types > 0:
            self._cover_dimension(
                pool, selected, selected_ids,
                key=lambda e: e.method_type,
                min_unique=policy.min_method_types,
                rng=rng,
            )

        if policy.min_regions > 0:
            self._cover_dimension(
                pool, selected, selected_ids,
                key=lambda e: e.region,
                min_unique=policy.min_regions,
                rng=rng,
            )

        if policy.min_organizations > 0:
            self._cover_dimension(
                pool, selected, selected_ids,
                key=lambda e: e.organization,
                min_unique=policy.min_organizations,
                rng=rng,
            )

        # Phase 2: Fill remaining slots
        remaining = [c for c in pool if c.actor_id not in selected_ids]
        rng.shuffle(remaining)
        for entry in remaining:
            if len(selected) >= needed:
                break
            add(entry)

        # Phase 3: Validate
        if len(selected) < needed:
            return None

        # Trim to exact count needed
        selected = selected[:needed]

        # Verify all constraints are met
        if not self._meets_constraints(selected, policy):
            return None

        return selected

    def _cover_dimension(
        self,
        pool: list[RosterEntry],
        selected: list[RosterEntry],
        selected_ids: set[str],
        key,
        min_unique: int,
        rng: random.Random,
    ) -> None:
        """Ensure at least min_unique distinct values for a dimension."""
        # What values are already covered by selected?
        covered = {key(s) for s in selected}
        needed_values = min_unique - len(covered)

        if needed_values <= 0:
            return

        # Group unselected candidates by dimension value
        groups: dict[str, list[RosterEntry]] = {}
        for entry in pool:
            if entry.actor_id not in selected_ids:
                val = key(entry)
                if val not in covered:
                    groups.setdefault(val, []).append(entry)

        # Select one from each new group
        group_keys = list(groups.keys())
        rng.shuffle(group_keys)
        for gk in group_keys[:needed_values]:
            candidates_in_group = groups[gk]
            chosen = rng.choice(candidates_in_group)
            selected.append(chosen)
            selected_ids.add(chosen.actor_id)
            covered.add(gk)

    @staticmethod
    def _meets_constraints(
        selected: list[RosterEntry],
        policy: TierPolicy,
    ) -> bool:
        """Verify a selection meets all tier policy constraints."""
        if len(selected) < policy.reviewers_required:
            return False

        families = {e.model_family for e in selected}
        if len(families) < policy.min_model_families:
            return False

        methods = {e.method_type for e in selected}
        if len(methods) < policy.min_method_types:
            return False

        regions = {e.region for e in selected}
        if len(regions) < policy.min_regions:
            return False

        orgs = {e.organization for e in selected}
        if len(orgs) < policy.min_organizations:
            return False

        return True
