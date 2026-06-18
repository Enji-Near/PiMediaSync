import sys
import os
from threading import Event, Thread
import logging
from time import sleep, monotonic
from datetime import datetime
import vlc
import pysimpledmx

# neeeded for vlcPlayerMock
import evento

# globals
END_DURATION_OFFSET = .25  # if no SEQUENCE defined, this variable sets how far from the end of the media file to automatically stop playing


class PlayerDeadError(Exception):
    '''
    Raised when the underlying media player has entered an unrecoverable
    state. Replaces omxplayer-wrapper's ``OMXPlayerDeadError`` so the rest
    of the application can keep the same control flow.
    '''
    pass


class VlcPlayer():
    '''
    Thin wrapper around python-vlc (libVLC) that exposes the same interface
    the rest of the application previously relied on from OMXPlayer.

    OMXPlayer was deprecated in 2020 and does not run on Raspberry Pi 4/5.
    libVLC is the modern, actively-maintained replacement and runs on the
    Pi 5. All positions/durations are exposed in *seconds* (libVLC works in
    milliseconds internally) to match the original OMXPlayer behaviour.
    '''

    def __init__(self, filename, logger=None):
        self.logger = logger or logging.getLogger("VlcPlayer")

        # `--no-xlib` lets VLC run without an X11 desktop (e.g. Pi OS Lite),
        # the rest just suppress on-screen titles/overlays for a clean output.
        self.instance = vlc.Instance(
            "--no-osd",
            "--no-video-title-show",
            "--no-xlib",
            "--quiet",
        )
        self.player = self.instance.media_player_new()
        self.media = self.instance.media_new(filename)
        self.player.set_media(self.media)
        self.player.set_fullscreen(True)

        # Parse the media up-front so duration() is available before playback
        # begins (the sync logic needs it when building a default sequence).
        self.media.parse_with_options(vlc.MediaParseFlag.local, 3000)
        deadline = monotonic() + 3.0
        while self.media.get_duration() <= 0 and monotonic() < deadline:
            sleep(0.05)

        # Event hooks kept for API parity with the old OMXPlayer wrapper.
        self.playEvent = evento.event.Event()
        self.pauseEvent = evento.event.Event()
        self.stopEvent = evento.event.Event()
        self.exitEvent = evento.event.Event()
        self.seekEvent = evento.event.Event()
        self.positionEvent = evento.event.Event()

    def hide_video(self):
        # OMXPlayer removed the video layer to show a blank screen when idle.
        # Stopping VLC achieves the same blank-screen result; the next
        # play() restarts the media from the beginning.
        self.player.stop()

    def show_video(self):
        self.player.set_fullscreen(True)

    def play(self):
        self.player.play()
        self.playEvent(self)

    def pause(self):
        self.player.set_pause(1)
        self.pauseEvent(self)

    def stop(self):
        self.player.stop()
        self.stopEvent(self)

    def exit(self):
        self.player.stop()
        self.exitEvent(self)

    def seek(self, seconds):
        # OMXPlayer.seek() was a *relative* seek in seconds.
        target_ms = int(self.player.get_time() + (seconds * 1000))
        self.player.set_time(max(0, target_ms))
        self.seekEvent(self)

    def seek_to_start(self):
        self.player.set_time(0)
        self.seekEvent(self)

    def position(self):
        current_ms = self.player.get_time()
        return (current_ms / 1000.0) if current_ms > 0 else 0.0

    def duration(self):
        length_ms = self.player.get_length()
        if length_ms <= 0:
            length_ms = self.media.get_duration()
        return (length_ms / 1000.0) if length_ms > 0 else 0.0

    def playback_status(self):
        state = self.player.get_state()
        if state == vlc.State.Error:
            raise PlayerDeadError("VLC media player entered an error state")
        if state == vlc.State.Playing:
            return "Playing"
        if state == vlc.State.Paused:
            return "Paused"
        return "Stopped"

    def quit(self):
        self.player.stop()
        self.player.release()
        self.instance.release()

class dmxMock(pysimpledmx.DMXConnection):
    '''
    Used when actual DMX serial device is unavailable
    '''
    def __init__(self):
        self.logger = logging.getLogger("dmxMock")
        self.logger.info("Mock DMX class initiated")

    def ramp(self, channels, steps, duration):
        self.logger.info("Mock DMX ramp method")
        mix = list(zip(channels, steps))
        self.logger.info("Channels and Steps: {}".format(mix))
        self.logger.info("Duration: {}".format(duration))


class vlcPlayerMock():
    '''
    Mock class for instantiating when a video/audio file is not available

    The idea is to keep all code pertaining to the media player while allowing
    for instances of OmxDmx without an actual VLC player.
    '''

    def __init__(self, filename):
        self.logger = logging.getLogger("vlcPlayerMock")
        self.logger.info("Mock VLC player class initiated")

        self.pauseEvent = evento.event.Event()
        self.playEvent = evento.event.Event()
        self.stopEvent = evento.event.Event()
        self.exitEvent = evento.event.Event()
        self.seekEvent = evento.event.Event()
        self.positionEvent = evento.event.Event()

        self.playbackStatus = "Stopped"  # ("Playing" | "Paused" | "Stopped")
        self.start_time = datetime.utcnow() # keep track of when mock system started "playing"

    def hide_video(self):
        pass

    def pause(self):
        self.playbackStatus = "Paused"
        self.pauseEvent(self)

    def play(self):
        self.playbackStatus = "Playing"
        self.start_time = datetime.utcnow()
        self.logger.debug("start_time = {0}".format(self.start_time.timestamp()))
        self.playEvent(self)

    def position(self):
        current_position = float((datetime.utcnow() - self.start_time).total_seconds())
        self.logger.debug("current_position = {0}".format(current_position))
        return current_position

    def stop(self):
        self.playbackStatus = "Stopped"
        self.stopEvent(self)

    def exit(self):
        self.exitEvent(self)

    def seek(self, val):
        self.seekEvent(self)

    def seek_to_start(self):
        self.seekEvent(self)

    def playback_status(self):
        return self.playbackStatus

    def show_video(self):
        pass

    def duration(self):
        return (sys.maxsize)  # always greater than position()

    def quit(self):
        pass


class OmxDmx(Thread):
    def __init__(self, buttonEvent, killEvent, mediafile=None, dmxDevice="/dev/null", autorepeat=False, dmxChannels=[1], dmxDefaultVals=255, defaultTransition_t=0, sequence=[]):
        super().__init__()
        self.logger = logging.getLogger("omxdmx")
        self.buttonEvent = buttonEvent
        self.killEvent = killEvent

        self.mediafile = mediafile

        self.player = self.playerFactory(self.mediafile, self.logger)

        # Automatically start and restart after end of sequence
        self.autorepeat = autorepeat
        if self.autorepeat:
            self.buttonEvent.set()

        self.dmxChannels = dmxChannels

        if(type(dmxDefaultVals) == type(list())):
            self.dmxDefaultVals = dmxDefaultVals
        else:
            self.dmxDefaultVals = [dmxDefaultVals] * len(self.dmxChannels)
        self.dmxDefaultVals += [0] * (len(self.dmxChannels)-len(self.dmxDefaultVals))  # extend if too short
        self.dmxDefaultVals = self.dmxDefaultVals[:len(self.dmxChannels)] # cut if too long

        self.defaultTransition_t = defaultTransition_t
        self.isDefault = False

        self.sequence = sequence
        if not len(self.sequence):
            self.sequence.append({
                'dmx_levels': self.dmxDefaultVals,
                'dmx_transition': self.defaultTransition_t,
                'end_time': self.player.duration() - END_DURATION_OFFSET
                })

        # setup DMX device
        self.numChannels = max(self.dmxChannels) + 1
        try:
            self.dmx = pysimpledmx.DMXConnection(dmxDevice,
                softfail=True, numChannels=self.numChannels)
        except Exception as e:
            self.logger.exception("DMX device failure, creating mock device")
            self.dmx = dmxMock()

        self.dmx.ramp(self.dmxChannels,
                self.dmxDefaultVals,
                self.defaultTransition_t)
        self.DMXisDefault = True

        # set state before run
        self.running = True
        self.playing = False

    def run(self):
        '''
        Main video playing function.
        Will run until KeyboardInterrupt or catastrophic failure.
        '''

        self.logger.debug("Waiting for video")
        while self.running:
            if(self.buttonEvent.is_set()):
                self.playing = True
                self.logger.debug("Starting Video")
            elif not self.DMXisDefault:
                # if "button" is not pressed, go to default
                self.dmx.ramp(self.dmxChannels,
                    self.dmxDefaultVals,
                    self.defaultTransition_t)
                self.DMXisDefault = True
                self.logger.debug("Button not pushed, setting lights to default values")

            if(self.killEvent.is_set()):
                self.killThread()
                break

            while self.playing:
                # make sure the media player is still alive
                try:
                    self.player.playback_status()
                except PlayerDeadError as e:
                    self.logger.exception("Media player has died. Exiting")
                    sys.exit(1)

                self.playFromBeginning()
                for steps in self.sequence:
                    try:
                        self.player.playback_status()
                    except PlayerDeadError as e:
                        self.logger.exception("Media player has died. Exiting")
                        sys.exit(1)

                    # the player stops if the whole video plays.
                    self.logger.debug("player at position: {}".format(self.player.position()))

                    end_check = (self.player.duration() - steps['end_time'])
                    if((self.player.duration() - steps['end_time']) < END_DURATION_OFFSET):
                        self.logger.warning("Media file is shorter than LIGHTING_SEQUENCE. Stopping video to keep application alive.")
                        self.player.pause()
                        self.player.hide_video()
                        self.playing = False
                        break

                    # handle DMX
                    self.dmx.ramp(self.dmxChannels, steps['dmx_levels'], steps['dmx_transition'])

                    sleeptime = steps['end_time'] - self.player.position()
                    # exit thread on kill event
                    if(self.killEvent.wait(sleeptime)):
                        self.killThread()
                        break

                self.DMXisDefault = False
                self.buttonEvent.clear()
                self.player.pause()
                self.player.hide_video()
                self.playing = False

                if self.autorepeat:
                    self.buttonEvent.set()

        self.player.quit()

    def killThread(self):
        '''
        Method used to kill thread once
        self.killEvent event is set
        '''
        self.logger.debug("kill event received, killing app")
        self.running = False
        self.killEvent.clear()

    def playFromBeginning(self):
        '''
        Simple wrapper for playing from start.
        '''

        self.player.play()
        sleep(.1)
        self.player.seek_to_start()  # player to "beginning"
        sleep(.5)
        self.player.show_video()

    @staticmethod
    def playerFactory(filename, logger):
        '''
        Creates an instance of VlcPlayer in the starting state we desire.

        If filename does not exist (or is None), generates a Mock device
        with equivalent functionality (but no media output)
        '''

        if filename is not None and not os.path.isfile(filename):
            logger.warning("Media file: {} DOES NOT EXIST".format(filename))
            filename = None # force use of the mock device below

        if filename is None:
            player = vlcPlayerMock(filename)
        else:
            try:
                player = VlcPlayer(filename, logger)
            except Exception as e:
                logger.exception("Could not start VLC, creating mock device")
                player = vlcPlayerMock(filename)

        player.playEvent += lambda _: logger.debug("Play")
        player.pauseEvent += lambda _: logger.debug("Pause")
        player.stopEvent += lambda _: logger.debug("Stop")

        try:
            player.hide_video()
            player.pause()
        except Exception as e:
            logger.exception("Exception in playerFactory")
            sys.exit(1)
        return player


class RepeatScheduler(Thread):
    '''
    RepeatScheduler is a threaded scheduler for excuting a callback on a
    repeated interval
    '''
    def __init__(self, repeatTime, killEvent, callback=None, callbackArgs=()):
        Thread.__init__(self)
        self.logger = logging.getLogger("RepeatScheduler")
        self.logger.info("RepeatScheduler activated with \
            callback: {}".format(callback))

        self.killEvent = killEvent
        self.repeatTime = repeatTime
        self.callback = callback
        self.callbackArgs = callbackArgs

    def run(self):
        while not self.killEvent.wait(self.repeatTime):
            self.logger.debug("RepeatScheduler ran after waiting \
                for {} seconds".format(self.repeatTime))
            if self.callback is not None:
                self.callback(*self.callbackArgs)
        self.logger.debug("Thread exiting.")


if __name__ == '__main__':
    def increase_press_count():
        global COUNT
        COUNT += 1
        print("RepeatScheduler count: {}".format(COUNT))

    repeatTime = .1 # 1 second delay between
    killEvent = Event()
    COUNT = 0

    t = RepeatScheduler(repeatTime, killEvent, callback=increase_press_count)
    t.start()

    while(COUNT < 5):
        sleep(repeatTime)

    killEvent.set()