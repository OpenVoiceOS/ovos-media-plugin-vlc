import time

import vlc
from ovos_bus_client.message import Message

from ovos_plugin_manager.templates.media import MediaBackend, AudioPlayerBackend, VideoPlayerBackend
from ovos_utils.log import LOG


class VlcBaseService(MediaBackend):
    def __init__(self, config, bus=None, video=False):
        super().__init__(config, bus)
        self._init_vlc(config, bus, video=video)

    def _init_vlc(self, config, bus=None, video=False):
        """Set up the libvlc engine + event handlers.

        Factored out of ``__init__`` so it can be shared by both the new
        ``MediaBackend`` (ovos-media) backends and the legacy ``AudioBackend``
        (ovos-audio) adapter, which have different base-class constructors but
        drive the same VLC engine underneath.
        """
        if video:
            self.instance = vlc.Instance("")
        else:
            self.instance = vlc.Instance("--no-video")

        self.player = self.instance.media_player_new()
        self.vlc_events = self.player.event_manager()

        self.vlc_events.event_attach(vlc.EventType.MediaPlayerPlaying,
                                     self.track_start, 1)
        self.vlc_events.event_attach(vlc.EventType.MediaPlayerTimeChanged,
                                     self.update_playback_time, None)
        self.vlc_events.event_attach(vlc.EventType.MediaPlayerEndReached,
                                     self.queue_ended, 0)
        self.vlc_events.event_attach(vlc.EventType.MediaPlayerEncounteredError,
                                     self.handle_vlc_error, None)

        self.config = config
        self.bus = bus
        self.low_volume = self.config.get('low_volume', 30)
        self._playback_time = 0
        self.player.audio_set_volume(100)
        self._last_sync = 0
        if video and self.config.get("fullscreen", True):
            self.player.toggle_fullscreen()

    # vlc internals
    @property
    def playback_time(self):
        """ in milliseconds """
        return self._playback_time

    def handle_vlc_error(self, data, other):
        self.ocp_error()

    def update_playback_time(self, data, other):
        self._playback_time = data.u.new_time
        # this message is captured by ovos common play and used to sync the
        # seekbar
        if time.time() - self._last_sync > 2:
            # send event ~ every 2 s
            # the gui seems to lag a lot when sending messages too often,
            # gui expected to keep an internal fake progress bar and sync periodically
            self._last_sync = time.time()
            self.bus.emit(Message("ovos.common_play.playback_time",
                                  {"position": self._playback_time,
                                   "length": self.get_track_length()}))

    def track_start(self, data, other):
        LOG.debug('VLC playback start')
        if self._track_start_callback:
            self._track_start_callback(self.track_info().get('name', "track"))

    def queue_ended(self, data, other):
        LOG.debug('VLC playback ended')
        if self._track_start_callback:
            self._track_start_callback(None)
        # natural end-of-media (vlc reached end on its own, no stop()
        # requested by us) - ocp_stop() is idempotent (no-ops once
        # self._now_playing is None), so it is safe to call here even
        # when stop() already triggered it; this is the only path that
        # reports a *natural* end-of-media upward
        self.ocp_stop()

    def supported_uris(self):
        return ['file', 'http', 'https']

    # audio service
    def play(self, repeat=False):
        """ Play playlist using vlc. """
        LOG.debug('VLCService Play')
        track = self.instance.media_new(self._now_playing)
        track.get_mrl()
        self.player.set_media(track)
        self.player.play()

    def stop(self):
        """ Stop vlc playback. """
        LOG.info('VLCService Stop')
        if self.player.is_playing():
            self.player.stop()
            return True
        return False

    def pause(self):
        """ Pause vlc playback. """
        self.player.set_pause(1)

    def resume(self):
        """ Resume paused playback. """
        self.player.set_pause(0)

    def track_info(self):
        """ Extract info of current track. """
        ret = {}
        t = self.player.get_media()
        if t:
            ret['album'] = t.get_meta(vlc.Meta.Album)
            ret['artist'] = t.get_meta(vlc.Meta.Artist)
            ret['title'] = t.get_meta(vlc.Meta.Title)
        return ret

    def _has_media_loaded(self):
        """True once a track is loaded, through playing, paused or buffering.

        ``is_playing()`` is false while paused, but a paused track still has
        a real position and length, so the guard has to test for loaded
        media, not for active playback. ``get_state()`` answers
        ``NothingSpecial`` before anything is loaded and ``Stopped``,
        ``Ended`` or ``Error`` once playback ends; every other state keeps a
        track loaded.
        """
        return self.player.get_state() not in (
            vlc.State.NothingSpecial, vlc.State.Stopped,
            vlc.State.Ended, vlc.State.Error)

    def get_track_length(self):
        """
        getting the duration of the audio in milliseconds

        ``None`` means nothing is loaded. libVLC answers 0, not -1, for a
        live stream's unknown duration; this reports the MediaBackend
        contract's -1 for that case instead of the raw 0.
        """
        if not self._has_media_loaded():
            return None
        length = self.player.get_length()
        return length if length > 0 else -1

    def get_track_position(self):
        """
        get current position in milliseconds

        ``None`` means nothing is loaded. A paused track and a live stream
        both have a real elapsed position, so it is returned like any other
        track's.
        """
        if not self._has_media_loaded():
            return None
        return self.player.get_time()

    def set_track_position(self, milliseconds):
        """
        go to position in milliseconds

          Args:
                milliseconds (int): number of milliseconds of final position
        """
        self.player.set_time(int(milliseconds))

    def seek_forward(self, seconds=1):
        """
        skip X seconds

          Args:
                seconds (int): number of seconds to seek, if negative rewind
        """
        seconds = seconds * 1000
        new_time = self.player.get_time() + seconds
        duration = self.player.get_length()
        if new_time > duration:
            new_time = duration
        self.player.set_time(new_time)

    def seek_backward(self, seconds=1):
        """
        rewind X seconds

          Args:
                seconds (int): number of seconds to seek, if negative rewind
        """
        seconds = seconds * 1000
        new_time = self.player.get_time() - seconds
        if new_time < 0:
            new_time = 0
        self.player.set_time(new_time)

    def lower_volume(self):
        """Lower volume.

        This method is used to implement audio ducking. It will be called when
        OpenVoiceOS is listening or speaking to make sure the media playing isn't
        interfering.
        """
        self.player.audio_set_volume(self.low_volume)

    def restore_volume(self):
        """Restore normal volume.

        Called when to restore the playback volume to previous level after
        OpenVoiceOS has lowered it using lower_volume().
        """
        self.player.audio_set_volume(100)


class VLCOCPAudioService(AudioPlayerBackend, VlcBaseService):
    def __init__(self, config, bus=None):
        super().__init__(config, bus, video=False)


class VLCOCPVideoService(VideoPlayerBackend, VlcBaseService):
    def __init__(self, config, bus=None):
        super().__init__(config, bus, video=True)
