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
    AudioPlayerBackend, VideoPlayerBackend, PlaybackEvent)
from ovos_plugin_manager.templates.audio import AudioBackend
from ovos_utils.fakebus import FakeBus

from ovos_media_plugin_vlc import (
    VlcBaseService, VLCOCPAudioService, VLCOCPVideoService)
from ovos_media_plugin_vlc.audio import VLCAudioService, load_service

URI = "http://example.com/song.mp3"


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

    def test_capabilities(self):
        svc = VLCOCPAudioService({}, bus=MagicMock())
        self.assertTrue(svc.can_seek)
        self.assertTrue(svc.can_pause)


class TestV2EventReporting(unittest.TestCase):
    """MediaBackend v2 contract: physical events go through report(), never
    the bus - the daemon owns every ``ovos.common_play.*`` transition."""

    def _service(self):
        svc = VLCOCPAudioService({}, bus=MagicMock())
        events = []
        svc.bind_event_reporter(lambda event, **data: events.append((event, data)))
        return svc, events

    def test_load_track_returns_bool_and_reports_nothing(self):
        svc, events = self._service()
        self.assertTrue(svc.load_track(URI))
        self.assertEqual(events, [], "load_track must not report - the "
                                      "daemon owns LOADED_MEDIA")

    def test_track_start_reports_with_uri(self):
        svc, events = self._service()
        svc.load_track(URI)
        svc.track_start(None, None)
        self.assertIn((PlaybackEvent.TRACK_START, {"uri": URI}), events)

    def test_vlc_error_reports_error_and_uri(self):
        svc, events = self._service()
        svc.load_track(URI)
        svc.handle_vlc_error(None, None)
        self.assertEqual(len(events), 1)
        event, data = events[0]
        self.assertEqual(event, PlaybackEvent.ERROR)
        self.assertEqual(data.get("uri"), URI)
        self.assertIsInstance(data.get("error"), str)
        self.assertTrue(data["error"])

    def test_explicit_stop_then_vlc_stopped_event_reports_stopped(self):
        """stop() records the explicit-stop request; the *real* vlc
        end-of-track signal (queue_ended, wired to both
        MediaPlayerEndReached and MediaPlayerStopped) is what actually
        reports it - matching how libvlc fires MediaPlayerStopped
        asynchronously rather than synchronously from stop() itself."""
        svc, events = self._service()
        svc.load_track(URI)
        svc.stop()
        self.assertEqual(events, [], "stop() itself must not report - only "
                                      "the vlc end-of-track callback does")
        svc.queue_ended(None, None)
        self.assertIn((PlaybackEvent.STOPPED, {"uri": URI}), events)

    def test_natural_end_after_stop_flag_is_not_sticky(self):
        """the _stop_requested flag is consumed by report_track_end, so a
        stop()'d track followed by a *second*, never-stopped track that
        ends naturally must report END_OF_MEDIA, not a stale STOPPED."""
        svc, events = self._service()
        svc.load_track(URI)
        svc.stop()
        svc.queue_ended(None, None)  # consumes the flag -> STOPPED
        events.clear()

        svc.load_track(URI)
        svc.queue_ended(None, None)  # natural end, no stop() this time
        self.assertIn((PlaybackEvent.END_OF_MEDIA, {"uri": URI}), events)
        self.assertNotIn((PlaybackEvent.STOPPED, {"uri": URI}), events)

    def test_full_verb_cycle_emits_no_common_play_bus_messages(self):
        bus = FakeBus()
        seen = []
        bus.on("ovos.common_play.playback_time",
               lambda msg: seen.append(msg.msg_type))

        def _catch_all(msg):
            if msg.msg_type.startswith("ovos.common_play."):
                seen.append(msg.msg_type)

        bus.on("message", _catch_all)

        svc = VLCOCPAudioService({}, bus=bus)
        svc.bind_event_reporter(lambda event, **data: None)
        svc.load_track(URI)
        svc.play()
        svc.track_start(None, None)
        svc.pause()
        svc.resume()
        svc.get_track_position()
        svc.set_track_position(1000)
        svc.stop()
        svc.queue_ended(None, None)
        svc.handle_vlc_error(None, None)

        self.assertEqual(seen, [], f"backend emitted state on the bus: {seen}")


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
