"""Regression test: get_track_length/get_track_position must not pass
libVLC's own -1/0 through when nothing is loaded or when a live stream
has no finite duration.

MediaBackend's contract: ``None`` means nothing is loaded; a paused or
playing track answers its real elapsed position and a length of -1 means
"loaded, no finite duration" (a live stream); any other track answers both
as real values.

``python-vlc`` (and libvlc) are not available in CI, so ``vlc`` is mocked in
``sys.modules`` before importing the plugin, matching test_backends.py.
"""
import sys
import unittest
from unittest.mock import MagicMock

_vlc = MagicMock()
sys.modules.setdefault("vlc", _vlc)
import vlc  # the module actually installed above, shared across test files

from ovos_media_plugin_vlc import VLCOCPAudioService


class TestTrackLengthAndPosition(unittest.TestCase):

    def _service(self, state, length, position):
        svc = VLCOCPAudioService({}, bus=MagicMock())
        svc.player = MagicMock()
        svc.player.get_state.return_value = state
        # libVLC's own is_playing() is true only in the Playing state, and
        # false while paused, stopped or before anything is loaded.
        svc.player.is_playing.return_value = state == vlc.State.Playing
        svc.player.get_length.return_value = length
        svc.player.get_time.return_value = position
        return svc

    def test_stopped_reports_none_for_both(self):
        # libVLC answers -1 from both get_length() and get_time() when
        # nothing is loaded.
        svc = self._service(vlc.State.Stopped, length=-1, position=-1)
        self.assertIsNone(svc.get_track_length())
        self.assertIsNone(svc.get_track_position())

    def test_nothing_special_reports_none_for_both(self):
        # the state before anything is ever loaded.
        svc = self._service(vlc.State.NothingSpecial, length=-1, position=-1)
        self.assertIsNone(svc.get_track_length())
        self.assertIsNone(svc.get_track_position())

    def test_paused_reports_its_real_length_and_position(self):
        # is_playing() is false while paused, but the track is still
        # loaded and has a real position and length.
        svc = self._service(vlc.State.Paused, length=180000, position=42000)
        self.assertEqual(svc.get_track_length(), 180000)
        self.assertEqual(svc.get_track_position(), 42000)

    def test_live_stream_reports_its_position_and_unknown_length(self):
        # libVLC answers 0, not -1, for a live stream's length; the
        # contract's unknown-duration answer is -1.
        svc = self._service(vlc.State.Playing, length=0, position=7000)
        self.assertEqual(svc.get_track_position(), 7000)
        self.assertEqual(svc.get_track_length(), -1)

    def test_a_track_reports_its_real_length_and_position(self):
        svc = self._service(vlc.State.Playing, length=200000, position=12500)
        self.assertEqual(svc.get_track_length(), 200000)
        self.assertEqual(svc.get_track_position(), 12500)


if __name__ == "__main__":
    unittest.main()
