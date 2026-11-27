"""Legacy ``ovos-audio`` (mycroft.plugin.audioservice) adapter.

The same VLC engine as the new ovos-media :class:`VLCOCPAudioService`, exposed
under the legacy audio-service contract so this plugin works on both stacks:

* new ``ovos-media`` — ``opm.media.audio`` → :class:`~ovos_media_plugin_vlc.VLCOCPAudioService`
* legacy ``ovos-audio`` — ``mycroft.plugin.audioservice`` → :class:`VLCAudioService`
  (discovered via :func:`load_service`)
"""
from ovos_plugin_manager.templates.audio import AudioBackend
from ovos_plugin_manager.templates.media import MediaBackend, PlaybackEvent
from ovos_utils.log import LOG

from ovos_media_plugin_vlc import VlcBaseService


class VLCAudioService(VlcBaseService, AudioBackend):
    """VLC backend for the legacy ovos-audio service.

    Reuses every playback method (``play``/``stop``/``pause``/``resume``/
    seek/volume/track-info) from :class:`VlcBaseService`; only the constructor
    differs because the legacy ``AudioBackend`` takes a ``name``.

    ``VlcBaseService`` is listed first so its concrete methods satisfy the
    abstract playback methods declared on ``AudioBackend`` (MRO order matters).
    """

    def __init__(self, config, bus=None, name='vlc'):
        MediaBackend.__init__(self, config, bus)
        AudioBackend.__init__(self, config, bus, name)
        self._init_vlc(config, bus, video=False)
        # ovos-audio has no event reporter: translate the reports into the
        # legacy track-start callback.
        self.bind_event_reporter(self._report_legacy)

    def _report_legacy(self, event, **data):
        if event == PlaybackEvent.TRACK_START:
            if self._track_start_callback:
                self._track_start_callback(
                    self.track_info().get('name', "track"))
        elif event == PlaybackEvent.END_OF_MEDIA:
            if self._track_start_callback:
                self._track_start_callback(None)
            else:
                self.ocp_stop()
        elif event == PlaybackEvent.ERROR:
            self.ocp_error()

    def load_track(self, uri, metadata=None):
        """Set the legacy ``_now_playing`` that the ``ocp_*`` reports read,
        then load the track in VLC."""
        AudioBackend.load_track(self, uri)
        return VlcBaseService.load_track(self, uri, metadata)

    def play(self, repeat=False):
        """ Play the loaded track; ovos-audio passes ``repeat``. """
        VlcBaseService.play(self)


def load_service(base_config, bus):
    backends = base_config.get('backends', {})
    services = [(b, backends[b]) for b in backends
                if backends[b].get('type') in ['vlc', 'ovos_vlc'] and
                backends[b].get('active', True)]
    instances = [VLCAudioService(s[1], bus, s[0]) for s in services]
    if len(instances) == 0:
        LOG.warning("No VLC backends have been configured")
    return instances
