class Config():
    MEDIA_NAME = "./video/myvideo.mov" # ./ is relative to PiMediaSync repo
    DMX_DEVICE = "/dev/ttyUSB0" # the DMX device

    # configure button input using gpiozero (Raspberry Pi 5 compatible).
    # 'pin' uses BCM GPIO numbering: BCM 15 is physical pin 10.
    GPIO_VALUES = {
        'pin': 15,            # BCM GPIO 15 (== physical pin 10)
        'pull_up': True,      # internal pull-up; press pulls pin to GND (falling edge)
        'bounce_time': 0.2,   # 200ms software debounce
    }

    SCHEDULER_TIME = 600 # activate sequence automatically every 10 minutes

    AUTOREPEAT=False # auto repeat disabled

    DEFAULT_VALUE = 255 # DMX lights start/stop on brightness of 255
    # DEFAULT_VALUE = [255, 0, 255] # also allowed; will set length of list automatically if less than length of CHANNELS (below)
    DEFAULT_TRANSITION_TIME = 1 # DMX lights start/stop with transition time of 1 second
    CHANNELS = [1, 4, 3, 2, 5] # DMX light channel mapping order -- notice they can be any order
    LIGHTING_SEQUENCE = [
        {
            'dmx_levels': [0, 0, 0, 0, 0], # set all DMX outputs to 0
            'dmx_transition': 5, # take 5 seconds to transition to dmx_levels
            'end_time': 10 # after 10 second, move to the next sequence
        },
        {
            'dmx_levels': [0, 255, 0, 0, 0], # set DMX output channel 4 to 255
            'dmx_transition': 10,  # take 10 seconds to transition to dmx_levels
            'end_time': 60 # after 60 second, move to the next sequence
            # done, return to the beginning of sequence, set `DEFAULT_VALUE` and pause.
        }
    ]
