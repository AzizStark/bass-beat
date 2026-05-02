import numpy as np
import sounddevice as sd
import threading
import os
import math

try:
    import pulsectl
    HAS_PULSECTL = True
except ImportError:
    HAS_PULSECTL = False

FFT_SIZE = 8192
FFT_BUFFER_SIZE = 16384
SAMPLE_RATE = 48000
FREQ_MIN = 22
FREQ_MAX = 200
SENSITIVITY = 33
FFT_ATTACK = 0
FFT_DECAY = 65
NUM_BANDS = 60


def _get_monitor_source_name():
    if not HAS_PULSECTL:
        return None
    try:
        pulse = pulsectl.Pulse('bassbeat2-detect')
        default_sink = pulse.server_info().default_sink_name
        monitor_name = default_sink + '.monitor'
        for src in pulse.source_list():
            if src.name == monitor_name:
                pulse.close()
                return monitor_name
        for src in pulse.source_list():
            if '.monitor' in src.name:
                pulse.close()
                return src.name
        pulse.close()
    except Exception:
        pass
    return None


def _move_stream_to_monitor(monitor_name):
    if not HAS_PULSECTL or not monitor_name:
        return
    try:
        pulse = pulsectl.Pulse('bassbeat2-move')
        source_idx = None
        for src in pulse.source_list():
            if src.name == monitor_name:
                source_idx = src.index
                break
        if source_idx is not None:
            for rec in pulse.source_output_list():
                app_name = rec.proplist.get('application.name', '')
                if 'bassbeat2' in app_name.lower() or 'portaudio' in app_name.lower() or 'python' in app_name.lower():
                    pulse.source_output_move(rec.index, source_idx)
                    print(f"Audio: moved stream to monitor '{monitor_name}'")
                    break
            else:
                for rec in pulse.source_output_list():
                    pulse.source_output_move(rec.index, source_idx)
                    print(f"Audio: moved stream {rec.index} to monitor '{monitor_name}'")
                    break
        pulse.close()
    except Exception as e:
        print(f"Audio: could not move to monitor: {e}")


def _build_hann_window_periodic(n):
    """Periodic Hann window.

    w[0] = 0.0
    w[i] = 0.5 * (1 - cos(2*pi*i / (N+1)))  for i = 1..N-1
    """
    w = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        w[i] = 0.5 * (1.0 - math.cos(2.0 * math.pi * i / (n + 1)))
    return w


def _compute_band_freqs(num_bands, freq_min, freq_max):
    """Logarithmic band center frequencies."""
    step = math.log(freq_max / freq_min) / num_bands / math.log(2.0)
    band_freq = np.zeros(num_bands, dtype=np.float64)
    band_freq[0] = freq_min * (2.0 ** (step / 2.0))
    for i in range(1, num_bands):
        band_freq[i] = band_freq[i - 1] * (2.0 ** step)
    return band_freq


def _compute_fft_filter_constants(sample_rate, attack_ms, decay_ms, fps=62.5, fps_sync=True):
    """Compute per-bin attack/decay filter constants.

    k = exp(log10(0.01) / (freq * 0.001 * envFFT * 0.001))

    The base k is calibrated for 62.5 fps.
    When fps_sync=True, rescale so the per-second decay rate is identical at any fps.
    When fps_sync=False, use the raw k value (decay speed changes with fps).
    """
    if attack_ms > 0:
        k_attack = math.exp(math.log10(0.01) / (sample_rate * 0.001 * attack_ms * 0.001))
        if fps_sync:
            k_attack = k_attack ** (62.5 / fps)
    else:
        k_attack = 0.0

    if decay_ms > 0:
        k_decay = math.exp(math.log10(0.01) / (sample_rate * 0.001 * decay_ms * 0.001))
        if fps_sync:
            k_decay = k_decay ** (62.5 / fps)
    else:
        k_decay = 0.0

    return k_attack, k_decay


class AudioCapture:
    def __init__(self, num_bands=NUM_BANDS, fft_size=FFT_SIZE,
                 fft_buffer_size=FFT_BUFFER_SIZE,
                 sample_rate=SAMPLE_RATE,
                 freq_min=FREQ_MIN, freq_max=FREQ_MAX,
                 sensitivity=SENSITIVITY,
                 fft_attack=FFT_ATTACK, fft_decay=FFT_DECAY,
                 fps=60, fps_sync_decay=True, latency=128):
        self.num_bands = num_bands
        self.fft_size = fft_size
        self.fft_buffer_size = fft_buffer_size
        self.sample_rate = sample_rate
        self._latency = latency
        self.freq_min = freq_min
        self.freq_max = freq_max
        self.sensitivity = sensitivity
        self.fft_attack = fft_attack
        self.fft_decay = fft_decay

        self._ring_buffer = np.zeros(fft_size, dtype=np.float32)
        self._write_pos = 0
        self._lock = threading.Lock()

        self._window = _build_hann_window_periodic(fft_size)

        self._band_freq = _compute_band_freqs(num_bands, freq_min, freq_max)

        self._k_attack, self._k_decay = _compute_fft_filter_constants(
            sample_rate, fft_attack, fft_decay, fps, fps_sync_decay
        )

        self._fft_out = np.zeros(fft_buffer_size // 2 + 1, dtype=np.float64)

        self._bands = np.zeros(num_bands, dtype=np.float64)

        self._stream = None
        self._monitor_name = _get_monitor_source_name()

    def start(self):
        self._lower_audio_latency()

        if self._monitor_name:
            os.environ['PULSE_SOURCE'] = self._monitor_name
            print(f"Audio: PULSE_SOURCE={self._monitor_name}")

        self._stream = sd.InputStream(
            device=None,
            channels=2,
            samplerate=self.sample_rate,
            blocksize=128,
            dtype='float32',
            callback=self._audio_callback,
        )
        self._stream.start()

        if self._monitor_name:
            import time
            time.sleep(0.1)
            _move_stream_to_monitor(self._monitor_name)

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _lower_audio_latency(self):
        if self._latency <= 0:
            return
        import subprocess
        import shutil
        quantum = str(self._latency)
        if shutil.which("pw-metadata"):
            try:
                subprocess.run(
                    ["pw-metadata", "-n", "settings", "0", "clock.force-quantum", quantum],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
                )
                print(f"Audio: PipeWire quantum set to {quantum}")
            except Exception:
                pass

    def _audio_callback(self, indata, frames, time_info, status):
        if indata.shape[1] >= 2:
            mono = (indata[:, 0] + indata[:, 1]) * 0.5
        else:
            mono = indata[:, 0]
        n = len(mono)
        with self._lock:
            end = self._write_pos + n
            if end <= self.fft_size:
                self._ring_buffer[self._write_pos:end] = mono
            else:
                first = self.fft_size - self._write_pos
                self._ring_buffer[self._write_pos:] = mono[:first]
                self._ring_buffer[:n - first] = mono[first:]
            self._write_pos = end % self.fft_size

    def get_bands(self):
        with self._lock:
            wp = self._write_pos
            chunk = np.empty(self.fft_size, dtype=np.float64)
            chunk[:self.fft_size - wp] = self._ring_buffer[wp:]
            chunk[self.fft_size - wp:] = self._ring_buffer[:wp]

        windowed = chunk * self._window

        fft_complex = np.fft.rfft(windowed, n=self.fft_buffer_size)

        scalar = 1.0 / math.sqrt(self.fft_size)
        new_fft = (fft_complex.real ** 2 + fft_complex.imag ** 2) * scalar

        rising = new_fft >= self._fft_out
        self._fft_out[:] = np.where(
            rising,
            new_fft + self._k_attack * (self._fft_out - new_fft),
            new_fft + self._k_decay * (self._fft_out - new_fft),
        )

        df = float(self.sample_rate) / self.fft_buffer_size
        band_scalar = 2.0 / float(self.sample_rate)
        band_out = np.zeros(self.num_bands, dtype=np.float64)

        i_bin = int(round(self.freq_min / df))
        i_band = 0
        f0 = float(self.freq_min)
        half_bins = self.fft_buffer_size // 2
        fft_len = len(self._fft_out)

        while i_bin <= half_bins and i_band < self.num_bands:
            f_lin1 = (i_bin + 0.5) * df
            f_log1 = self._band_freq[i_band]
            x = self._fft_out[i_bin] if i_bin < fft_len else 0.0

            if f_lin1 <= f_log1:
                band_out[i_band] += (f_lin1 - f0) * x * band_scalar
                f0 = f_lin1
                i_bin += 1
            else:
                band_out[i_band] += (f_log1 - f0) * x * band_scalar
                f0 = f_log1
                i_band += 1

        band_out = np.clip(band_out, 0.0, 1.0)
        mask = band_out > 0.0
        band_out[mask] = np.maximum(0.0, 10.0 / self.sensitivity * np.log10(band_out[mask]) + 1.0)
        self._bands[:] = band_out

        return self._bands.copy()
