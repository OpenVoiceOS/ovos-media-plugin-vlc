"""Unit tests for the VLC backends.

``python-vlc`` (and libvlc) are not available in CI, so ``vlc`` is mocked in
``sys.modules`` before importing the plugin. The tests assert wiring/contract,
not real playback: both the new ovos-media backends and the legacy ovos-audio
adapter build, expose the right base classes, and the supported URIs + entry
points are declared correctly.
"""
import sys
import unittest
from unittest.mock import MagicMock


# --- mock libvlc so the plugin imports without a real VLC install -----------
_vlc = MagicMock()
# vlc.EventType.* must be attribute-accessible; MagicMock handles that.
sys.modules.setdefault("vlc", _vlc)

from ovos_plugin_manager.templates.media import (
    AudioPlayerBackend, VideoPlayerBackend)
from ovos_plugin_manager.templates.audio import AudioBackend

from ovos_media_plugin_vlc import (
    VlcBaseService, VLCOCPAudioService, VLCOCPVideoService)
from ovos_media_plugin_vlc.audio import VLCAudioService, load_service


class TestNewBackends(unittest.TestCase):
    def test_audio_backend_is_audioplayerbackend(self):
        svc = VLCOCPAudioService({}, bus=MagicMock())
        self.assertIsInstance(svc, AudioPlayerBackend)
        self.assertIsInstance(svc, VlcBaseService)

    def test_video_backend_is_videoplayerbackend(self):
        svc = VLCOCPVideoService({}, bus=MagicMock())
        self.assertIsInstance(svc, VideoPlayerBackend)

    def test_supported_uris(self):
        svc = VLCOCPAudioService({}, bus=MagicMock())
        self.assertEqual(svc.supported_uris(), ['file', 'http', 'https'])


class TestLegacyAdapter(unittest.TestCase):
    def test_legacy_is_audiobackend(self):
        svc = VLCAudioService({}, bus=MagicMock(), name='vlc')
        self.assertIsInstance(svc, AudioBackend)
        # reuses the shared VLC engine/methods
        self.assertIsInstance(svc, VlcBaseService)
        self.assertTrue(hasattr(svc, "play"))
        self.assertTrue(hasattr(svc, "lower_volume"))

    def test_supported_uris(self):
        svc = VLCAudioService({}, bus=MagicMock(), name='vlc')
        self.assertEqual(svc.supported_uris(), ['file', 'http', 'https'])

    def test_load_service_builds_active_vlc_backends(self):
        cfg = {"backends": {
            "myvlc": {"type": "vlc", "active": True},
            "off": {"type": "vlc", "active": False},
            "other": {"type": "mpv", "active": True},
        }}
        services = load_service(cfg, bus=MagicMock())
        self.assertEqual(len(services), 1)
        self.assertIsInstance(services[0], VLCAudioService)

    def test_load_service_empty(self):
        self.assertEqual(load_service({"backends": {}}, bus=MagicMock()), [])


class TestEntryPoints(unittest.TestCase):
    """Both the new and legacy entry-point groups must be declared."""

    def test_pyproject_declares_new_and_legacy_groups(self):
        import os
        here = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        with open(os.path.join(here, "pyproject.toml")) as f:
            src = f.read()
        self.assertIn("opm.media.audio", src)
        self.assertIn("opm.media.video", src)
        self.assertIn("mycroft.plugin.audioservice", src)
        self.assertIn("ovos_media_plugin_vlc.audio", src)


if __name__ == "__main__":
    unittest.main()
