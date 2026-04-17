"""Audio capture and analysis for real-time visualization."""

from __future__ import annotations

import numpy as np
import threading
import time
from typing import Optional, Literal
import logging

logger = logging.getLogger(__name__)

AudioBackend = Literal["pulsectl", "sounddevice", "pyaudio", "none"]


class AudioAnalyzer:
    """Captures and analyzes audio data for visualization."""

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
        self.thread: Optional[threading.Thread] = None

        # Audio data
        self.frequency_data: list[float] = [0.0] * num_bands
        self.lock = threading.Lock()

        # Audio backend
        self.audio_available = False
        self.stream = None
        self.audio_backend: AudioBackend = "none"
        self.pulse = None
        self.monitor_source_name: Optional[str] = None

        self._init_audio()

    def _init_audio(self):
        """Initialize audio capture library with priority: pulsectl > sounddevice > pyaudio."""

        # If specific backend is requested, try only that one
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
            # Try pulsectl first (best for PulseAudio/PipeWire on Linux)
            if self._try_init_pulsectl():
                return

            # Try sounddevice as fallback
            if self._try_init_sounddevice():
                return

            # Try pyaudio as last resort
            if self._try_init_pyaudio():
                return

        logger.warning(
            "No audio library available. Install pulsectl, sounddevice, or pyaudio for real audio visualization"
        )

    def _try_init_pulsectl(self) -> bool:
        """Try to initialize PulseAudio/PipeWire via pulsectl."""
        try:
            import pulsectl
            import os

            # Try to connect to PulseAudio/PipeWire
            # Check if we have PULSE_SERVER or XDG_RUNTIME_DIR set
            pulse_server = os.environ.get("PULSE_SERVER")
            runtime_dir = os.environ.get("XDG_RUNTIME_DIR")

            if not pulse_server and not runtime_dir:
                logger.debug("No PULSE_SERVER or XDG_RUNTIME_DIR set, skipping pulsectl")
                return False

            try:
                pulse = pulsectl.Pulse("terminal_lyrics-probe", connect=False)
                pulse.connect(autospawn=False)
            except Exception as e:
                logger.debug(f"Could not connect to PulseAudio/PipeWire: {e}")
                return False

            # Find monitor source (system audio output)
            monitor_source = None
            try:
                sources = pulse.source_list()

                # If specific device is requested, try to find it
                
                if self.device_name:
                    for source in sources:
                        if (
                            source.name == self.device_name
                            or source.description == self.device_name
                        ):
                            monitor_source = source.name
                            logger.info(
                                f"Found requested device: {source.description} ({source.name})"
                            )
                            break

                # Otherwise, find any monitor source
                if not monitor_source:
                    for source in sources:
                        # Look for monitor sources (capture from output)
                        if ".monitor" in source.name or "monitor" in source.description.lower():
                            monitor_source = source.name
                            logger.info(
                                f"Found monitor source: {source.description} ({source.name})"
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
                logger.debug(f"Error querying PulseAudio sources: {e}")
                pulse.close()
                return False

        except ImportError:
            logger.debug("pulsectl not available")
            return False
        except Exception as e:
            logger.debug(f"Could not initialize pulsectl: {e}")
            return False

    def _try_init_sounddevice(self) -> bool:
        """Try to initialize sounddevice."""
        try:
            import sounddevice as sd

            # Check if monitor devices are available
            device_index = None
            try:
                devices = sd.query_devices()

                # If specific device is requested, try to find it
                if self.device_name:
                    for i, dev in enumerate(devices):
                        if dev["name"] == self.device_name and dev["max_input_channels"] > 0:
                            device_index = i
                            logger.info(f"Found requested device: {dev['name']}")
                            break

                # Otherwise, look for monitor devices
                if device_index is None:
                    for i, dev in enumerate(devices):
                        dev_name = dev["name"].lower()
                        if (
                            any(kw in dev_name for kw in ["monitor", "loopback"])
                            and dev["max_input_channels"] > 0
                        ):
                            device_index = i
                            logger.info(f"Found monitor device: {dev['name']}")
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
            import pyaudio

            self.audio_backend = "pyaudio"
            self.audio_available = True
            logger.info("Using pyaudio for audio capture")
            return True

        except ImportError:
            logger.debug("pyaudio not available")
            return False

    def start(self):
        """Start audio capture."""
        if not self.audio_available:
            logger.warning("Audio capture not available")
            return False

        if self.running:
            return True

        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

        # Give it a moment to start, but don't block
        time.sleep(0.1)

        return True

    def stop(self):
        """Stop audio capture."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)

        # Close stream based on backend
        if self.stream:
            try:
                if self.audio_backend == "sounddevice":
                    self.stream.stop()
                    self.stream.close()
                elif self.audio_backend == "pyaudio":
                    self.stream.stop_stream()
                    self.stream.close()
            except Exception as e:
                logger.error(f"Error stopping audio stream: {e}")

        # Close PulseAudio connection
        if self.pulse:
            try:
                self.pulse.close()
            except Exception as e:
                logger.error(f"Error closing PulseAudio connection: {e}")

    def _capture_loop(self):
        """Main audio capture loop."""
        if self.audio_backend == "pulsectl":
            self._capture_pulsectl()
        elif self.audio_backend == "sounddevice":
            self._capture_sounddevice()
        elif self.audio_backend == "pyaudio":
            self._capture_pyaudio()

    def _capture_pulsectl(self):
        """Capture audio using parec (PulseAudio record) from monitor source."""
        try:
            import subprocess

            logger.info(
                f"Starting parec capture from PulseAudio source: {self.monitor_source_name}"
            )

            # Use parec to capture from the PulseAudio/PipeWire monitor source
            # parec outputs raw audio to stdout
            cmd = [
                "parec",
                "--device", self.monitor_source_name,
                "--format", "float32le",
                "--rate", str(self.sample_rate),
                "--channels", "1",
                "--latency-msec", "10",  # Low latency mode
            ]

            logger.info(f"Running command: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            logger.info("PulseAudio/PipeWire capture started via parec")

            bytes_per_sample = 4  # float32 = 4 bytes
            # Use smaller buffer for lower latency (256 samples = ~5.8ms at 44.1kHz)
            latency_chunk = 256
            bytes_per_latency_chunk = latency_chunk * bytes_per_sample

            # Accumulator for building full chunks for analysis
            audio_buffer = bytearray()
            bytes_per_analysis_chunk = self.chunk_size * bytes_per_sample

            try:
                while self.running:
                    # Read small chunks for low latency
                    raw_data = proc.stdout.read(bytes_per_latency_chunk)
                    if not raw_data:
                        if proc.poll() is not None:
                            logger.error("parec process terminated unexpectedly")
                            break
                        continue

                    # Add to buffer
                    audio_buffer.extend(raw_data)

                    # Process when we have enough data for analysis
                    while len(audio_buffer) >= bytes_per_analysis_chunk:
                        chunk = bytes(audio_buffer[:bytes_per_analysis_chunk])
                        del audio_buffer[:bytes_per_analysis_chunk]

                        # Convert raw bytes to numpy array
                        audio_data = np.frombuffer(chunk, dtype=np.float32)

                        if len(audio_data) == self.chunk_size:
                            # Analyze frequencies
                            self._analyze_audio(audio_data)

            except Exception as e:
                logger.error(f"Error during parec capture: {e}")
            finally:
                proc.terminate()
                proc.wait(timeout=5)

        except FileNotFoundError:
            logger.error("parec not found. Install pulseaudio-utils or pipewire-alsa")
            self.running = False
        except Exception as e:
            logger.error(f"Error in pulsectl capture: {e}")
            self.running = False

    def _capture_sounddevice(self):
        """Capture audio using sounddevice."""
        try:
            import sounddevice as sd

            def callback(indata, frames, time_info, status):
                if status:
                    logger.debug(f"Audio status: {status}")

                # Get audio data
                audio_data = indata[:, 0] if len(indata.shape) > 1 else indata

                # Analyze frequencies
                self._analyze_audio(audio_data)

            # Determine which device to use
            device_to_use = None

            if self.device_name:
                # Use the device that was found during init
                try:
                    devices = sd.query_devices()
                    for i, dev in enumerate(devices):
                        if dev["name"] == self.device_name and dev["max_input_channels"] > 0:
                            device_to_use = i
                            logger.info(f"Using configured device: {dev['name']}")
                            break
                except Exception as e:
                    logger.debug(f"Could not find configured device: {e}")

            # Try to open stream
            try:
                stream_params = {
                    "callback": callback,
                    "channels": 1,
                    "samplerate": self.sample_rate,
                    "blocksize": self.chunk_size,
                }

                if device_to_use is not None:
                    stream_params["device"] = device_to_use
                else:
                    logger.warning(
                        "No specific device configured, using default input (may capture microphone instead of system audio)"
                    )

                with sd.InputStream(**stream_params):
                    while self.running:
                        time.sleep(0.1)
            except Exception as e:
                logger.warning(f"Could not open audio device: {e}")
                self.running = False

        except Exception as e:
            logger.error(f"Error in sounddevice capture: {e}")
            self.running = False

    def _capture_pyaudio(self):
        """Capture audio using pyaudio."""
        try:
            import pyaudio

            p = pyaudio.PyAudio()

            # Try to find loopback device
            device_index = None
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if "monitor" in info["name"].lower() or "loopback" in info["name"].lower():
                    device_index = i
                    break

            self.stream = p.open(
                format=pyaudio.paFloat32,
                channels=1,
                rate=self.sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self.chunk_size,
            )

            while self.running:
                try:
                    data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                    audio_data = np.frombuffer(data, dtype=np.float32)
                    self._analyze_audio(audio_data)
                except Exception as e:
                    logger.debug(f"Error reading audio: {e}")
                    time.sleep(0.01)

            self.stream.stop_stream()
            self.stream.close()
            p.terminate()

        except Exception as e:
            logger.error(f"Error in pyaudio capture: {e}")
            self.running = False

    def _analyze_audio(self, audio_data):
        """Analyze audio data and extract frequency bands."""
        try:
            # Apply FFT
            fft_data = np.fft.rfft(audio_data)
            fft_magnitude = np.abs(fft_data)

            # Don't normalize by max - preserve relative band energy
            # Instead, scale by total energy for consistency across volume levels
            total_energy = np.sum(fft_magnitude)
            if total_energy > 0:
                fft_magnitude = fft_magnitude / total_energy

            fft_len = len(fft_magnitude)  # = chunk_size + 1
            sample_rate = self.sample_rate
            nyquist = sample_rate / 2  # max representable frequency

            # Frequency band boundaries
            # Linear for bass (0-500Hz), logarithmic for rest up to nyquist
            bass_bands = 4  # First 4 bands: linear 0-500Hz
            log_bands = self.num_bands - bass_bands
            max_freq = min(20000, nyquist)  # Cap at nyquist

            bands = []

            for i in range(self.num_bands):
                if i < bass_bands:
                    # Linear distribution for bass: 0-500Hz
                    start_hz = (i / bass_bands) * 500
                    end_hz = ((i + 1) / bass_bands) * 500
                else:
                    # Logarithmic distribution: 500Hz-max_freq
                    log_i = i - bass_bands
                    t_start = log_i / log_bands
                    t_end = (log_i + 1) / log_bands
                    start_hz = 500 * (max_freq / 500) ** t_start
                    end_hz = 500 * (max_freq / 500) ** t_end

                # Convert Hz to FFT bin indices
                start_bin = max(0, int(start_hz / nyquist * (fft_len - 1)))
                end_bin = min(fft_len - 1, int(end_hz / nyquist * (fft_len - 1)))

                if end_bin > start_bin:
                    band_data = fft_magnitude[start_bin:end_bin]
                    band_value = float(np.sum(band_data))
                    bands.append(band_value)
                else:
                    bands.append(0.0)

            # Normalize bands relative to each other (max band = 1.0)
            max_band = max(bands) if bands else 0
            if max_band > 0:
                bands = [b / max_band for b in bands]

            # Update frequency data with lock
            with self.lock:
                self.frequency_data = bands

        except Exception as e:
            logger.debug(f"Error analyzing audio: {e}")

    def get_frequency_data(self) -> list[float]:
        """Get current frequency band data."""
        with self.lock:
            return self.frequency_data.copy()

    def is_available(self) -> bool:
        """Check if audio capture is available."""
        return self.audio_available

    def is_running(self) -> bool:
        """Check if audio capture is running."""
        return self.running


# Singleton instance
_audio_analyzer: Optional[AudioAnalyzer] = None


def get_audio_analyzer(
    num_bands: int = 20, device_name: Optional[str] = None, preferred_backend: str = "auto"
) -> AudioAnalyzer:
    """Get or create audio analyzer instance."""
    global _audio_analyzer
    if _audio_analyzer is None:
        _audio_analyzer = AudioAnalyzer(
            num_bands=num_bands, device_name=device_name, preferred_backend=preferred_backend
        )
    return _audio_analyzer