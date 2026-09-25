def seconds_to_frames(seconds: float, refresh_hz: float) -> int:
    if seconds < 0 or refresh_hz <= 0:
        raise ValueError("seconds must be non-negative and refresh_hz must be positive")
    frames = seconds * refresh_hz
    rounded = round(frames)
    if abs(frames - rounded) > 1e-9:
        raise ValueError(f"duration is not an integer number of frames: {seconds}s at {refresh_hz}Hz")
    return rounded
