import json
import os
import tempfile
import unittest
from pathlib import Path

from rpi_vstim.cli import _load_operator_session_metadata
from rpi_vstim.core.config import ConfigError


class OperatorSessionMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "metadata.json"
        self.value = {
            "schema_version": 1,
            "session_id": "session-123",
            "protocol_id": "natural_images",
            "engine_protocol_id": "natural-images",
            "preset_id": "operator_simulation",
            "subject_id": "example_mouse",
            "profile": {"profile_id": "profile-0123456789abcdef0123456789abcdef",
                        "name": "Short simulation", "version": 2},
            "parameters": {"image_count": 4},
            "parameter_overrides": {"image_count": 4},
        }

    def tearDown(self):
        self.temporary.cleanup()

    def _write(self, value=None):
        self.path.write_text(json.dumps(self.value if value is None else value), encoding="utf-8")
        os.chmod(str(self.path), 0o600)

    def test_valid_metadata_is_bound_to_session_subject_and_resolved_image_count(self):
        self._write()
        metadata = _load_operator_session_metadata(
            self.path, session_id="session-123", mouse_id="example_mouse", image_count=4
        )
        self.assertEqual(metadata["profile"]["version"], 2)
        self.assertEqual(metadata["parameters"], {"image_count": 4})
        self.assertIsNone(_load_operator_session_metadata(
            None, session_id="session-123", mouse_id="example_mouse", image_count=4
        ))

    def test_mismatched_identity_parameter_and_profile_are_rejected(self):
        for key, value in (("session_id", "other-session"), ("subject_id", "other-mouse"),
                           ("engine_protocol_id", "wrong")):
            altered = dict(self.value, **{key: value})
            with self.subTest(key=key):
                self._write(altered)
                with self.assertRaises(ConfigError):
                    _load_operator_session_metadata(
                        self.path, session_id="session-123", mouse_id="example_mouse", image_count=4
                    )
        self._write(dict(self.value, parameters={"image_count": 5}))
        with self.assertRaisesRegex(ConfigError, "parameters"):
            _load_operator_session_metadata(
                self.path, session_id="session-123", mouse_id="example_mouse", image_count=4
            )
        self._write(dict(self.value, parameter_overrides={"image_count": 2801}))
        with self.assertRaisesRegex(ConfigError, "parameters"):
            _load_operator_session_metadata(
                self.path, session_id="session-123", mouse_id="example_mouse", image_count=4
            )
        self._write(dict(self.value, profile={"profile_id": "../../bad", "name": "Bad", "version": 1}))
        with self.assertRaisesRegex(ConfigError, "profile identity"):
            _load_operator_session_metadata(
                self.path, session_id="session-123", mouse_id="example_mouse", image_count=4
            )

    def test_schema_permissions_and_arbitrary_fields_are_rejected(self):
        self._write(dict(self.value, schema_version=2))
        with self.assertRaisesRegex(ConfigError, "schema version"):
            _load_operator_session_metadata(
                self.path, session_id="session-123", mouse_id="example_mouse", image_count=4
            )
        self._write(dict(self.value, config_path="/etc/passwd"))
        with self.assertRaisesRegex(ConfigError, "invalid schema"):
            _load_operator_session_metadata(
                self.path, session_id="session-123", mouse_id="example_mouse", image_count=4
            )
        self._write()
        os.chmod(str(self.path), 0o644)
        with self.assertRaisesRegex(ConfigError, "permissions"):
            _load_operator_session_metadata(
                self.path, session_id="session-123", mouse_id="example_mouse", image_count=4
            )


if __name__ == "__main__":
    unittest.main()
