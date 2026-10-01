"""Legacy ``ovos-audio`` (mycroft.plugin.audioservice) adapter.

The same VLC engine as the new ovos-media :class:`VLCOCPAudioService`, exposed
under the legacy audio-service contract so this plugin works on both stacks:

* new ``ovos-media`` — ``opm.media.audio`` → :class:`~ovos_media_plugin_vlc.VLCOCPAudioService`
* legacy ``ovos-audio`` — ``mycroft.plugin.audioservice`` → :class:`VLCAudioService`
  (discovered via :func:`load_service`)
"""
from ovos_plugin_manager.templates.audio import AudioBackend
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
        AudioBackend.__init__(self, config, bus, name)
        # AudioBackend.__init__ (legacy v1 template) never runs
        # MediaBackend.__init__, so the report()/report_track_end()
        # bookkeeping those methods rely on (_event_reporter,
        # _stop_requested) would otherwise never get initialized on this
        # adapter - set it up explicitly since we still drive the shared
        # v2 VlcBaseService engine underneath.
        self._event_reporter = None
        self._stop_requested = False
        # set up the VLC engine without the new MediaBackend constructor
        self._init_vlc(config, bus, video=False)


def load_service(base_config, bus):
    backends = base_config.get('backends', {})
    services = [(b, backends[b]) for b in backends
                if backends[b].get('type') in ['vlc', 'ovos_vlc'] and
                backends[b].get('active', True)]
    instances = [VLCAudioService(s[1], bus, s[0]) for s in services]
    if len(instances) == 0:
        LOG.warning("No VLC backends have been configured")
    return instances
