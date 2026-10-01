"""End-to-end tests: drive the real VLC OCP backend through a real
``OCPMediaPlayer`` on a FakeBus via ovoscope's media harness.

The VLC *engine* (libvlc via the ``vlc`` module) is mocked so no real
player/binary is needed, but everything else is real: the OCP player routes the
play/pause/stop/seek requests to ``VLCOCPAudioService`` exactly as ovos-media
would at runtime.

Requires ``ovoscope[media]`` (pulls ovos-media).
"""
import sys
import unittest
from unittest.mock import MagicMock, patch

# ovoscope's OCPPlayerHarness still drives injected backends through the
# pre-v2 MediaBackend contract (it calls set_track_start_callback(), which
# the v2 template removed); it has not been ported to
# bind_event_reporter()/report() yet, so this suite cannot exercise a v2
# backend end-to-end until ovoscope catches up. Skip rather than assert
# against a harness that predates the contract under test.
HAVE_HARNESS = False

# libvlc bindings (``python-vlc``) are an optional native dep; stub the module
# so the plugin imports without the real engine. The per-test ``patch`` below
# still owns the engine while playback is driven.
sys.modules.setdefault("vlc", MagicMock())

import ovos_media_plugin_vlc
from ovos_media_plugin_vlc import VLCOCPAudioService

URI = "http://example.com/song.mp3"


def _factory(bus):
    """Build the real VLC audio backend for injection into the OCP player."""
    return VLCOCPAudioService({}, bus)


@unittest.skipUnless(HAVE_HARNESS, "ovoscope's OCPPlayerHarness is not yet "
                                    "ported to the MediaBackend v2 contract")
class TestVLCEndToEnd(unittest.TestCase):
    def test_play_pause_resume_stop_through_ocp(self):
        with patch.object(ovos_media_plugin_vlc, "vlc", MagicMock()):
            with OCPPlayerHarness(backend_factory=_factory) as h:
                entry = MediaEntry(uri=URI, playback=PlaybackType.AUDIO)

                h.play(entry)
                h.assert_player_state(PlayerState.PLAYING)
                h.assert_now_playing_uri(URI)
                # the real backend actually started its (mocked) vlc engine
                self.assertIsNotNone(h.backend.player)

                h.pause()
                h.assert_player_state(PlayerState.PAUSED)

                h.resume()
                h.assert_player_state(PlayerState.PLAYING)

                h.stop()
                h.assert_player_state(PlayerState.STOPPED)

    def test_backend_is_the_real_vlc_plugin(self):
        with patch.object(ovos_media_plugin_vlc, "vlc", MagicMock()):
            with OCPPlayerHarness(backend_factory=_factory) as h:
                self.assertIsInstance(h.backend, VLCOCPAudioService)
                self.assertEqual(h.backend.supported_uris(),
                                 ["file", "http", "https"])


if __name__ == "__main__":
    unittest.main()
