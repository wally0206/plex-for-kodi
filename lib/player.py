import base64
import threading

import xbmc
import xbmcgui
import kodijsonrpc
import colors
from windows import seekdialog
import util
from plexnet import plexplayer
from plexnet import plexapp

from plexnet import signalsmixin


class BasePlayerHandler(object):
    def __init__(self, player):
        self.player = player
        self.baseOffset = 0
        self.timelineType = None
        self.lastTimelineState = None
        self.ignoreTimelines = False
        self.playQueue = None

    def onPlayBackStarted(self):
        pass

    def onPlayBackPaused(self):
        pass

    def onPlayBackResumed(self):
        pass

    def onPlayBackStopped(self):
        pass

    def onPlayBackEnded(self):
        pass

    def onPlayBackSeek(self, stime, offset):
        pass

    def onPlayBackFailed(self):
        pass

    def onVideoWindowOpened(self):
        pass

    def onVideoWindowClosed(self):
        pass

    def onVideoOSD(self):
        pass

    def onSeekOSD(self):
        pass

    def onMonitorInit(self):
        pass

    def tick(self):
        pass

    def close(self):
        pass

    @property
    def trueTime(self):
        return self.baseOffset + self.player.currentTime

    def getCurrentItem(self):
        if self.player.playerObject:
            return self.player.playerObject.item
        return None

    def shouldSendTimeline(self, item):
        return item.ratingKey and item.getServer()

    def updateNowPlaying(self, force=False, refreshQueue=False, state=None):
        if self.ignoreTimelines:
            return

        item = self.getCurrentItem()

        if not item:
            return

        if not self.shouldSendTimeline(item):
            return

        state = state or self.player.playState
        # Avoid duplicates
        if state == self.lastTimelineState and not force:
            return

        self.lastTimelineState = state
        # self.timelineTimer.reset()

        time = int(self.trueTime * 1000)

        # self.trigger("progress", [m, item, time])

        if refreshQueue and self.playQueue:
            self.playQueue.refreshOnTimeline = True

        plexapp.APP.nowplayingmanager.updatePlaybackState(self.timelineType, self.player.playerObject, state, time, self.playQueue)


class SeekPlayerHandler(BasePlayerHandler):
    NO_SEEK = 0
    SEEK_INIT = 1
    SEEK_IN_PROGRESS = 2
    SEEK_PLAYLIST = 3

    MODE_ABSOLUTE = 0
    MODE_RELATIVE = 1

    def __init__(self, player):
        BasePlayerHandler.__init__(self, player)
        self.dialog = seekdialog.SeekDialog.create(show=False, handler=self)
        self.playlist = None
        self.playQueue = None
        self.timelineType = 'video'
        self.reset()

    def reset(self):
        self.duration = 0
        self.offset = 0
        self.baseOffset = 0
        self.seeking = self.NO_SEEK
        self.seekOnStart = 0
        self.mode = self.MODE_RELATIVE

    def setup(self, duration, offset, bif_url, title='', title2='', seeking=NO_SEEK):
        self.baseOffset = offset / 1000.0
        self.seeking = seeking
        self.duration = duration
        self.dialog.setup(duration, offset, bif_url, title, title2)

    def next(self):
        if not self.playlist or not self.playlist.next():
            return False

        self.seeking = self.SEEK_PLAYLIST
        self.player.playVideoPlaylist(self.playlist, handler=self)

        return True

    def prev(self):
        if not self.playlist or not self.playlist.prev():
            return False

        self.seeking = self.SEEK_PLAYLIST
        self.player.playVideoPlaylist(self.playlist, handler=self)

        return True

    def playAt(self, pos):
        if not self.playlist or not self.playlist.setCurrent(pos):
            return False

        self.seeking = self.SEEK_PLAYLIST
        self.player.playVideoPlaylist(self.playlist, handler=self)

        return True

    def onSeekAborted(self):
        if self.seeking:
            self.seeking = self.NO_SEEK
            self.player.control('play')

    def showSeekDialog(self, from_seek=False):
        xbmc.executebuiltin('Dialog.Close(videoosd,true)')
        if xbmc.getCondVisibility('Player.showinfo'):
            xbmc.executebuiltin('Action(Info)')
        self.updateOffset()
        self.dialog.update(self.offset, from_seek)
        self.dialog.show()

    def seek(self, offset, settings_changed=False):
        if self.mode == self.MODE_ABSOLUTE and not settings_changed:
            self.offset = offset
            util.DEBUG_LOG('New player offset: {0}'.format(self.offset))
            return self.seekAbsolute(offset)

        self.seeking = self.SEEK_IN_PROGRESS
        self.offset = offset
        # self.player.control('play')
        util.DEBUG_LOG('New player offset: {0}'.format(self.offset))
        self.player._playVideo(offset, seeking=self.seeking, force_update=settings_changed)

    def seekAbsolute(self, seek=None):
        self.seekOnStart = seek or self.seekOnStart
        if self.seekOnStart:
            self.player.control('play')
            self.player.seekTime(self.seekOnStart / 1000.0)

    def closeSeekDialog(self):
        util.CRON.forceTick()
        if self.dialog:
            self.dialog.doClose()

    def onPlayBackStarted(self):
        self.updateNowPlaying(refreshQueue=True)
        if self.mode == self.MODE_ABSOLUTE:
            self.seekAbsolute()

        subs = self.player.video.selectedSubtitleStream()
        if subs:
            xbmc.sleep(100)
            self.player.showSubtitles(False)
            path = subs.getSubtitleServerPath()
            if path:
                util.DEBUG_LOG('Setting subtitle path: {0}'.format(path))
                self.player.setSubtitles(path)
            else:
                # util.TEST(subs.__dict__)
                # util.TEST(self.player.video.mediaChoice.__dict__)
                util.DEBUG_LOG('Enabling embedded subtitles at: {0}'.format(subs.index))
                util.DEBUG_LOG('Kodi reported subtitles: {0}'.format(self.player.getAvailableSubtitleStreams()))
                self.player.setSubtitleStream(subs.index.asInt())

            self.player.showSubtitles(True)

        self.seeking = self.NO_SEEK

    def onPlayBackResumed(self):
        self.updateNowPlaying()
        self.closeSeekDialog()

    def onPlayBackStopped(self):
        self.updateNowPlaying()
        if self.seeking != self.SEEK_PLAYLIST:
            self.closeSeekDialog()

        if self.seeking not in (self.SEEK_IN_PROGRESS, self.SEEK_PLAYLIST):
            self.sessionEnded()

    def onPlayBackEnded(self):
        self.updateNowPlaying()
        if self.next():
            return

        if self.seeking != self.SEEK_PLAYLIST:
            self.closeSeekDialog()

        if self.seeking not in (self.SEEK_IN_PROGRESS, self.SEEK_PLAYLIST):
            self.sessionEnded()

    def onPlayBackPaused(self):
        self.updateNowPlaying()

    def onPlayBackSeek(self, stime, offset):
        if self.seekOnStart:
            self.seekOnStart = 0
            return

        self.seeking = self.SEEK_INIT
        self.player.control('pause')
        self.updateOffset()
        self.showSeekDialog(from_seek=True)

    def updateOffset(self):
        self.offset = int(self.player.getTime() * 1000)

    def onPlayBackFailed(self):
        if self.seeking != self.SEEK_PLAYLIST:
            self.sessionEnded()
        self.seeking = self.NO_SEEK
        return True

    def onSeekOSD(self):
        if self.dialog.isOpen:
            self.closeSeekDialog()
            self.showSeekDialog()

    def onVideoWindowClosed(self):
        self.closeSeekDialog()
        util.DEBUG_LOG('Video window closed - Seeking={0}'.format(self.seeking))
        if not self.seeking:
            self.player.stop()
            if not self.playlist or not self.playlist.hasNext():
                self.sessionEnded()

    def onVideoOSD(self):
        # xbmc.executebuiltin('Dialog.Close(seekbar,true)')  # Doesn't work :)
        # if not self.seeking:
        self.showSeekDialog()

    def tick(self):
        self.updateNowPlaying(force=True)
        self.dialog.tick()

    def close(self):
        self.closeSeekDialog()

    def sessionEnded(self):
        self.player.trigger('session.ended')


class AudioPlayerHandler(BasePlayerHandler):
    def __init__(self, player, window=None):
        BasePlayerHandler.__init__(self, player)
        self.window = window
        self.timelineType = 'music'
        if self.player.isPlayingAudio():
            self.extractTrackInfo()

    def extractTrackInfo(self):
        plexID = None
        for x in range(10):  # Wait a sec (if necessary) for this to become available
            try:
                item = kodijsonrpc.rpc.Player.GetItem(playerid=0, properties=['comment'])['item']
                plexID = item['comment']
            except:
                util.ERROR()

            if plexID:
                break
            xbmc.sleep(100)

        if not plexID:
            return

        if not plexID.startswith('PLEX-'):
            return

        util.DEBUG_LOG('Extracting track info from comment')
        try:
            data = plexID.split(':', 1)[-1]
            from plexnet import plexobjects
            track = plexobjects.PlexObject.deSerialize(base64.urlsafe_b64decode(data.encode('utf-8')))
            pobj = plexplayer.PlexAudioPlayer(track)
            self.player.playerObject = pobj
            self.updatePlayQueueTrack(track)
        except:
            util.ERROR()

    def setPlayQueue(self, pq):
        self.playQueue = pq
        pq.on('items.changed', self.playQueueCallback)

    def playQueueCallback(self, **kwargs):
        plist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        # plist.clear()
        try:
            citem = kodijsonrpc.rpc.Player.GetItem(playerid=0, properties=['comment'])['item']
            plexID = citem['comment'].split(':', 1)[0]
        except:
            util.ERROR()
            return

        current = plist.getposition()
        size = plist.size()

        # Remove everything but the current track
        for x in range(size - 1, current, -1):  # First everything with a greater position
            kodijsonrpc.rpc.Playlist.Remove(playlistid=xbmc.PLAYLIST_MUSIC, position=x)
        for x in range(current):  # Then anything with a lesser position
            kodijsonrpc.rpc.Playlist.Remove(playlistid=xbmc.PLAYLIST_MUSIC, position=0)

        swap = None
        for idx, track in enumerate(self.playQueue.items()):
            tid = 'PLEX-{0}'.format(track.ratingKey)
            if tid == plexID:
                # Save the position of the current track in the pq
                swap = idx

            url, li = self.player.createTrackListItem(track, index=idx + 1)

            plist.add(url, li)

        plist[0].setInfo('music', {
            'playcount': swap + 1,
        })

        # Now swap the track to the correct position. This seems to be the only way to update the kodi playlist position to the current track's new position
        if swap is not None:
            kodijsonrpc.rpc.Playlist.Swap(playlistid=xbmc.PLAYLIST_MUSIC, position1=0, position2=swap + 1)
            kodijsonrpc.rpc.Playlist.Remove(playlistid=xbmc.PLAYLIST_MUSIC, position=0)

        self.player.trigger('playlist.changed')

    def updatePlayQueue(self, delay=False):
        if not self.playQueue:
            return

        self.playQueue.refresh(delay=delay)

    def updatePlayQueueTrack(self, track):
        if not self.playQueue:
            return

        self.playQueue.selectedId = track.playQueueItemID or None

    @property
    def trueTime(self):
        try:
            return self.player.getTime()
        except:
            return self.player.currentTime

    def stampCurrentTime(self):
        try:
            self.player.currentTime = self.player.getTime()
        except RuntimeError:  # Not playing
            pass

    def onMonitorInit(self):
        self.extractTrackInfo()
        self.updateNowPlaying(state='playing')

    def onPlayBackStarted(self):
        self.updatePlayQueue(delay=True)
        self.extractTrackInfo()
        self.updateNowPlaying(state='playing')

    def onPlayBackResumed(self):
        self.updateNowPlaying(state='playing')

    def onPlayBackPaused(self):
        self.updateNowPlaying(state='paused')

    def onPlayBackStopped(self):
        self.updatePlayQueue()
        self.updateNowPlaying(state='stopped')
        self.closeWindow()

    def onPlayBackEnded(self):
        self.updatePlayQueue()
        self.updateNowPlaying(state='stopped')
        self.closeWindow()

    def onPlayBackFailed(self):
        return True

    def closeWindow(self):
        if not self.window:
            return

        self.window.doClose()
        del self.window
        self.window = None

    def tick(self):
        self.stampCurrentTime()
        self.updateNowPlaying(force=True)


class PlexPlayer(xbmc.Player, signalsmixin.SignalsMixin):
    STATE_STOPPED = "stopped"
    STATE_PLAYING = "playing"
    STATE_PAUSED = "paused"
    STATE_BUFFERING = "buffering"

    def init(self):
        self._closed = False
        self._nextItem = None
        self.started = False
        self.video = None
        self.hasOSD = False
        self.hasSeekOSD = False
        self.xbmcMonitor = util.MONITOR
        self.handler = AudioPlayerHandler(self)
        self.playerObject = None
        self.currentTime = 0
        self.seekStepsSetting = util.SettingControl('videoplayer.seeksteps', 'Seek steps', disable_value=[-10, 10])
        self.seekDelaySetting = util.SettingControl('videoplayer.seekdelay', 'Seek delay', disable_value=0)
        self.thread = None
        if xbmc.getCondVisibility('Player.HasMedia'):
            self.started = True
        self.open()

        return self

    def open(self):
        self._closed = False
        self.monitor()

    def close(self, shutdown=False):
        self._closed = True

    def reset(self):
        self.video = None
        self.started = False
        self.playerObject = None
        self.handler = AudioPlayerHandler(self)
        self.currentTime = 0

    def control(self, cmd):
        if cmd == 'play':
            util.DEBUG_LOG('Player - Control:  Command=Play')
            if xbmc.getCondVisibility('Player.Paused | !Player.Playing'):
                util.DEBUG_LOG('Player - Control:  Playing')
                xbmc.executebuiltin('PlayerControl(Play)')
        elif cmd == 'pause':
            util.DEBUG_LOG('Player - Control:  Command=Pause')
            if not xbmc.getCondVisibility('Player.Paused'):
                util.DEBUG_LOG('Player - Control:  Pausing')
                xbmc.executebuiltin('PlayerControl(Play)')

    @property
    def playState(self):
        if xbmc.getCondVisibility('Player.Playing'):
            return self.STATE_PLAYING
        elif xbmc.getCondVisibility('Player.Caching'):
            return self.STATE_BUFFERING
        elif xbmc.getCondVisibility('Player.Paused'):
            return self.STATE_PAUSED

        return self.STATE_STOPPED

    def videoIsFullscreen(self):
        return xbmc.getCondVisibility('VideoPlayer.IsFullscreen')

    def playAt(self, path, ms):
        """
        Plays the video specified by path.
        Optionally set the start position with h,m,s,ms keyword args.
        """
        seconds = ms / 1000.0

        h = int(seconds / 3600)
        m = int((seconds % 3600) / 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)

        kodijsonrpc.rpc.Player.Open(
            item={'file': path},
            options={'resume': {'hours': h, 'minutes': m, 'seconds': s, 'milliseconds': ms}}
        )

    def play(self, *args, **kwargs):
        self.started = False
        xbmc.Player.play(self, *args, **kwargs)

    def playVideo(self, video, resume=False, force_update=False):
        self.handler = SeekPlayerHandler(self)
        self.video = video
        self.open()
        self._playVideo(resume and video.viewOffset.asInt() or 0, force_update=force_update)

    def _playVideo(self, offset=0, seeking=0, force_update=False):
        self.playerObject = plexplayer.PlexPlayer(self.video, offset, forceUpdate=force_update)
        meta = self.playerObject.build()
        url = meta.streamUrls[0]
        bifURL = self.playerObject.getBifUrl()
        util.DEBUG_LOG('Playing URL(+{1}ms): {0}{2}'.format(url, offset, bifURL and ' - indexed' or ''))
        self.handler.setup(self.video.duration.asInt(), offset, bifURL, title=self.video.grandparentTitle, title2=self.video.title, seeking=seeking)
        url = util.addURLParams(url, {
            'X-Plex-Platform': 'Chrome',
            'X-Plex-Client-Identifier': plexapp.INTERFACE.getGlobal('clientIdentifier')
        })
        li = xbmcgui.ListItem(self.video.title, path=url, thumbnailImage=self.video.defaultThumb.asTranscodedImageURL(256, 256))
        vtype = self.video.type if self.video.type in ('movie', 'episode', 'musicvideo') else 'video'
        li.setInfo('video', {
            'mediatype': vtype,
            'title': self.video.title,
            'tvshowtitle': self.video.grandparentTitle,
            'episode': self.video.index.asInt(),
            'season': self.video.parentIndex.asInt(),
            'year': self.video.year.asInt(),
            'plot': self.video.summary
        })
        self.stopAndWait()
        self.play(url, li)

        if offset and not meta.isTranscoded:
            self.handler.seekOnStart = meta.playStart * 1000
            self.handler.mode = self.handler.MODE_ABSOLUTE
        else:
            self.handler.mode = self.handler.MODE_RELATIVE

    def playVideoPlaylist(self, playlist, resume=True, handler=None):
        if not handler:
            self.handler = SeekPlayerHandler(self)
        self.handler.playlist = playlist
        if playlist.isRemote:
            self.handler.playQueue = playlist
        self.video = playlist.current()
        self.open()
        self._playVideo(resume and self.video.viewOffset.asInt() or 0, seeking=handler and handler.SEEK_PLAYLIST or 0)

    def createVideoListItem(self, video, index=0):
        url = 'plugin://script.plex/play?{0}'.format(base64.urlsafe_b64encode(video.serialize()))
        li = xbmcgui.ListItem(self.video.title, path=url, thumbnailImage=self.video.defaultThumb.asTranscodedImageURL(256, 256))
        vtype = self.video.type if self.video.vtype in ('movie', 'episode', 'musicvideo') else 'video'
        li.setInfo('video', {
            'mediatype': vtype,
            'playcount': index,
            'title': video.title,
            'tvshowtitle': video.grandparentTitle,
            'episode': video.index.asInt(),
            'season': video.parentIndex.asInt(),
            'year': video.year.asInt(),
            'plot': video.summary
        })

        return url, li

    def playAudio(self, track, window=None, fanart=None):
        self.handler = AudioPlayerHandler(self, window)
        url, li = self.createTrackListItem(track, fanart)
        self.stopAndWait()
        self.play(url, li)

    def playAlbum(self, album, startpos=-1, window=None, fanart=None):
        self.handler = AudioPlayerHandler(self, window)
        plist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        plist.clear()
        index = 1
        for track in album.tracks():
            url, li = self.createTrackListItem(track, fanart, index=index)
            plist.add(url, li)
            index += 1
        xbmc.executebuiltin('PlayerControl(RandomOff)')
        self.stopAndWait()
        self.play(plist, startpos=startpos)

    def playAudioPlaylist(self, playlist, startpos=-1, window=None, fanart=None):
        self.handler = AudioPlayerHandler(self, window)
        plist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        plist.clear()
        index = 1
        for track in playlist.items():
            url, li = self.createTrackListItem(track, fanart, index=index)
            plist.add(url, li)
            index += 1

        if playlist.isRemote:
            self.handler.setPlayQueue(playlist)
        else:
            if playlist.startShuffled:
                plist.shuffle()
                xbmc.executebuiltin('PlayerControl(RandomOn)')
            else:
                xbmc.executebuiltin('PlayerControl(RandomOff)')
        self.stopAndWait()
        self.play(plist, startpos=startpos)

    def createTrackListItem(self, track, fanart=None, index=0):
        # pobj = plexplayer.PlexAudioPlayer(track)
        # url = pobj.build()['url']  # .streams[0]['url']
        # util.DEBUG_LOG('Playing URL: {0}'.format(url))
        # url += '&X-Plex-Platform=Chrome'
        data = base64.urlsafe_b64encode(track.serialize())
        url = 'plugin://script.plex/play?{0}'.format(data)
        li = xbmcgui.ListItem(track.title, path=url, thumbnailImage=track.defaultThumb.asTranscodedImageURL(256, 256))
        li.setInfo('music', {
            'artist': str(track.grandparentTitle),
            'title': str(track.title),
            'album': str(track.parentTitle),
            'discnumber': track.parentIndex.asInt(),
            'tracknumber': track.get('index').asInt(),
            'duration': int(track.duration.asInt() / 1000),
            'playcount': index,
            'comment': 'PLEX-{0}:{1}'.format(track.ratingKey, data)
        })
        art = fanart or track.defaultArt
        li.setArt({
            'fanart': art.asTranscodedImageURL(1920, 1080),
            'landscape': art.asTranscodedImageURL(1920, 1080, blur=128, opacity=60, background=colors.noAlpha.Background)
        })
        if fanart:
            li.setArt({'fanart': fanart})
        return (url, li)

    def onPlayBackStarted(self):
        self.started = True
        util.DEBUG_LOG('Player - STARTED')
        if not self.handler:
            return
        self.handler.onPlayBackStarted()

    def onPlayBackPaused(self):
        util.DEBUG_LOG('Player - PAUSED')
        if not self.handler:
            return
        self.handler.onPlayBackPaused()

    def onPlayBackResumed(self):
        util.DEBUG_LOG('Player - RESUMED')
        if not self.handler:
            return
        self.handler.onPlayBackResumed()

    def onPlayBackStopped(self):
        if not self.started:
            self.onPlayBackFailed()

        util.DEBUG_LOG('Player - STOPPED' + (not self.started and ': FAILED' or ''))
        if not self.handler:
            return
        self.handler.onPlayBackStopped()

    def onPlayBackEnded(self):
        if not self.started:
            self.onPlayBackFailed()

        util.DEBUG_LOG('Player - ENDED' + (not self.started and ': FAILED' or ''))
        if not self.handler:
            return
        self.handler.onPlayBackEnded()

    def onPlayBackSeek(self, time, offset):
        util.DEBUG_LOG('Player - SEEK')
        if not self.handler:
            return
        self.handler.onPlayBackSeek(time, offset)

    def onPlayBackFailed(self):
        if not self.handler:
            return

        if self.handler.onPlayBackFailed():
            util.showNotification('Playback Failed!')
            # xbmcgui.Dialog().ok('Failed', 'Playback failed')

    def onVideoWindowOpened(self):
        util.DEBUG_LOG('Player: Video window opened')
        try:
            self.handler.onVideoWindowOpened()
        except:
            util.ERROR()

    def onVideoWindowClosed(self):
        util.DEBUG_LOG('Player: Video window closed')
        try:
            self.handler.onVideoWindowClosed()
            # self.stop()
        except:
            util.ERROR()

    def onVideoOSD(self):
        util.DEBUG_LOG('Player: Video OSD opened')
        try:
            self.handler.onVideoOSD()
        except:
            util.ERROR()

    def onSeekOSD(self):
        util.DEBUG_LOG('Player: Seek OSD opened')
        try:
            self.handler.onSeekOSD()
        except:
            util.ERROR()

    def stopAndWait(self):
        if self.isPlaying():
            util.DEBUG_LOG('Player: Stopping and waiting...')
            self.stop()
            while not self.xbmcMonitor.waitForAbort(0.1) and self.isPlaying():
                pass
            self.xbmcMonitor.waitForAbort(0.2)
            util.DEBUG_LOG('Player: Stopping and waiting...Done')

    def monitor(self):
        if not self.thread or not self.thread.isAlive():
            self.thread = threading.Thread(target=self._monitor, name='PLAYER:MONITOR')
            self.thread.start()

    def _monitor(self):
        try:
            while not xbmc.abortRequested and not self._closed:
                if not self.isPlaying():
                    util.DEBUG_LOG('Player: Idling...')

                while not self.isPlaying() and not xbmc.abortRequested and not self._closed:
                    self.xbmcMonitor.waitForAbort(0.1)

                if self.isPlayingVideo():
                    util.DEBUG_LOG('Monitoring video...')
                    self._videoMonitor()
                elif self.isPlayingAudio():
                    util.DEBUG_LOG('Monitoring audio...')
                    self._audioMonitor()
                elif self.isPlaying():
                    util.DEBUG_LOG('Monitoring pre-play...')
                    self._preplayMonitor()

            self.handler.close()
            self.close()
            util.DEBUG_LOG('Player: Closed')
        finally:
            self.trigger('session.ended')

    def _preplayMonitor(self):
        while self.isPlaying() and not self.isPlayingVideo() and not self.isPlayingAudio() and not xbmc.abortRequested and not self._closed:
            self.xbmcMonitor.waitForAbort(0.1)

        if not self.isPlayingVideo() and not self.isPlayingAudio():
            self.onPlayBackFailed()

    def _videoMonitor(self):
        with self.seekDelaySetting.suspend():
            with self.seekStepsSetting.suspend():
                hasFullScreened = False

                ct = 0
                while self.isPlayingVideo() and not xbmc.abortRequested and not self._closed:
                    self.currentTime = self.getTime()
                    self.xbmcMonitor.waitForAbort(0.1)
                    if xbmc.getCondVisibility('Window.IsActive(videoosd) | Player.ShowInfo'):
                        if not self.hasOSD:
                            self.hasOSD = True
                            self.onVideoOSD()
                    else:
                        self.hasOSD = False

                    if xbmc.getCondVisibility('Window.IsActive(seekbar)'):
                        if not self.hasSeekOSD:
                            self.hasSeekOSD = True
                            self.onSeekOSD()
                    else:
                        self.hasSeekOSD = False

                    if xbmc.getCondVisibility('VideoPlayer.IsFullscreen'):
                        if not hasFullScreened:
                            hasFullScreened = True
                            self.onVideoWindowOpened()
                    elif hasFullScreened and not xbmc.getCondVisibility('Window.IsVisible(busydialog)'):
                        hasFullScreened = False
                        self.onVideoWindowClosed()

                    ct += 1
                    if ct > 9:
                        ct = 0
                        self.handler.tick()

                if hasFullScreened:
                    self.onVideoWindowClosed()

    def _audioMonitor(self):
        self.started = True
        self.handler.onMonitorInit()
        ct = 0
        while self.isPlayingAudio() and not xbmc.abortRequested and not self._closed:
            self.currentTime = self.getTime()
            self.xbmcMonitor.waitForAbort(0.1)

            ct += 1
            if ct > 9:
                ct = 0
                self.handler.tick()

PLAYER = PlexPlayer().init()
