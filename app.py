#!/usr/bin/env python3
import argparse, sys, os, logging
from time import sleep
from threading import Event
import mediadmx
# Raspberry Pi 5 uses the new RP1 I/O controller, which the legacy RPi.GPIO
# library does not support. gpiozero (with the lgpio backend) is the modern,
# Pi 5-compatible replacement. NOTE: gpiozero uses BCM (Broadcom) pin
# numbering, not the BOARD/physical numbering used by the old RPi.GPIO code.
from gpiozero import Button, DigitalInputDevice

import default_config


class ConfigDict(dict):
    '''
    Minimal configuration container, replacing flask.config.Config.

    The application only used Flask's Config as a dict-like loader, which
    pulled in Flask/Jinja2/Werkzeug (and broke on modern Jinja2/Python).
    This imports only the UPPERCASE attributes from a config object, mirroring
    flask.config.Config.from_object().
    '''

    def __init__(self, root_path=".", defaults=None):
        super().__init__(defaults or {})
        self.root_path = root_path

    def from_object(self, obj):
        for key in dir(obj):
            if key.isupper():
                self[key] = getattr(obj, key)


def buttonCallback(buttonEvent):
    '''
    Simple callback to relay button press to other thread
    '''

    player_log.debug("Button Pressed")
    buttonEvent.set()

def buttonSetup(pin, pull_up, bounce_time, event):
    '''
    Simple helper function to get all button stuff setup
    including the button callback.

    Uses gpiozero (Pi 5 compatible). ``pin`` is a BCM GPIO number.
    A press triggers the FALLING edge (``when_pressed``) when ``pull_up`` is
    True. The returned Button must be kept referenced for the lifetime of the
    program so gpiozero does not garbage-collect it.
    '''

    button = Button(pin, pull_up=pull_up, bounce_time=bounce_time)
    button.when_pressed = lambda event=event: buttonCallback(event)
    return button


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Syncronizes video and dmx lighting \
        sequences on a Raspberry Pi using VLC and \
        and Enttec USB-to-DMX converter.")
    parser.add_argument(
        "-d",
        "--debug",
        help="increase output verbosity",
        action="store_true")
    parser.add_argument(
        "-c",
        "--config",
        help="set config filename and directory.")
    args = parser.parse_args()

    # Setup logging
    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO
    player_log = logging.getLogger("sawmill")
    logging.basicConfig(
        format='%(asctime)s:%(name)s:%(levelname)s:%(message)s', 
        datefmt='%m/%d/%Y %I:%M:%S %p', 
        level=loglevel)

    # generate application config
    config = ConfigDict("./")
    config.from_object(default_config.Config)  # load defaults

    # would try to import with `from_pyfile()` but doesn't work for this format 
    if(args.config):
        directory, module_name = os.path.split(args.config)
        module_name = os.path.splitext(module_name)[0]
        path = list(sys.path)
        sys.path.insert(0, directory)
        
        try:
            module = __import__(module_name)
            config.from_object(module.Config)
        finally:
            sys.path[:] = path # restore

    # VLC runs in-process via python-vlc, so there is no leftover external
    # player process to clean up (unlike the old omxplayer subprocess).

    buttonEvent = Event()
    mediaKillEvent = Event()

    # GPIO devices are kept referenced here so gpiozero does not
    # garbage-collect them, and so they can be closed on shutdown.
    button = None

    # flag for informing if application can ever activate
    hasActivationInput = False

    # attempt setup of "virtual" button on timer
    schedulerKillEvent = Event()  # used later, even if not connected
    schedule_t = config['SCHEDULER_TIME']
    if (schedule_t > 0):
        scheduledButton = mediadmx.RepeatScheduler(schedule_t, schedulerKillEvent,
            callback=lambda event=buttonEvent: buttonCallback(event))
        scheduledButton.start()
        hasActivationInput = True
        player_log.info("Scheduler enabled with {} second timer.".format(schedule_t))
    else:
        player_log.info("Scheduler disabled because SCHEDULER_TIME set to {}.".format(schedule_t))

    # Attempt to setup user input (button)
    gpio_values = config['GPIO_VALUES']
    if gpio_values['pin'] is not None:
        button = buttonSetup(gpio_values['pin'],
            gpio_values.get('pull_up', True),
            gpio_values.get('bounce_time', 0.2),
            buttonEvent)
        hasActivationInput = True
        player_log.info("Button enabled on BCM GPIO {}.".format(gpio_values['pin']))
    else:
        player_log.info("Button not enabled.".format())


    # check for AUTOREPEAT in config OR AUTOREPEAT toggle switch
    autorepeat = config['AUTOREPEAT']
    if (config['AUTOREPEAT_TOGGLE']['gpio_pin'] is not None):
        channel = config['AUTOREPEAT_TOGGLE']['gpio_pin']
        # Read the toggle ONCE at startup. gpiozero's DigitalInputDevice with
        # pull_up=True reports value==1 when the pin is pulled LOW (active);
        # the original RPi.GPIO code enabled autorepeat when the pin read HIGH
        # (idle), so invert to preserve the original switch behaviour.
        toggle = DigitalInputDevice(channel, pull_up=True)
        autorepeat = not toggle.value # read toggle ONCE and set to start
        toggle.close()

    if not hasActivationInput and not autorepeat:
        player_log.info("No user input--button or timer--set and AUTOREPEAT is False. Program will sit and do nothing.")

    mediaDmxThread = mediadmx.MediaDmx(buttonEvent, mediaKillEvent,
                        mediafile=config['MEDIA_NAME'],
                        autorepeat=autorepeat,
                        dmxDevice=config["DMX_DEVICE"],
                        dmxChannels=config['CHANNELS'],
                        dmxDefaultVals=config['DEFAULT_VALUE'],
                        defaultTransition_t=config['DEFAULT_TRANSITION_TIME'],
                        sequence=config['LIGHTING_SEQUENCE'])

    try:
        mediaDmxThread.start()
        mediaDmxThread.join()
    except KeyboardInterrupt as e:
        player_log.exception("KeyboardInterrupt")
        schedulerKillEvent.set()
        mediaKillEvent.set()
        while(mediaDmxThread.is_alive()):
            player_log.debug("waiting for thread to quit")
            sleep(1)
    except SystemExit as e:
        player_log.exception("SystemExit")
        schedulerKillEvent.set()
        mediaKillEvent.set()
        while(mediaDmxThread.is_alive()):
            player_log.debug("waiting for thread to quit")
            sleep(1)
    finally:
        if button is not None:
            button.close()
