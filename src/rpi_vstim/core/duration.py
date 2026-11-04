from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def seconds_to_frames(seconds: float, refresh_hz: float) -> int:
    if seconds < 0 or refresh_hz <= 0:
        raise ValueError("seconds must be non-negative and refresh_hz must be positive")
    frames = seconds * refresh_hz
    rounded = round(frames)
    if abs(frames - rounded) > 1e-9:
        raise ValueError(f"duration is not an integer number of frames: {seconds}s at {refresh_hz}Hz")
    return rounded


def milliseconds_to_frames(milliseconds: float, refresh_hz: float) -> int:
    """Round to nearest frame; exact halves round up and nonzero requests get one frame."""
    if type(milliseconds) not in (int, float) or type(refresh_hz) not in (int, float):
        raise ValueError("milliseconds and refresh_hz must be numbers")
    try:
        duration = Decimal(str(milliseconds))
        refresh = Decimal(str(refresh_hz))
        if not duration.is_finite() or not refresh.is_finite() or duration < 0 or refresh <= 0:
            raise ValueError("milliseconds must be finite and non-negative; refresh_hz must be finite and positive")
        frames = int((duration * refresh / 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise ValueError("milliseconds and refresh_hz must be finite") from exc
    return max(1, frames) if duration else 0
