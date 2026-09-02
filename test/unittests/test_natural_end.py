"""Regression test: a track that ends naturally (vlc fires
``MediaPlayerEndReached`` on its own, no stop() ever called) must report
MediaState.END_OF_MEDIA / PlayerState.STOPPED on the bus, exactly like an
explicit stop does.

``python-vlc`` (and libvlc) are not available in CI, so ``vlc`` is mocked in
``sys.modules`` before importing the plugin, matching test_backends.py.
"""
import sys
import unittest
from unittest.mock import MagicMock

_vlc = MagicMock()
sys.modules.setdefault("vlc", _vlc)

from ovos_utils.fakebus import FakeBus
from ovos_utils.ocp import MediaState, PlayerState

from ovos_media_plugin_vlc import VLCOCPAudioService


class TestNaturalEndOfMedia(unittest.TestCase):

    def _service(self):
        bus = FakeBus()
        states = []
        player_states = []
        bus.on("ovos.common_play.media.state",
               lambda msg: states.append(msg.data.get("state")))
        bus.on("ovos.common_play.player.state",
               lambda msg: player_states.append(msg.data.get("state")))
        service = VLCOCPAudioService({}, bus=bus)
        service._now_playing = "file:///tmp/track.wav"
        return service, states, player_states

    def test_natural_track_end_emits_end_of_media(self):
        service, states, player_states = self._service()

        # simulate vlc's MediaPlayerEndReached event firing on its own,
        # with no stop() ever called by us
        service.queue_ended(None, None)

        self.assertIn(MediaState.END_OF_MEDIA, states,
                       f"natural end-of-media never emitted END_OF_MEDIA; saw: {states}")
        self.assertIn(PlayerState.STOPPED, player_states,
                       f"natural end-of-media never emitted PlayerState.STOPPED; saw: {player_states}")


if __name__ == "__main__":
    unittest.main()
