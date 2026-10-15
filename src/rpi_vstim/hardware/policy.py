"""Reserved and current-rig GPIO policy shared by configuration and guards."""

IRIG_OUTPUT_GPIO_BCM = 9
SOUND_TRIGGER_1_GPIO_BCM = 23
SOUND_TRIGGER_2_GPIO_BCM = 24
SOUND_TRIGGER_GPIO_BCM = frozenset({SOUND_TRIGGER_1_GPIO_BCM, SOUND_TRIGGER_2_GPIO_BCM})
RESERVED_GPIO_BCM = frozenset({IRIG_OUTPUT_GPIO_BCM})
# Legacy operator-button service only; the current Pi 5 rig uses GPIO23 for sound.
OPERATOR_BAIT_GPIO_BCM = 23
LICK_CENTER_GPIO_BCM = 15


def reserved_gpio_message(pin: int) -> str:
    if pin == IRIG_OUTPUT_GPIO_BCM:
        return "BCM GPIO9 is reserved for IRIG output."
    if pin == SOUND_TRIGGER_1_GPIO_BCM:
        return "BCM GPIO23 is sound_trigger_1 on the current Pi 5 rig."
    if pin == SOUND_TRIGGER_2_GPIO_BCM:
        return "BCM GPIO24 is sound_trigger_2 on the current Pi 5 rig."
    return f"BCM GPIO{pin} is reserved and currently unused"
