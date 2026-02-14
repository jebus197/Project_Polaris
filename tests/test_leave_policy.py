"""Unit tests for leave policy configuration and resolver methods.

Tests PolicyResolver leave methods, config loading, and defaults.
"""

import pytest
from pathlib import Path

from genesis.policy.resolver import PolicyResolver


# ===================================================================
# PolicyResolver leave methods — with config
# ===================================================================

class TestLeavePolicyWithConfig:
    @classmethod
    def setup_class(cls) -> None:
        """Load from actual config directory."""
        config_dir = Path(__file__).parent.parent / "config"
        cls.resolver = PolicyResolver.from_config_dir(config_dir)

    def test_has_leave_config(self) -> None:
        assert self.resolver.has_leave_config() is True

    def test_adjudication_config_min_quorum(self) -> None:
        config = self.resolver.leave_adjudication_config()
        assert config["min_quorum"] == 3

    def test_adjudication_config_min_approve(self) -> None:
        config = self.resolver.leave_adjudication_config()
        assert config["min_approve_to_grant"] == 2

    def test_adjudication_config_min_trust(self) -> None:
        config = self.resolver.leave_adjudication_config()
        assert config["min_adjudicator_trust"] == 0.40

    def test_adjudication_config_min_domain_trust(self) -> None:
        config = self.resolver.leave_adjudication_config()
        assert config["min_domain_trust"] == 0.30

    def test_illness_category_domains(self) -> None:
        config = self.resolver.leave_category_config("illness")
        assert "healthcare" in config["required_adjudicator_domains"]

    def test_pregnancy_category_domains(self) -> None:
        config = self.resolver.leave_category_config("pregnancy")
        assert "healthcare" in config["required_adjudicator_domains"]

    def test_child_care_category_domains(self) -> None:
        config = self.resolver.leave_category_config("child_care")
        assert "social_services" in config["required_adjudicator_domains"]

    def test_bereavement_category_domains(self) -> None:
        config = self.resolver.leave_category_config("bereavement")
        domains = config["required_adjudicator_domains"]
        assert "social_services" in domains
        assert "mental_health" in domains

    def test_anti_gaming_cooldown(self) -> None:
        config = self.resolver.leave_anti_gaming_config()
        assert config["cooldown_days_between_leaves"] == 30

    def test_anti_gaming_max_per_year(self) -> None:
        config = self.resolver.leave_anti_gaming_config()
        assert config["max_leaves_per_year"] == 4

    def test_trust_freeze_config(self) -> None:
        config = self.resolver.leave_trust_freeze_config()
        assert config["freeze_trust_score"] is True
        assert config["freeze_domain_scores"] is True
        assert config["freeze_skill_decay"] is True
        assert config["reset_last_active_on_return"] is True

    def test_duration_limits_pregnancy(self) -> None:
        config = self.resolver.leave_duration_config()
        overrides = config.get("category_overrides", {})
        assert overrides.get("pregnancy") == 365

    def test_duration_limits_child_care(self) -> None:
        config = self.resolver.leave_duration_config()
        overrides = config.get("category_overrides", {})
        assert overrides.get("child_care") == 365

    def test_duration_limits_default_unlimited(self) -> None:
        config = self.resolver.leave_duration_config()
        assert config.get("default_max_days") is None


# ===================================================================
# PolicyResolver leave methods — without config (defaults)
# ===================================================================

class TestLeavePolicyWithoutConfig:
    """When no leave_policy.json is loaded, resolver returns sane defaults."""

    def test_has_leave_config_false(self) -> None:
        resolver = PolicyResolver(params={"version": "1.0"}, policy={"version": "1.0"})
        assert resolver.has_leave_config() is False

    def test_adjudication_defaults_sane(self) -> None:
        """Returns sane defaults even without config file."""
        resolver = PolicyResolver(params={"version": "1.0"}, policy={"version": "1.0"})
        config = resolver.leave_adjudication_config()
        assert config["min_quorum"] == 3
        assert config["min_approve_to_grant"] == 2
        assert config["min_adjudicator_trust"] == 0.40
        assert config["min_domain_trust"] == 0.30

    def test_category_config_defaults_sane(self) -> None:
        resolver = PolicyResolver(params={"version": "1.0"}, policy={"version": "1.0"})
        config = resolver.leave_category_config("illness")
        assert "required_adjudicator_domains" in config
        assert "healthcare" in config["required_adjudicator_domains"]

    def test_anti_gaming_defaults_sane(self) -> None:
        resolver = PolicyResolver(params={"version": "1.0"}, policy={"version": "1.0"})
        config = resolver.leave_anti_gaming_config()
        assert config["cooldown_days_between_leaves"] == 30
        assert config["max_leaves_per_year"] == 4

    def test_trust_freeze_defaults_sane(self) -> None:
        resolver = PolicyResolver(params={"version": "1.0"}, policy={"version": "1.0"})
        config = resolver.leave_trust_freeze_config()
        assert config["freeze_trust_score"] is True
        assert config["reset_last_active_on_return"] is True

    def test_duration_defaults_sane(self) -> None:
        resolver = PolicyResolver(params={"version": "1.0"}, policy={"version": "1.0"})
        config = resolver.leave_duration_config()
        assert config["default_max_days"] is None
        assert config["category_overrides"]["pregnancy"] == 365
        assert config["category_overrides"]["child_care"] == 365
