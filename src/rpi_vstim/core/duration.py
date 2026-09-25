def seconds_to_frames(seconds: float, refresh_hz: float) -> int:
    frames = seconds * refresh_hz
    rounded = round(frames)
    if abs(frames - rounded) > 1e-9:
        raise ValueError(f"duration is not an integer number of frames: {seconds}s at {refresh_hz}Hz")
    return rounded

