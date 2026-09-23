"""Deterministic original MIDI, PCM WAV, and Vorbis audio synthesis."""

from array import array
from dataclasses import dataclass
import io
import math
import os
import struct
import subprocess
import wave

from asset_generation.procedural_common import seed_int


SAMPLE_RATE = 22050


@dataclass(frozen=True)
class AudioPolicy:
    family: str
    duration_seconds: float


def audio_policy(path: str) -> AudioPolicy:
    lower = path.lower()
    parts = lower.split("/")
    if "/bgm/" in lower or parts[-2:-1] == ["music"] or "/music/" in lower or "/bgm/" in lower:
        return AudioPolicy("bgm", 8.0)
    if "/bgs/" in lower:
        return AudioPolicy("bgs", 5.0)
    if "/me/" in lower:
        return AudioPolicy("me", 2.5)
    if "/se/" in lower or parts[-2:-1] == ["sound"] or "/sound/" in lower or "systemfile/se_" in lower:
        return AudioPolicy("se", 0.45 + (seed_int(path) % 65) / 100.0)
    # RM2000/2003 root category checks after normalization.
    if lower.startswith("music/"):
        return AudioPolicy("bgm", 8.0)
    if lower.startswith("sound/"):
        return AudioPolicy("se", 0.45 + (seed_int(path) % 65) / 100.0)
    if lower.startswith("data/bgm/"):
        return AudioPolicy("bgm", 8.0)
    if lower.startswith("data/se/"):
        return AudioPolicy("se", 0.45 + (seed_int(path) % 65) / 100.0)
    raise ValueError(f"No audio policy for {path}")


def _variable_length(value: int) -> bytes:
    buffer = value & 0x7F
    out = bytearray([buffer])
    while value >> 7:
        value >>= 7
        buffer = (value & 0x7F) | 0x80
        out.insert(0, buffer)
    return bytes(out)


def _track(events: bytes) -> bytes:
    return b"MTrk" + struct.pack(">I", len(events)) + events


def midi_bytes(creative_id: str, family: str) -> bytes:
    seed = seed_int(f"midi:{creative_id}")
    division = 480
    bpm = 84 + seed % 53
    tempo = round(60_000_000 / bpm)
    tempo_track = bytearray()
    tempo_track += b"\x00\xff\x51\x03" + tempo.to_bytes(3, "big")
    tempo_track += b"\x00\xff\x58\x04\x04\x02\x18\x08"
    tempo_track += b"\x00\xff\x2f\x00"

    name = creative_id.lower()
    minor = any(word in name for word in ("battle", "boss", "dark", "dungeon", "danger", "evil", "defeat", "night"))
    scale = (0, 2, 3, 5, 7, 8, 10) if minor else (0, 2, 4, 5, 7, 9, 11)
    root = 45 + seed % 12
    program = seed % 80
    bars = 4 if family == "me" else 16
    music = bytearray(b"\x00" + bytes((0xC0, program)))
    for step in range(bars * 4):
        degree = (seed >> (step % 32)) % len(scale)
        octave = 12 if (seed + step) % 5 == 0 else 0
        note = min(96, root + scale[degree] + octave)
        velocity = 68 + (seed + step * 11) % 28
        music += b"\x00" + bytes((0x90, note, velocity))
        music += _variable_length(division) + bytes((0x80, note, 0))
    music += b"\x00\xff\x2f\x00"
    header = b"MThd" + struct.pack(">IHHH", 6, 1, 2, division)
    return header + _track(bytes(tempo_track)) + _track(bytes(music))


def _frequency(note: int) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def _envelope(index: int, total: int, family: str) -> float:
    attack = max(1, int(total * (0.01 if family == "se" else 0.03)))
    release = max(1, int(total * (0.12 if family in ("se", "me") else 0.03)))
    return min(1.0, index / attack, (total - index - 1) / release)


def pcm_samples(creative_id: str, policy: AudioPolicy) -> array:
    seed = seed_int(f"pcm:{creative_id}:{policy.family}")
    count = max(1, round(policy.duration_seconds * SAMPLE_RATE))
    samples = array("h")
    name = creative_id.lower()
    minor = any(word in name for word in ("battle", "boss", "dark", "dungeon", "danger", "evil", "defeat", "night", "damage"))
    scale = (0, 3, 5, 7, 10) if minor else (0, 2, 4, 7, 9)
    root = 45 + seed % 12
    lcg = seed & 0x7FFFFFFF
    for index in range(count):
        time = index / SAMPLE_RATE
        envelope = max(0.0, _envelope(index, count, policy.family))
        if policy.family == "bgs":
            lcg = (1103515245 * lcg + 12345) & 0x7FFFFFFF
            noise = (lcg / 0x3FFFFFFF) - 1.0
            if any(word in name for word in ("wind", "rain", "wave", "river", "sea", "fire", "drip")):
                carrier = math.sin(2 * math.pi * (70 + seed % 90) * time)
                value = noise * 0.14 + carrier * 0.08
            else:
                value = math.sin(2 * math.pi * (45 + seed % 55) * time) * 0.18 + noise * 0.05
        elif policy.family == "se":
            base = 80 + seed % 900
            sweep = base * (1.0 + (0.8 if seed & 1 else -0.45) * index / count)
            tone = math.sin(2 * math.pi * sweep * time)
            overtone = math.sin(2 * math.pi * sweep * (1.5 + (seed % 4) * 0.25) * time)
            lcg = (1103515245 * lcg + 12345) & 0x7FFFFFFF
            noise = (lcg / 0x3FFFFFFF) - 1.0
            percussive = any(word in name for word in ("attack", "hit", "slash", "blow", "break", "damage", "thunder", "explosion"))
            value = tone * 0.34 + overtone * 0.16 + (noise * 0.18 if percussive else 0.0)
        else:
            beat_seconds = 0.32 if policy.family == "me" else 0.42 + (seed % 7) * 0.01
            beat = int(time / beat_seconds)
            note = root + scale[(beat + seed) % len(scale)] + (12 if (beat + seed) % 8 in (3, 7) else 0)
            freq = _frequency(note)
            local = (time % beat_seconds) / beat_seconds
            note_env = min(1.0, local * 12.0) * max(0.0, 1.0 - local * 0.75)
            chord = math.sin(2 * math.pi * freq * time)
            chord += 0.45 * math.sin(2 * math.pi * freq * 1.5 * time)
            chord += 0.25 * math.sin(2 * math.pi * freq * 2.0 * time)
            pulse = math.sin(2 * math.pi * (55 + seed % 25) * time) * (0.18 if beat % 4 == 0 and local < 0.3 else 0.0)
            value = chord * 0.20 * note_env + pulse
        samples.append(max(-32767, min(32767, round(value * envelope * 32767))))
    return samples


def wav_bytes(creative_id: str, policy: AudioPolicy) -> bytes:
    samples = pcm_samples(creative_id, policy)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(samples.tobytes())
    return buffer.getvalue()


def ogg_bytes(creative_id: str, policy: AudioPolicy) -> bytes:
    wav = wav_bytes(creative_id, policy)
    serial = seed_int(f"ogg:{creative_id}") % 2_000_000_000
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "pipe:0", "-ac", "2",
        "-fflags", "+bitexact", "-flags:a", "+bitexact", "-c:a", "vorbis", "-strict", "-2", "-q:a", "3",
        "-map_metadata", "-1", "-serial_offset", str(serial), "-f", "ogg", "pipe:1",
    ]
    result = subprocess.run(command, input=wav, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0 or not result.stdout.startswith(b"OggS"):
        raise RuntimeError(f"ffmpeg OGG encoding failed: {result.stderr.decode('utf-8', 'replace')}")
    return result.stdout


def render_audio(path: str, creative_id: str, policy: AudioPolicy) -> bytes:
    extension = os.path.splitext(path)[1].lower()
    if extension == ".mid":
        return midi_bytes(creative_id, policy.family)
    if extension == ".wav":
        return wav_bytes(creative_id, policy)
    if extension == ".ogg":
        return ogg_bytes(creative_id, policy)
    raise ValueError(f"Unsupported audio extension: {extension}")
