"""End, error and stop reports against a fake libvlc with the 3.0 event order.

See ``fake_libvlc`` for the libvlc 3.0 source that the fake follows.
"""
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.modules.setdefault("vlc", MagicMock())

from ovos_bus_client.message import Message
from ovos_plugin_manager.templates.media import PlaybackEvent
from ovos_utils.fakebus import FakeBus

import ovos_media_plugin_vlc
from ovos_media_plugin_vlc import VLCOCPAudioService

from fake_libvlc import make_vlc

A = "file:///music/a.mp3"
B = "file:///music/b.mp3"


class _FakeVlcTest(unittest.TestCase):
    def setUp(self):
        self.vlc, self.players = make_vlc()
        patcher = patch.object(ovos_media_plugin_vlc, "vlc", self.vlc)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestBackendReports(_FakeVlcTest):
    def setUp(self):
        super().setUp()
        self.svc = VLCOCPAudioService({}, bus=FakeBus())
        self.player = self.players[-1]
        self.events = []
        self.svc.bind_event_reporter(
            lambda event, **data: self.events.append((event, data)))

    def play(self, uri):
        self.svc.load_track(uri)
        self.svc.play()
        self.events.clear()

    def test_natural_end_reports_one_end_of_media(self):
        self.play(A)
        self.player.natural_end()
        self.assertEqual(self.events,
                         [(PlaybackEvent.END_OF_MEDIA, {"uri": A})])

    def test_error_reports_one_error_and_no_end(self):
        self.play(A)
        self.player.error()
        self.assertEqual([e for e, _ in self.events], [PlaybackEvent.ERROR])
        self.assertEqual(self.events[0][1]["uri"], A)

    def test_stop_reports_one_stopped(self):
        self.play(A)
        self.svc.stop()
        self.assertEqual(self.events, [(PlaybackEvent.STOPPED, {"uri": A})])

    def test_switch_reports_no_end_for_the_replaced_media(self):
        self.play(A)
        self.svc.load_track(B)
        self.svc.play()
        self.assertEqual(self.events, [(PlaybackEvent.TRACK_START, {"uri": B})])
        self.player.natural_end()
        self.assertEqual(self.events[1:],
                         [(PlaybackEvent.END_OF_MEDIA, {"uri": B})])


class TestQueueThroughOvosMedia(_FakeVlcTest):
    """The real ovos-media player and dispatcher drive the backend."""

    def setUp(self):
        super().setUp()
        from ovos_utils.ocp import MediaEntry, PlaybackType
        from ovos_media.bus.api import OCPBusApi
        from ovos_media.player import OCPMediaPlayer
        from ovos_media.player.dispatcher import Dispatcher

        self.bus = FakeBus()
        self.ocp = OCPMediaPlayer(self.bus, config={})
        self.addCleanup(self.ocp.shutdown)
        self.ocp.now_playing.extract_stream = lambda **kwargs: None
        self.ocp.dispatcher.shutdown()
        self.ocp.dispatcher = Dispatcher(immediate=False)
        self.ocp.dispatcher.post_hook = self.ocp.publish_snapshot
        self.ocp.bus_api.shutdown()
        self.ocp.bus_api = OCPBusApi(self.bus, player=self.ocp)

        self.backend = VLCOCPAudioService({}, bus=self.bus)
        self.backend.name = "vlc"
        self.player = self.players[-1]
        service = self.ocp.audio_service
        service.services = [self.backend]
        service.current = None
        self.backend.bind_event_reporter(
            lambda event, **data: service._handle_backend_event(
                self.backend, event, **data))

        self.entries = [MediaEntry(uri=uri, title=uri,
                                   playback=PlaybackType.AUDIO)
                        for uri in (A, B, "file:///music/c.mp3")]
        self.ocp.playlist.clear()
        for entry in self.entries:
            self.ocp.playlist.add_entry(entry)
        self.drain(lambda: self.ocp.set_now_playing(self.ocp.playlist[0]))
        self.drain(self.ocp.play)
        self.assertEqual(self.player.media.uri, A)

    def drain(self, fn=None):
        self.ocp.dispatcher.call(fn or (lambda: None), timeout=10)
        self.assertTrue(self.ocp.dispatcher.settle(timeout=10))

    def settle(self):
        self.drain()
        time.sleep(0.3)
        self.drain()

    def test_natural_end_of_a_plays_b(self):
        self.player.natural_end()
        self.settle()
        self.assertEqual(self.ocp.now_playing.uri, B)
        self.assertEqual(self.player.media.uri, B)

    def test_stop_does_not_advance(self):
        self.ocp.audio_service.play_start_time = 0  # past the 1 s stop guard
        self.bus.emit(Message("ovos.common_play.stop"))
        self.settle()
        self.assertNotEqual(self.ocp.now_playing.uri, B)
        self.assertEqual(self.player.media.uri, A)
        self.assertFalse(self.player.is_playing())


class TestLegacyOvosAudio(_FakeVlcTest):
    """ovos-audio loads the plugin by its mycroft.plugin.audioservice
    entry point and plays through the legacy AudioBackend calls."""

    def setUp(self):
        super().setUp()
        import ovos_audio.audio as audio
        config = {"Audio": {"default-backend": "vlc", "backends": {
            "vlc": {"type": "ovos_vlc", "active": True}}}}
        patcher = patch.object(audio, "Configuration", return_value=config)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bus = FakeBus()
        self.queue_end = []
        self.bus.on("mycroft.audio.queue_end", self.queue_end.append)
        self.service = audio.AudioService(self.bus, disable_ocp=True)
        self.assertEqual([s.name for s in self.service.service], ["vlc"])

    def test_play_then_natural_end_reaches_ovos_audio(self):
        self.service.play([A], None)
        player = self.players[-1]
        self.assertEqual(player.media.uri, A)
        self.assertTrue(player.is_playing())
        player.natural_end()
        self.assertEqual(len(self.queue_end), 1)

    def test_error_reports_invalid_media(self):
        states = []
        self.bus.on("ovos.common_play.media.state",
                    lambda m: states.append(m.data["state"]))
        self.service.play([A], None)
        states.clear()
        self.players[-1].error()
        from ovos_utils.ocp import MediaState
        self.assertEqual(states, [MediaState.INVALID_MEDIA])
        self.assertEqual(self.queue_end, [])


if __name__ == "__main__":
    unittest.main()
