"""Tests for core vs user module discovery and enablement logic."""

from __future__ import annotations


from dskity.config.settings import DSkitySettings
from dskity.modules.registry import ModuleRegistry


class TestCoreModuleEnablement:
    """Core modules (dskity.modules) are enabled by default."""

    def test_core_modules_enabled_by_default(self):
        """Core modules should be enabled when common.core_modules.<name>.enabled is not set."""
        config = DSkitySettings()
        
        # Discover core modules
        core_registry = ModuleRegistry.from_package("dskity.modules")
        enabled = list(core_registry.enabled_core_modules(config))
        
        # kvstore should be enabled by default
        assert any(m.meta.name == "kvstore" for m in enabled), (
            "kvstore should be enabled by default"
        )

    def test_core_modules_disabled_explicitly(self):
        """Core modules can be disabled via common.registry.enabled: false."""
        config = DSkitySettings()
        config.common.registry.enabled = False
        
        # Discover core modules
        core_registry = ModuleRegistry.from_package("dskity.modules")
        enabled = list(core_registry.enabled_core_modules(config))
        
        # kvstore should be disabled
        assert not any(m.meta.name == "kvstore" for m in enabled), (
            "kvstore should be disabled when explicitly disabled"
        )


class TestUserModuleEnablement:
    """User modules (modules_search_paths) are disabled by default."""

    def test_user_modules_disabled_by_default(self):
        """User modules should be disabled when modules.<name>.enabled is not set."""
        config = DSkitySettings()
        
        # Discover user modules
        user_registry = ModuleRegistry.from_package("examples.modules")
        enabled = list(user_registry.enabled_modules(config))
        
        # No user modules should be enabled by default
        assert len(enabled) == 0, (
            "User modules should be disabled by default"
        )

    def test_user_modules_enabled_explicitly(self):
        """User modules can be enabled via modules.<name>.enabled: true."""
        config = DSkitySettings()
        # Use ensure() to get or create module settings
        config.modules.get("examples")  # Get returns None if not present
        # Need to use direct dict access or ensure()
        config_dict = {
            "modules": {
                "examples": {"enabled": True}
            }
        }
        config2 = DSkitySettings(**config_dict)
        
        # Discover user modules
        user_registry = ModuleRegistry.from_package("examples.modules")
        enabled = list(user_registry.enabled_modules(config2))
        
        # examples should be enabled
        assert any(m.meta.name == "examples" for m in enabled), (
            "examples should be enabled when explicitly enabled"
        )


class TestModuleWithRequiredFields:
    """Modules with required configuration fields should not error when disabled."""

    def test_disabled_module_with_required_fields_no_error(self):
        """
        A module with required fields in additional_settings_model
        should not raise ValidationError when disabled.
        
        This is the regression test for: second_module with tenant_id field
        """
        config = DSkitySettings()
        
        # second_module requires tenant_id but should not error when disabled
        user_registry = ModuleRegistry.from_package("examples.modules")
        enabled = list(user_registry.enabled_modules(config))
        
        # second_module should NOT be in the list of enabled modules
        assert not any(m.meta.name == "second_module" for m in enabled), (
            "second_module should be disabled by default"
        )
        
        # This should not raise any validation error
        # (the test passes if no exception is raised)

    def test_enabled_module_with_required_fields_validates(self):
        """When a module with required fields is enabled, validation should occur."""
        config_dict = {
            "modules": {
                "second_module": {
                    "enabled": True,
                    "additional_settings": {"tenant_id": "test-tenant"}
                }
            }
        }
        config = DSkitySettings(**config_dict)
        
        # second_module should be in the list of enabled modules
        user_registry = ModuleRegistry.from_package("examples.modules")
        enabled = list(user_registry.enabled_modules(config))
        
        assert any(m.meta.name == "second_module" for m in enabled), (
            "second_module should be enabled when explicitly enabled"
        )
