"""Reserved GPIO policy shared by configuration and guards."""

IRIG_OUTPUT_GPIO_BCM = 9
RESERVED_GPIO_BCM = frozenset({IRIG_OUTPUT_GPIO_BCM})
# Legacy optional operator-button service; current Pi 5 profiles leave it unassigned.
OPERATOR_BAIT_GPIO_BCM = 23
LICK_CENTER_GPIO_BCM = 15


def reserved_gpio_message(pin: int) -> str:
    if pin == IRIG_OUTPUT_GPIO_BCM:
        return "BCM GPIO9 is reserved for IRIG output."
    return f"BCM GPIO{pin} is reserved and currently unused"
