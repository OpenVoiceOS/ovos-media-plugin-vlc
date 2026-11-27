"""A switch must not mislabel the end of the replaced media.

libvlc fires its end per media. When B replaces A, the end of A arrives
after B is the current media, so the uri must come from the media that
ended. A small fake libvlc dispatches both the player-level end events and
the per-media state change, as libvlc does.
"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.modules.setdefault("vlc", MagicMock())

from ovos_plugin_manager.templates.media import PlaybackEvent

import ovos_media_plugin_vlc
from ovos_media_plugin_vlc import VLCOCPAudioService

A = "file:///music/a.mp3"
B = "file:///music/b.mp3"


class FakeEventManager:
    def __init__(self):
        self.callbacks = {}

    def event_attach(self, event_type, callback, *args):
        self.callbacks.setdefault(event_type, []).append((callback, args))

    def fire(self, event_type, event):
        for callback, args in self.callbacks.get(event_type, []):
            callback(event, *args)


class FakeMedia:
    def __init__(self, uri):
        self.uri = uri
        self.events = FakeEventManager()

    def event_manager(self):
        return self.events

    def get_mrl(self):
        return self.uri


class FakePlayer:
    def __init__(self):
        self.events = FakeEventManager()
        self.media = None

    def event_manager(self):
        return self.events

    def set_media(self, media):
        self.media = media

    def audio_set_volume(self, volume):
        pass

    def is_playing(self):
        return True

    def stop(self):
        pass


def fake_vlc():
    event_type = SimpleNamespace(
        MediaPlayerPlaying="Playing", MediaPlayerEndReached="EndReached",
        MediaPlayerStopped="PlayerStopped",
        MediaPlayerEncounteredError="PlayerError",
        MediaStateChanged="MediaStateChanged")
    state = SimpleNamespace(Ended="Ended", Stopped="Stopped", Error="Error",
                            Playing="Playing", NothingSpecial="Nothing")
    player = FakePlayer()
    instance = SimpleNamespace(media_player_new=lambda: player,
                               media_new=FakeMedia)
    return SimpleNamespace(EventType=event_type, State=state,
                           Instance=lambda *a: instance), player


def end_media(vlc, player, media, new_state):
    """Fire what libvlc fires when one media ends."""
    media.events.fire(vlc.EventType.MediaStateChanged,
                      SimpleNamespace(u=SimpleNamespace(new_state=new_state)))
    player_event = {"Ended": "EndReached", "Stopped": "PlayerStopped",
                    "Error": "PlayerError"}[new_state]
    player.events.fire(player_event, SimpleNamespace())


class TestStaleSwitch(unittest.TestCase):
    def setUp(self):
        self.vlc, self.player = fake_vlc()
        patcher = patch.object(ovos_media_plugin_vlc, "vlc", self.vlc)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.svc = VLCOCPAudioService({}, bus=MagicMock())
        self.events = []
        self.svc.bind_event_reporter(
            lambda event, **data: self.events.append((event, data)))

    def test_end_of_replaced_media_carries_its_own_uri(self):
        self.svc.load_track(A)
        media_a = self.player.media
        self.svc.load_track(B)
        end_media(self.vlc, self.player, media_a, "Ended")
        self.assertEqual(self.events, [(PlaybackEvent.END_OF_MEDIA, {"uri": A})])

    def test_error_of_replaced_media_carries_its_own_uri(self):
        self.svc.load_track(A)
        media_a = self.player.media
        self.svc.load_track(B)
        end_media(self.vlc, self.player, media_a, "Error")
        self.assertEqual(len(self.events), 1)
        event, data = self.events[0]
        self.assertEqual(event, PlaybackEvent.ERROR)
        self.assertEqual(data["uri"], A)

    def test_stop_reports_stopped_with_current_uri(self):
        self.svc.load_track(A)
        self.svc.stop()
        end_media(self.vlc, self.player, self.player.media, "Stopped")
        self.assertEqual(self.events, [(PlaybackEvent.STOPPED, {"uri": A})])


if __name__ == "__main__":
    unittest.main()
