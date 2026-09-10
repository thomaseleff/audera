# ADR 003: CamillaDSP Signal Chain Configuration

**Date:** 2026-05-12
**Status:** Accepted

## Context

CamillaDSP is inserted between Snapclient and the physical DAC via an ALSA loopback device. This placement introduces asynchronous buffering that sits outside Snapcast's native timing control. The signal chain is:

```
Snapclient → hw:Loopback,0 → [kernel loopback] → hw:Loopback,1 → CamillaDSP → hw:0 → DAC
```

Several config values interact — clock sync, resampling cost, device-open behaviour, and filter type — and each has a non-obvious default that fails subtly (drift, clicks, HDMI dropout, CPU saturation) if left at CamillaDSP's default. The config is rendered by `render_camilladsp` in `audera/cli/conf.py`; its inline comments own the per-key rationale.

## Decisions

### 1. Clock domain synchronization is mandatory

`enable_rate_adjust: true` must always be set. The network clock driving Snapclient and the local crystal clock driving the DAC are independent; without rate adjustment, the playback buffer will drift until an underrun or overrun occurs, producing a click or silence. The other synchronization parameters are set as follows:

| Parameter | Value | Rationale |
| :--- | :--- | :--- |
| `target_level` | `1024` | Equal to `chunksize`. Balances latency against buffer stability. |
| `adjust_period` | `5` | 5-second correction interval. Responsive to network jitter without audible pitch wobble. |

This combination introduces a fixed "blind" latency of approximately **43 ms** at 48 kHz (1024 samples ÷ 48000 Hz × 2 for capture + playback buffer). Because all nodes share this config, the 43 ms blind latency is identical across every node and cancels out — Snapcast requires no offset to compensate for it. Per-client latency offsets in the Snapserver dashboard are only needed to compensate for differences in DAC hardware latency between nodes (output FIFO, PLL, analog filter group delay), which must be determined by acoustic measurement.

### 2. Hardware rate adjustment is preferred over software resampling

Omitting the `resampler` key entirely disables software resampling, delegating clock adjustment to the ALSA loopback kernel driver at near-zero CPU cost. On an RPi Zero 2 W, software resampling imposes a measurable CPU load that competes with CamillaDSP's real-time processing budget.

If the ALSA loopback adjustment is insufficient (symptom: persistent clicks or pops), add a `resampler` block with `type: FastAsync` as the fallback. The resampler type hierarchy by CPU cost is:

1. **FastAsync** — lowest cost; sufficient when capture/playback ratio is close to 1:1.
2. **BalancedAsync** — higher quality; may cause CPU spikes on the RPi Zero 2 W.
3. **AccurateAsync** — highest quality; not suitable for the RPi Zero 2 W; intended for RPi 4 or desktop hardware.

### 3. DSP is IIR-only, compiled and pushed at runtime

The rendered config boots with an empty pipeline (`filters: {}`, `pipeline: []`). The DSP editor (`audera/domains/dsp/`) then compiles a parametric EQ — an optional mono downmix `Mixer`, L/R balance `Gain` filters, a `Gain` pre-amp, and one `Biquad` per band — and pushes it to the running daemon over the WebSocket (`SetConfigJson`), never by rewriting the file. Bands are the source of truth; the pipeline is a derived artifact. The `domains/dsp/` docstrings own the compile-and-apply flow and the auto-protected pre-amp headroom.

IIR biquads (PEQ, shelving, high/low-pass) are near-zero CPU at 48 kHz. FIR convolution is deliberately not implemented: linear-phase room correction would exceed the RPi Zero 2 W's real-time budget.

### 4. The ALSA device stays open

`stop_on_rate_change: false`, `silence_threshold: null`, and `silence_timeout: null` keep CamillaDSP's ALSA device open continuously. Closing it after silence, or stopping on an input rate change, de-clocks an HDMI sink and drops the connection.

### 5. Playback device address

Both player and streamer configs use `device: "hw:0"`. The `,0` sub-device specifier is redundant for the DigiAMP+ — ALSA resolves `hw:0` and `hw:0,0` to the same node.

**Pi 5 HDMI exception:** Pi 5's vc4-hdmi ALSA device accepts only `IEC958_SUBFRAME_LE`. CamillaDSP emits linear PCM (`S16LE`/`S32LE`), so every format open on `hw:0` returns `EINVAL`. Using `plughw:0` pulls in ALSA's `iec958` plugin automatically — no resampling, negligible CPU, no quality loss. Provisioning auto-detects the board model (`is_pi5()` in `os/dietpi/lib/config.sh`) and passes `--playback-device plughw:0` to the CLI's `conf camilladsp.yml` command. Pi 4 and all non-HDMI DACs remain on `hw:0`.

### 6. HDMI playback uses `S16LE`

The `playback.format` defaults to `S32LE`, but HDMI sinks (TVs, AVRs) frequently reject 32-bit PCM and respond with silence or dropouts. When the attached audio device is HDMI, `playback.format` is set to `S16LE` instead.

This loses no quality: the pipeline's effective ceiling is already 16-bit/48 kHz (ADR 002), so the 32-bit playback path is lossless zero-padding — narrowing it to `S16LE` discards only that padding. The **capture** format stays `S32LE` regardless, to match Snapclient's 32-bit loopback output.

The format is chosen at provisioning time rather than at runtime: `audera {player,streamer} conf camilladsp.yml --playback-format {S16LE,S32LE}` renders the config, and each `os/dietpi/{player,streamer}/automation/setup.sh` passes `S16LE` when `--audio-device hdmi` is set (via the `camilladsp_playback_format` helper in `os/dietpi/lib/config.sh`) and `S32LE` otherwise.

## Consequences

- Multi-room sync does not require any Snapcast offset to compensate for the ~43 ms CamillaDSP blind latency — it is equal on all nodes and cancels out. A per-client latency offset is only required when nodes use different DAC hardware with different output latencies; the offset value equals the acoustic latency difference between nodes, measured empirically.
- If the stream format is changed (see ADR 002), `devices.samplerate` in `audera/cli/conf.py` (`render_camilladsp`) must be updated in the same change.
- HDMI sinks require `playback.format: S16LE` (see decision 6); provisioning selects this automatically for `--audio-device hdmi`.
- Runtime health can be monitored via the CamillaDSP WebSocket status interface: a capture ratio oscillating tightly around `1.000000` indicates a healthy clock sync. Persistent deviation indicates CPU saturation, thermal throttling, or hardware clock failure.
