import vlc

from ovos_plugin_manager.templates.media import (
    MediaBackend, AudioPlayerBackend, VideoPlayerBackend, PlaybackEvent)
from ovos_utils.log import LOG


class VlcBaseService(MediaBackend):
    can_seek = True
    can_pause = True

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
        # both a natural end (vlc reaches EOF on its own) and an explicit
        # stop() (which libvlc reports asynchronously via
        # MediaPlayerStopped, not synchronously from stop() itself) end up
        # at the *same* end-of-track handler; report_track_end tells them
        # apart via the _stop_requested flag the base class's stop() sets.
        self.vlc_events.event_attach(vlc.EventType.MediaPlayerEndReached,
                                     self.queue_ended, 0)
        self.vlc_events.event_attach(vlc.EventType.MediaPlayerStopped,
                                     self.queue_ended, 0)
        self.vlc_events.event_attach(vlc.EventType.MediaPlayerEncounteredError,
                                     self.handle_vlc_error, None)

        self.config = config
        self.bus = bus
        self.low_volume = self.config.get('low_volume', 30)
        self._loaded_uri = None
        self.player.audio_set_volume(100)
        if video and self.config.get("fullscreen", True):
            self.player.toggle_fullscreen()

    # vlc internals
    def handle_vlc_error(self, data, other):
        # an encountered error is also the end of the track - libvlc does
        # not additionally fire MediaPlayerEndReached/MediaPlayerStopped
        # for it, so this is the only end-of-track signal for a failed
        # track and must go through report_track_end (not a bare
        # report(ERROR, ...)) so the pending _stop_requested flag is
        # cleared the same way every other end-of-track path clears it.
        self.report_track_end(uri=self._loaded_uri,
                              error="libvlc reported a playback error")

    def track_start(self, data, other):
        LOG.debug('VLC playback start')
        self.report(PlaybackEvent.TRACK_START, uri=self._loaded_uri)

    def queue_ended(self, data, other):
        """Single convergence point for every "playback is no longer
        happening" signal libvlc can fire: a natural end
        (MediaPlayerEndReached) and an explicit stop() (MediaPlayerStopped,
        fired asynchronously by libvlc, not by our _stop()). Neither event
        alone knows *why* playback stopped, so report_track_end decides
        using the _stop_requested flag the base class's stop() sets.
        """
        LOG.debug('VLC playback ended')
        self.report_track_end(uri=self._loaded_uri)

    def supported_uris(self):
        return ['file', 'http', 'https']

    # audio service
    def load_track(self, uri: str, metadata: dict = None) -> bool:
        """ Load track using vlc. """
        LOG.debug('VLCService Load')
        track = self.instance.media_new(uri)
        track.get_mrl()
        self.player.set_media(track)
        self._loaded_uri = uri
        return True

    def play(self):
        """ Play the loaded track using vlc. """
        LOG.debug('VLCService Play')
        self.player.play()

    def _stop(self):
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
