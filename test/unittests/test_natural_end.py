"""Regression test: a track that ends naturally (vlc fires
``MediaPlayerEndReached`` on its own, no stop() ever called) must report
``PlaybackEvent.END_OF_MEDIA`` to the daemon, exactly like an explicit stop's
natural counterpart, and must carry the loaded ``uri`` for staleness checks.

``python-vlc`` (and libvlc) are not available in CI, so ``vlc`` is mocked in
``sys.modules`` before importing the plugin, matching test_backends.py.
"""
import sys
import unittest
from unittest.mock import MagicMock

_vlc = MagicMock()
sys.modules.setdefault("vlc", _vlc)

from ovos_plugin_manager.templates.media import PlaybackEvent

from ovos_media_plugin_vlc import VLCOCPAudioService

URI = "file:///tmp/track.wav"


class TestNaturalEndOfMedia(unittest.TestCase):

    def _service(self):
        service = VLCOCPAudioService({}, bus=MagicMock())
        events = []
        service.bind_event_reporter(lambda event, **data: events.append((event, data)))
        service.load_track(URI)
        return service, events

    def test_natural_track_end_reports_end_of_media_with_uri(self):
        service, events = self._service()

        # simulate vlc's MediaPlayerEndReached event firing on its own,
        # with no stop() ever called by us
        service.queue_ended(None, None)

        self.assertIn((PlaybackEvent.END_OF_MEDIA, {"uri": URI}), events,
                       f"natural end-of-media never reported END_OF_MEDIA with uri; saw: {events}")

    def test_backends_implement_underscore_stop_not_stop(self):
        """v2's MediaBackend.stop() is concrete (it flips _stop_requested
        then delegates); plugins implement _stop, not stop."""
        service, _ = self._service()
        self.assertTrue(hasattr(service, "_stop"))
        # stop() is still callable (inherited, concrete) and drives _stop()
        self.assertTrue(service.stop())


if __name__ == "__main__":
    unittest.main()
