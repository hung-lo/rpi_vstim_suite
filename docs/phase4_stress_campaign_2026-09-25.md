# Phase 4 software stress campaign

All runs were hardware-free on the Mac:

- 5,000 logical natural-image frames: 4,998 consumed, transport peak 8,
  zero underruns, 7 source reads/hash calculations/decodes, 7 renderer payload
  allocations.
- 1,000 randomized state-machine sessions: all reached an explicit terminal
  result.
- 100 multi-protocol sessions: 20 each for natural images, reward
  conditioning, spout training, drifting gratings, and retinotopy; all
  completed.
- 10,000 telemetry messages into a 256-entry sink: 256 retained and 9,744
  dropped, with no unbounded growth.
- same-seed reproducibility: identical natural-image plan JSON and digest
  `13678b58239e3f0b96a3a09bdd8a5bc26dae125443203b8b804f579d33c3b74b`.

These runs validate software bounds and deterministic behavior only. They do
not validate the Pi display, cameras, SSD, GPIO/reward, or photodiode.
