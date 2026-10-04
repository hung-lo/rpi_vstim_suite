"""Canonical lab GPIO policy shared by configuration and hardware guards."""

IRIG_OUTPUT_GPIO_BCM = 9
RESERVED_GPIO_BCM = frozenset({9, 24})
OPERATOR_BAIT_GPIO_BCM = 23
LICK_CENTER_GPIO_BCM = 15


def reserved_gpio_message(pin: int) -> str:
    if pin == IRIG_OUTPUT_GPIO_BCM:
        return "BCM GPIO9 is reserved for IRIG output."
    return f"BCM GPIO{pin} is reserved and currently unused"
