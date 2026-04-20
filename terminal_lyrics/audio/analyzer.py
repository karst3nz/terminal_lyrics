"""Audio capture and analysis for real-time visualization."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Literal, Optional

import numpy as np

logger = logging.getLogger(__name__)

AudioBackend = Literal["pulsectl", "sounddevice", "pyaudio", "none"]


class AudioAnalyzer:
    """Captures and analyzes audio data for visualization (asyncio-driven capture)."""

    def __init__(
        self,
        sample_rate: int = 44100,
        chunk_size: int = 512,  # Reduced from 2048 for lower latency (~11.6ms at 44.1kHz)
        num_bands: int = 20,
        device_name: Optional[str] = None,
        preferred_backend: str = "auto",
    ):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.num_bands = num_bands
        self.device_name = device_name
        self.preferred_backend = preferred_backend
        self.running = False
        self._capture_task: asyncio.Task[None] | None = None

        # Audio data (sounddevice callback runs off-loop → keep a threading lock)
        self.frequency_data: list[float] = [0.0] * num_bands
        self._freq_lock = threading.Lock()

        # Audio backend
        self.audio_available = False
        self.stream = None
        self.audio_backend: AudioBackend = "none"
        self.pulse = None
        self.monitor_source_name: Optional[str] = None

        self._parec_proc: asyncio.subprocess.Process | None = None
        self._sd_stream = None

        self._init_audio()

    def _init_audio(self):
        """Initialize audio capture library with priority: pulsectl > sounddevice > pyaudio."""

        if self.preferred_backend == "pulsectl":
            if self._try_init_pulsectl():
                return
        elif self.preferred_backend == "sounddevice":
            if self._try_init_sounddevice():
                return
        elif self.preferred_backend == "pyaudio":
            if self._try_init_pyaudio():
                return
        elif self.preferred_backend == "auto":
            if self._try_init_pulsectl():
                return
            if self._try_init_sounddevice():
                return
            if self._try_init_pyaudio():
                return

        logger.warning(
            "No audio library available. Install pulsectl, sounddevice, or pyaudio for real audio visualization"
        )

    def _try_init_pulsectl(self) -> bool:
        """Try to initialize PulseAudio/PipeWire via pulsectl."""
        try:
            import os

            import pulsectl

            pulse_server = os.environ.get("PULSE_SERVER")
            runtime_dir = os.environ.get("XDG_RUNTIME_DIR")

            if not pulse_server and not runtime_dir:
                logger.debug("No PULSE_SERVER or XDG_RUNTIME_DIR set, skipping pulsectl")
                return False

            try:
                pulse = pulsectl.Pulse("terminal_lyrics-probe", connect=False)
                pulse.connect(autospawn=False)
            except Exception as e:
                logger.debug("Could not connect to PulseAudio/PipeWire: %s", e)
                return False

            monitor_source = None
            try:
                sources = pulse.source_list()

                if self.device_name:
                    for source in sources:
                        if (
                            source.name == self.device_name
                            or source.description == self.device_name
                        ):
                            monitor_source = source.name
                            logger.info(
                                "Found requested device: %s (%s)",
                                source.description,
                                source.name,
                            )
                            break

                if not monitor_source:
                    for source in sources:
                        if ".monitor" in source.name or "monitor" in source.description.lower():
                            monitor_source = source.name
                            logger.info(
                                "Found monitor source: %s (%s)",
                                source.description,
                                source.name,
                            )
                            break

                if not monitor_source:
                    logger.debug("No monitor source found in PulseAudio/PipeWire")
                    pulse.close()
                    return False

                self.monitor_source_name = monitor_source
                self.audio_backend = "pulsectl"
                self.audio_available = True
                pulse.close()
                logger.info("Using pulsectl for audio capture (PulseAudio/PipeWire)")
                return True

            except Exception as e:
                logger.debug("Error querying PulseAudio sources: %s", e)
                pulse.close()
                return False

        except ImportError:
            logger.debug("pulsectl not available")
            return False
        except Exception as e:
            logger.debug("Could not initialize pulsectl: %s", e)
            return False

    def _try_init_sounddevice(self) -> bool:
        """Try to initialize sounddevice."""
        try:
            import sounddevice as sd

            device_index = None
            try:
                devices = sd.query_devices()

                if self.device_name:
                    for i, dev in enumerate(devices):
                        if dev["name"] == self.device_name and dev["max_input_channels"] > 0:
                            device_index = i
                            logger.info("Found requested device: %s", dev["name"])
                            break

                if device_index is None:
                    for i, dev in enumerate(devices):
                        dev_name = dev["name"].lower()
                        if (
                            any(kw in dev_name for kw in ["monitor", "loopback"])
                            and dev["max_input_channels"] > 0
                        ):
                            device_index = i
                            logger.info("Found monitor device: %s", dev["name"])
                            break

                if device_index is not None:
                    self.device_name = devices[device_index]["name"]
                else:
                    logger.debug("No monitor/loopback device found in sounddevice")
            except Exception:
                pass

            self.audio_backend = "sounddevice"
            self.audio_available = True
            logger.info("Using sounddevice for audio capture")
            return True

        except ImportError:
            logger.debug("sounddevice not available")
            return False

    def _try_init_pyaudio(self) -> bool:
        """Try to initialize pyaudio."""
        try:
            import pyaudio  # noqa: F401

            self.audio_backend = "pyaudio"
            self.audio_available = True
            logger.info("Using pyaudio for audio capture")
            return True

        except ImportError:
            logger.debug("pyaudio not available")
            return False

    def start(self) -> bool:
        """Start audio capture (requires a running asyncio event loop)."""
        if not self.audio_available:
            logger.warning("Audio capture not available")
            return False

        if self._capture_task is not None and not self._capture_task.done():
            return True

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "AudioAnalyzer.start() needs a running asyncio loop "
                "(run inside `asyncio.run()` or `terminal_lyrics watch`)."
            )
            return False

        self.running = True
        self._capture_task = loop.create_task(self._capture_runner(), name="terminal_lyrics-audio")
        return True

    def stop(self) -> None:
        """Stop audio capture and release devices."""
        self.running = False

        proc = self._parec_proc
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass

        if self._sd_stream is not None:
            try:
                self._sd_stream.abort()
            except Exception:
                logger.debug("sounddevice abort failed", exc_info=True)
            try:
                self._sd_stream.close()
            except Exception as e:
                logger.debug("sounddevice close: %s", e)
            self._sd_stream = None

        if self.stream:
            try:
                if self.audio_backend == "sounddevice":
                    self.stream.stop()
                    self.stream.close()
                elif self.audio_backend == "pyaudio":
                    self.stream.stop_stream()
                    self.stream.close()
            except Exception as e:
                logger.error("Error stopping audio stream: %s", e)
            self.stream = None

        if self.pulse:
            try:
                self.pulse.close()
            except Exception as e:
                logger.error("Error closing PulseAudio connection: %s", e)
            self.pulse = None

        t = self._capture_task
        self._capture_task = None
        if t is not None and not t.done():
            t.cancel()

    async def _capture_runner(self) -> None:
        try:
            if self.audio_backend == "pulsectl":
                await self._capture_pulsectl_async()
            elif self.audio_backend == "sounddevice":
                await self._capture_sounddevice_async()
            elif self.audio_backend == "pyaudio":
                await self._capture_pyaudio_async()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Audio capture task failed: %s", e)
        finally:
            self.running = False
            await self._async_finalize_capture()

    async def _async_finalize_capture(self) -> None:
        proc = self._parec_proc
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        self._parec_proc = None

        if self._sd_stream is not None:
            try:
                self._sd_stream.abort()
            except Exception:
                pass
            try:
                self._sd_stream.close()
            except Exception:
                pass
            self._sd_stream = None

        if self.stream and self.audio_backend == "pyaudio":
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    async def _capture_pulsectl_async(self) -> None:
        assert self.monitor_source_name is not None
        cmd = [
            "parec",
            "--device",
            self.monitor_source_name,
            "--format",
            "float32le",
            "--rate",
            str(self.sample_rate),
            "--channels",
            "1",
            "--latency-msec",
            "10",
        ]
        logger.info("Running parec: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._parec_proc = proc
        stdout = proc.stdout
        assert stdout is not None

        bytes_per_sample = 4
        latency_chunk = 256
        bytes_per_latency_chunk = latency_chunk * bytes_per_sample
        bytes_per_analysis_chunk = self.chunk_size * bytes_per_sample
        audio_buffer = bytearray()

        try:
            while self.running:
                raw_data = await stdout.read(bytes_per_latency_chunk)
                if not raw_data:
                    if proc.returncode is not None:
                        logger.error("parec process ended (code=%s)", proc.returncode)
                        break
                    await asyncio.sleep(0.002)
                    continue

                audio_buffer.extend(raw_data)
                while len(audio_buffer) >= bytes_per_analysis_chunk:
                    chunk = bytes(audio_buffer[:bytes_per_analysis_chunk])
                    del audio_buffer[:bytes_per_analysis_chunk]
                    audio_data = np.frombuffer(chunk, dtype=np.float32)
                    if len(audio_data) == self.chunk_size:
                        self._analyze_audio(audio_data)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error during parec capture: %s", e)
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    proc.kill()
            self._parec_proc = None

    async def _capture_sounddevice_async(self) -> None:
        import sounddevice as sd

        loop = asyncio.get_running_loop()
        q: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=8)

        def make_callback():
            def callback(indata, frames, time_info, status):
                if status:
                    logger.debug("Audio status: %s", status)
                audio_data = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()

                def _enqueue() -> None:
                    if not self.running:
                        return
                    try:
                        q.put_nowait(audio_data)
                    except asyncio.QueueFull:
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        try:
                            q.put_nowait(audio_data)
                        except asyncio.QueueFull:
                            pass

                loop.call_soon_threadsafe(_enqueue)

            return callback

        device_to_use = None
        if self.device_name:
            try:
                devices = sd.query_devices()
                for i, dev in enumerate(devices):
                    if dev["name"] == self.device_name and dev["max_input_channels"] > 0:
                        device_to_use = i
                        logger.info("Using configured device: %s", dev["name"])
                        break
            except Exception as e:
                logger.debug("Could not find configured device: %s", e)

        stream_params: dict = {
            "callback": make_callback(),
            "channels": 1,
            "samplerate": self.sample_rate,
            "blocksize": self.chunk_size,
        }
        if device_to_use is not None:
            stream_params["device"] = device_to_use
        else:
            logger.warning(
                "No specific device configured, using default input "
                "(may capture microphone instead of system audio)"
            )

        stream = sd.InputStream(**stream_params)
        self._sd_stream = stream
        stream.start()
        try:
            while self.running:
                try:
                    audio_data = await asyncio.wait_for(q.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                self._analyze_audio(audio_data)
        finally:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
            self._sd_stream = None

    async def _capture_pyaudio_async(self) -> None:
        import pyaudio

        def _open_stream():
            p = pyaudio.PyAudio()
            device_index = None
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if "monitor" in info["name"].lower() or "loopback" in info["name"].lower():
                    device_index = i
                    break
            stream = p.open(
                format=pyaudio.paFloat32,
                channels=1,
                rate=self.sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self.chunk_size,
            )
            return p, stream

        pa = None
        stream = None
        try:
            pa, stream = await asyncio.to_thread(_open_stream)
            self.stream = stream

            n = 0
            while self.running:

                def _read() -> bytes:
                    assert stream is not None
                    return stream.read(self.chunk_size, exception_on_overflow=False)

                data = await asyncio.to_thread(_read)
                audio_data = np.frombuffer(data, dtype=np.float32)
                self._analyze_audio(audio_data)
                n += 1
                if n % 16 == 0:
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error in pyaudio capture: %s", e)
        finally:
            if stream is not None:
                try:
                    await asyncio.to_thread(stream.stop_stream)
                    await asyncio.to_thread(stream.close)
                except Exception:
                    pass
            if pa is not None:
                try:
                    await asyncio.to_thread(pa.terminate)
                except Exception:
                    pass
            self.stream = None

    def _analyze_audio(self, audio_data):
        """Analyze audio data and extract frequency bands."""
        try:
            samples = np.asarray(audio_data, dtype=np.float32)
            if samples.size >= 1:
                samples = samples - np.mean(samples)
            if samples.size >= 4:
                samples = samples * np.hanning(samples.size)

            fft_data = np.fft.rfft(samples)
            fft_magnitude = np.abs(fft_data)
            fft_magnitude[0] = 0.0

            fft_power = np.asarray(fft_magnitude, dtype=np.float64) ** 2
            fft_power[0] = 0.0
            total_power = float(np.sum(fft_power))
            if total_power > 0:
                fft_power = fft_power / total_power

            fft_len = len(fft_power)
            sample_rate = self.sample_rate
            nyquist = sample_rate / 2

            bass_bands = 4
            log_bands = self.num_bands - bass_bands
            max_freq = min(20000, nyquist)

            bands = []

            for i in range(self.num_bands):
                if i < bass_bands:
                    start_hz = (i / bass_bands) * 500
                    end_hz = ((i + 1) / bass_bands) * 500
                else:
                    log_i = i - bass_bands
                    t_start = log_i / log_bands
                    t_end = (log_i + 1) / log_bands
                    start_hz = 500 * (max_freq / 500) ** t_start
                    end_hz = 500 * (max_freq / 500) ** t_end

                start_bin = max(0, int(start_hz / nyquist * (fft_len - 1)))
                end_bin = min(fft_len - 1, int(end_hz / nyquist * (fft_len - 1)))

                if end_bin > start_bin:
                    band_data = fft_power[start_bin:end_bin]
                    band_value = float(np.sum(band_data))
                    bands.append(band_value)
                else:
                    bands.append(0.0)

            with self._freq_lock:
                self.frequency_data = bands

        except Exception as e:
            logger.debug("Error analyzing audio: %s", e)

    def get_frequency_data(self) -> list[float]:
        """Per-band fraction of short-time spectral energy (sum ≈ 1 over bands)."""
        with self._freq_lock:
            return self.frequency_data.copy()

    def is_available(self) -> bool:
        return self.audio_available

    def is_running(self) -> bool:
        return self.running and self._capture_task is not None and not self._capture_task.done()


_audio_analyzer: Optional[AudioAnalyzer] = None


def get_audio_analyzer(
    num_bands: int = 20, device_name: Optional[str] = None, preferred_backend: str = "auto"
) -> AudioAnalyzer:
    global _audio_analyzer
    if _audio_analyzer is None:
        _audio_analyzer = AudioAnalyzer(
            num_bands=num_bands, device_name=device_name, preferred_backend=preferred_backend
        )
    return _audio_analyzer
