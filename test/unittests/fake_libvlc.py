"""A fake ``vlc`` module that sends events in the order of libvlc 3.0.

References are to ``lib/media_player.c`` on the VLC 3.0.x branch:

- ``input_event_changed``: ``END_S`` sets the state Ended and sends
  ``MediaPlayerEndReached``; ``ERROR_S`` sets Error and sends
  ``MediaPlayerEncounteredError``; ``INPUT_EVENT_DEAD``, which the input
  thread always sends when it exits, sets Ended and sends
  ``MediaPlayerStopped``.
- ``release_input_thread`` deletes the ``intf-event`` callback before it
  stops the input, so an input that is released sends nothing more.
  ``set_media``, ``play`` of a new input and ``stop`` release the input.
- ``set_state`` copies each state to the current media as
  ``MediaStateChanged``.
- ``libvlc_media_player_stop`` sends one ``MediaPlayerStopped`` if the
  state is not Stopped.
"""
from types import SimpleNamespace

State = SimpleNamespace(NothingSpecial=0, Opening=1, Buffering=2, Playing=3,
                        Paused=4, Stopped=5, Ended=6, Error=7)
EventType = SimpleNamespace(
    MediaPlayerPlaying="MediaPlayerPlaying",
    MediaPlayerEndReached="MediaPlayerEndReached",
    MediaPlayerEncounteredError="MediaPlayerEncounteredError",
    MediaPlayerStopped="MediaPlayerStopped",
    MediaStateChanged="MediaStateChanged")
Meta = SimpleNamespace(Album="Album", Artist="Artist", Title="Title")


class EventManager:
    def __init__(self):
        self.callbacks = []

    def event_attach(self, event_type, callback, *args):
        self.callbacks.append((event_type, callback, args))

    def send(self, event_type, event):
        for attached, callback, args in list(self.callbacks):
            if attached == event_type:
                callback(event, *args)


class Media:
    def __init__(self, uri):
        self.uri = uri
        self.events = EventManager()

    def event_manager(self):
        return self.events

    def get_mrl(self):
        return self.uri

    def get_meta(self, key):
        return None


class Player:
    def __init__(self):
        self.events = EventManager()
        self.media = None
        self.state = State.NothingSpecial
        self.input = None  # the live input thread, or None
        self._inputs = 0

    def event_manager(self):
        return self.events

    def _set_state(self, state):
        self.state = state
        if self.media:
            self.media.events.send(
                EventType.MediaStateChanged,
                SimpleNamespace(u=SimpleNamespace(new_state=state)))

    def _input_event(self, token, state, event_type):
        if self.input != token:
            return  # released: its intf-event callback is gone
        self._set_state(state)
        self.events.send(event_type, SimpleNamespace())

    def set_media(self, media):
        self.input = None
        self._set_state(State.NothingSpecial)
        self.media = media

    def play(self):
        self._inputs += 1
        self.input = self._inputs
        self._set_state(State.Playing)
        self.events.send(EventType.MediaPlayerPlaying, SimpleNamespace())

    def natural_end(self):
        token = self.input
        self._input_event(token, State.Ended, EventType.MediaPlayerEndReached)
        self._input_event(token, State.Ended, EventType.MediaPlayerStopped)
        if self.input == token:
            self.input = None

    def error(self):
        token = self.input
        self._input_event(token, State.Error,
                          EventType.MediaPlayerEncounteredError)
        self._input_event(token, State.Ended, EventType.MediaPlayerStopped)
        if self.input == token:
            self.input = None

    def stop(self):
        self.input = None
        if self.state != State.Stopped:
            self._set_state(State.Stopped)
            self.events.send(EventType.MediaPlayerStopped, SimpleNamespace())

    def is_playing(self):
        return self.state == State.Playing

    def get_state(self):
        return self.state

    def get_media(self):
        return self.media

    def get_length(self):
        return 1000

    def get_time(self):
        return 0

    def set_time(self, ms):
        pass

    def set_pause(self, pause):
        self.state = State.Paused if pause else State.Playing

    def audio_set_volume(self, volume):
        pass

    def toggle_fullscreen(self):
        pass


def make_vlc():
    """Return a fresh fake ``vlc`` module and the list of players it made."""
    players = []

    def media_player_new():
        players.append(Player())
        return players[-1]

    instance = SimpleNamespace(media_player_new=media_player_new,
                               media_new=Media)
    vlc = SimpleNamespace(State=State, EventType=EventType, Meta=Meta,
                          Instance=lambda *args: instance)
    return vlc, players
