"""Regression tests for image preservation and deployment rollback.

All Docker interactions are mocked; no image, container, or database is changed.
"""
from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ruslex_release", ROOT / "scripts/release.py")
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class PreviousImageTests(unittest.TestCase):
    def test_missing_container_does_not_attempt_image_tag(self):
        with patch.object(release, "compose", return_value="") as compose_mock, patch.object(
            release, "call"
        ) as call_mock:
            self.assertEqual(release.preserve_previous_image(), "")
        compose_mock.assert_called_once_with("images", "-q", "web", capture=True)
        call_mock.assert_not_called()

    def test_stale_image_does_not_stop_deployment(self):
        old_id = "sha256:" + "a" * 64
        error = subprocess.CalledProcessError(1, ("docker", "image", "inspect", old_id))
        with patch.object(release, "compose", return_value=old_id), patch.object(
            release, "call", side_effect=error
        ) as call_mock:
            self.assertEqual(release.preserve_previous_image(), "")
        call_mock.assert_called_once_with("docker", "image", "inspect", old_id, capture=True)

    def test_existing_image_is_saved_under_previous_tag(self):
        old_id = "sha256:" + "b" * 64
        with patch.object(release, "compose", return_value=old_id), patch.object(
            release, "call", return_value=""
        ) as call_mock:
            self.assertEqual(release.preserve_previous_image(), old_id)
        self.assertEqual(
            call_mock.call_args_list,
            [
                call("docker", "image", "inspect", old_id, capture=True),
                call("docker", "image", "tag", old_id, "ruslex:previous"),
            ],
        )

    def test_failed_tag_is_not_treated_as_successful_backup(self):
        old_id = "sha256:" + "c" * 64
        error = subprocess.CalledProcessError(1, ("docker", "image", "tag", old_id))

        def docker_call(*args, **kwargs):
            if args[:3] == ("docker", "image", "tag"):
                raise error
            return ""

        with patch.object(release, "compose", return_value=old_id), patch.object(
            release, "call", side_effect=docker_call
        ):
            self.assertEqual(release.preserve_previous_image(), "")

    def test_stale_image_does_not_prevent_build_or_attempt_fake_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(release, "preflight", return_value=Path(directory)), patch.object(
                release, "preserve_previous_image", return_value=""
            ), patch.object(release, "build") as build_mock, patch.object(
                release, "migrate"
            ), patch.object(release, "healthcheck", side_effect=RuntimeError("unhealthy")), patch.object(
                release, "compose", return_value=""
            ) as compose_mock, patch.object(release, "call", return_value="") as call_mock:
                with self.assertRaisesRegex(RuntimeError, "unhealthy"):
                    release.deploy()
        build_mock.assert_called_once()
        compose_mock.assert_any_call("up", "-d", "--no-deps", "--force-recreate", "web")
        self.assertEqual(compose_mock.call_count, 1)  # No rollback recreation
        for event in call_mock.call_args_list:
            self.assertNotEqual(event.args[:3], ("docker", "image", "tag"))

    def test_failed_health_check_restores_preserved_image(self):
        old_id = "sha256:" + "d" * 64
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(release, "preflight", return_value=Path(directory)), patch.object(
                release, "preserve_previous_image", return_value=old_id
            ), patch.object(release, "build"), patch.object(release, "migrate"), patch.object(
                release, "healthcheck", side_effect=RuntimeError("unhealthy")
            ), patch.object(release, "compose", return_value="") as compose_mock, patch.object(
                release, "call", return_value=""
            ) as call_mock:
                with self.assertRaisesRegex(RuntimeError, "unhealthy"):
                    release.deploy()
        self.assertEqual(compose_mock.call_count, 2)  # Deploy and rollback
        call_mock.assert_any_call("docker", "image", "tag", "ruslex:previous", "ruslex:local")


if __name__ == "__main__":
    unittest.main()
