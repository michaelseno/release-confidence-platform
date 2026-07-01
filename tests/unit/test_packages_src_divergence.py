"""OPS-D01, OPS-D02: Behavioral equivalence between packages/ and src/ implementations."""


class TestSanitizationEquivalence:
    """Verify packages/ and src/ sanitization produce identical results."""

    def test_sanitize_string_identical(self):
        """OPS-D01: sanitize(str) is identical across packages/ and src/."""
        from packages.sanitization.sanitizer import sanitize as pkg_sanitize
        from release_confidence_platform.sanitization.sanitizer import sanitize as src_sanitize
        assert pkg_sanitize("test-value") == src_sanitize("test-value")

    def test_sanitize_dict_identical(self):
        """OPS-D01: sanitize(dict) is identical across packages/ and src/."""
        from packages.sanitization.sanitizer import sanitize as pkg_sanitize
        from release_confidence_platform.sanitization.sanitizer import sanitize as src_sanitize
        fixture = {"key": "value", "nested": {"a": 1, "b": [1, 2, 3]}}
        assert pkg_sanitize(fixture) == src_sanitize(fixture)

    def test_sanitize_none_identical(self):
        """OPS-D01: sanitize(None) is identical across packages/ and src/."""
        from packages.sanitization.sanitizer import sanitize as pkg_sanitize
        from release_confidence_platform.sanitization.sanitizer import sanitize as src_sanitize
        assert pkg_sanitize(None) == src_sanitize(None)


class TestCoreLoggingEquivalence:
    """Verify packages/ and src/ StructuredLogger have equivalent public interfaces."""

    def test_structured_logger_same_interface(self):
        """OPS-D01: packages/ StructuredLogger methods are a subset of src/ methods."""
        from packages.core.logging import StructuredLogger as PkgLogger
        from release_confidence_platform.core.logging import StructuredLogger as SrcLogger
        pkg_methods = {m for m in dir(PkgLogger) if not m.startswith('_')}
        src_methods = {m for m in dir(SrcLogger) if not m.startswith('_')}
        missing = pkg_methods - src_methods
        assert not missing, f"Methods in packages/ but not in src/: {missing}"


class TestAuditMetadataRepositoryEquivalence:
    """Verify packages/ and src/ AuditMetadataRepository have equivalent interfaces."""

    def test_both_have_list_run_records(self):
        """OPS-D01: list_run_records exists in both packages/ and src/."""
        from packages.storage.audit_metadata_client import AuditMetadataRepository as PkgRepo
        from release_confidence_platform.storage.audit_metadata_client import (
            AuditMetadataRepository as SrcRepo,
        )
        assert hasattr(PkgRepo, 'list_run_records'), "packages/ missing list_run_records"
        assert hasattr(SrcRepo, 'list_run_records'), "src/ missing list_run_records"

    def test_both_importable(self):
        """OPS-D02: Post-sync, both packages/ and src/ modules import without error."""
        from packages.storage import audit_metadata_client as pkg_mod
        from release_confidence_platform.storage import audit_metadata_client as src_mod
        assert pkg_mod is not None
        assert src_mod is not None

    def test_repository_init_signatures_match(self):
        """OPS-D01: AuditMetadataRepository constructors accept same parameters."""
        import inspect

        from packages.storage.audit_metadata_client import AuditMetadataRepository as PkgRepo
        from release_confidence_platform.storage.audit_metadata_client import (
            AuditMetadataRepository as SrcRepo,
        )
        pkg_params = set(inspect.signature(PkgRepo.__init__).parameters.keys())
        src_params = set(inspect.signature(SrcRepo.__init__).parameters.keys())
        # packages/ params must be a subset of or equal to src/ params
        assert pkg_params <= src_params or pkg_params == src_params, (
            f"packages/ init params {pkg_params} differ from src/ init params {src_params}"
        )
