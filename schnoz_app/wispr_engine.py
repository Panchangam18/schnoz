"""Always-dictating WisprFlow speech-to-text client.

Adapted from schnoz/wispr_client.py. The key difference: there is no wake/stop
phrase state machine. All transcribed text is forwarded immediately — the client
is always in DICTATING mode for Ultra Schnoz.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import queue
import threading
import wave

import numpy as np
import sounddevice as sd
import websockets

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16_000       # WisprFlow requires 16 kHz
CHANNELS = 1               # mono
DTYPE = "int16"             # 16-bit PCM
CHUNK_DURATION_S = 0.5     # 500 ms per audio chunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pcm_to_wav_b64(pcm: bytes) -> str:
    """Wrap raw PCM int16 bytes in a WAV container and return base64."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _compute_volume(pcm: bytes) -> float:
    """RMS volume level from raw PCM int16 bytes."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))


# ---------------------------------------------------------------------------
# AlwaysDictatingWisprClient
# ---------------------------------------------------------------------------

class AlwaysDictatingWisprClient:
    """WebSocket client for WisprFlow — always forwards transcribed text."""

    def __init__(self, api_key: str, text_queue: queue.Queue):
        self._api_key = api_key
        self._text_queue = text_queue
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._ws = None
        self._chunk_number = 0
        self._total_packets = 0
        self._running = True

    async def _connect(self):
        url = (
            "wss://platform-api.wisprflow.ai/api/v1/dash/ws"
            f"?api_key=Bearer%20{self._api_key}"
        )
        self._ws = await websockets.connect(url)
        auth_msg = json.dumps({
            "type": "auth",
            "access_token": self._api_key,
            "language": ["en"],
        })
        await self._ws.send(auth_msg)
        resp = await self._ws.recv()
        data = json.loads(resp)
        if data.get("status") == "auth":
            print("[wispr] Authenticated with WisprFlow")
        else:
            print(f"[wispr] Auth response: {data}")
        self._chunk_number = 0
        self._total_packets = 0

    async def _send_loop(self):
        """Pull audio chunks from the queue and send to WisprFlow."""
        while self._running:
            try:
                pcm = await asyncio.wait_for(
                    self._audio_queue.get(), timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue
            if pcm is None:
                break

            wav_b64 = _pcm_to_wav_b64(pcm)
            volume = _compute_volume(pcm)
            n_samples = len(pcm) // 2
            duration_s = n_samples / SAMPLE_RATE

            msg = json.dumps({
                "type": "append",
                "position": self._total_packets,
                "audio_packets": {
                    "packets": [wav_b64],
                    "volumes": [volume],
                    "packet_duration": duration_s,
                    "audio_encoding": "wav",
                    "byte_encoding": "base64",
                },
            })
            try:
                await self._ws.send(msg)
            except websockets.ConnectionClosed:
                break
            self._chunk_number += 1
            self._total_packets += 1

    async def _commit(self):
        """Send commit to finalize the current transcription session."""
        if self._ws and self._total_packets > 0:
            msg = json.dumps({
                "type": "commit",
                "total_packets": self._total_packets,
            })
            try:
                await self._ws.send(msg)
            except websockets.ConnectionClosed:
                pass

    async def _recv_loop(self):
        """Receive transcription results — always forward text (no wake/stop phrases)."""
        try:
            async for raw in self._ws:
                data = json.loads(raw)
                status = data.get("status") or data.get("type", "")

                if status == "text":
                    text = data.get("text", "").strip()
                    if text:
                        self._text_queue.put(text)
                elif status == "error":
                    print(f"[wispr] Error: {data}")

        except websockets.ConnectionClosed as e:
            print(f"[wispr] WebSocket closed: {e}")

    async def _periodic_commit(self):
        """Periodically commit audio to get transcription results."""
        while self._running:
            await asyncio.sleep(3.0)
            if self._total_packets > 0:
                await self._commit()
                return

    def feed_audio(self, pcm_bytes: bytes):
        """Thread-safe: called from sounddevice callback to enqueue audio."""
        try:
            self._audio_queue.put_nowait(pcm_bytes)
        except asyncio.QueueFull:
            pass

    async def run(self):
        """Main entry point: connect, then run send/receive concurrently."""
        while self._running:
            try:
                await self._connect()
                await asyncio.gather(
                    self._send_loop(),
                    self._recv_loop(),
                    self._periodic_commit(),
                )
            except (websockets.ConnectionClosed, OSError) as e:
                print(f"[wispr] Connection lost ({e}), reconnecting in 2s...")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"[wispr] Unexpected error: {e}, reconnecting in 5s...")
                await asyncio.sleep(5)

    async def shutdown(self):
        self._running = False
        self._audio_queue.put_nowait(None)
        if self._ws:
            await self._ws.close()


# ---------------------------------------------------------------------------
# AudioCapture
# ---------------------------------------------------------------------------

class AudioCapture:
    """Captures microphone audio via sounddevice and feeds it to the client."""

    def __init__(self, client: AlwaysDictatingWisprClient, loop: asyncio.AbstractEventLoop):
        self._client = client
        self._loop = loop
        self._stream = None

    def start(self):
        blocksize = int(SAMPLE_RATE * CHUNK_DURATION_S)
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=blocksize,
            callback=self._callback,
        )
        self._stream.start()
        print(f"[wispr] Microphone capture started ({SAMPLE_RATE}Hz, {CHUNK_DURATION_S}s chunks)")

    def _callback(self, indata, frames, time_info, status):
        pcm_bytes = indata.tobytes()
        self._loop.call_soon_threadsafe(self._client.feed_audio, pcm_bytes)

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None


# ---------------------------------------------------------------------------
# Thread orchestrator
# ---------------------------------------------------------------------------

def start_wispr_thread(api_key: str) -> tuple[threading.Thread, queue.Queue, asyncio.AbstractEventLoop, AlwaysDictatingWisprClient]:
    """
    Start always-dictating WisprFlow client in a background daemon thread.

    Returns (thread, text_queue, loop, client).
    The caller can use loop and client to shut down gracefully.
    """
    text_queue: queue.Queue[str] = queue.Queue()
    loop = asyncio.new_event_loop()
    client = AlwaysDictatingWisprClient(api_key, text_queue)
    audio = AudioCapture(client, loop)

    def _run():
        asyncio.set_event_loop(loop)
        audio.start()
        try:
            loop.run_until_complete(client.run())
        finally:
            audio.stop()

    thread = threading.Thread(target=_run, daemon=True, name="wispr-stt")
    thread.start()
    return thread, text_queue, loop, client
