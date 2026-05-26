#!/usr/bin/env python3
"""
Rigol DHO814 USB Trace Extraction & Benchmark

Tests single trace extraction and measures throughput for SCA (Side Channel
Analysis) trace collection.

Requirements:
    pip install pyvisa pyvisa-py numpy matplotlib
"""

import pyvisa
import numpy as np
import time
import struct
import matplotlib.pyplot as plt

# Transfer waveform data in chunks (max ~250K points per SCPI query)
CHUNK_SIZE = 250000

def connect(resource_string=None):
    rm = pyvisa.ResourceManager('@py')
    
    if resource_string is None:
        resources = rm.list_resources()
        print("Available resources:", resources)
        # Find Rigol (vendor ID 0x1AB1)
        rigol = [r for r in resources if '1AB1' in r or 'USB' in r]
        if not rigol:
            raise RuntimeError("No Rigol scope found. Check USB connection.")
        resource_string = rigol[0]
    
    print(f"Connecting to: {resource_string}")
    scope = rm.open_resource(resource_string)
    scope.timeout = 10000  # 10 second timeout
    scope.chunk_size = 1024 * 1024  # 1MB chunks for fast transfer
    
    idn = scope.query('*IDN?')
    print(f"Connected: {idn.strip()}")
    return scope

def configure(scope, channel=1, trigger_channel=2, trigger_level=1.5,
              voltage_range=1.0, time_scale=1e-4, mem_depth='AUTO'):
    ch = f'CHAN{channel}'
    trig_ch = f'CHAN{trigger_channel}'

    scope.write(':STOP')

    # Enable measurement channel and trigger channel, disable others
    for i in range(1, 5):
        if i == channel or i == trigger_channel:
            scope.write(f':CHAN{i}:DISP ON')
        else:
            scope.write(f':CHAN{i}:DISP OFF')

    # Measurement channel config
    scope.write(f':{ch}:COUP DC')
    scope.write(f':{ch}:SCAL {voltage_range/8}')
    scope.write(f':{ch}:OFFS 0')

    # Trigger channel config
    scope.write(f':{trig_ch}:COUP DC')
    scope.write(f':{trig_ch}:SCAL 1.0')       # 1V/div
    scope.write(f':{trig_ch}:OFFS 0')

    scope.write(f':TIM:SCAL {time_scale}')
    actual_timescal = scope.query(':TIM:SCAL?').strip()
    print(f"Requested time_scale: {time_scale}, Actual: {actual_timescal}")
    scope.write(f':ACQ:MDEP {mem_depth}')

    num_points = int(float(scope.query(':ACQ:MDEP?').strip()))
    srate = scope.query(':ACQ:SRAT?').strip()

    if num_points <= CHUNK_SIZE:
        scope.write(':WAV:STAR 1')
        scope.write(f':WAV:STOP {num_points}')

    scope.write(':ACQ:TYPE NORM')

    # Trigger configuration
    scope.write(f':TRIG:EDGE:SOUR {trig_ch}')
    scope.write(':TRIG:EDGE:SLOP POS')
    scope.write(f':TRIG:EDGE:LEV {trigger_level}')
    scope.write(':TRIG:SWE NORM')

    # Waveform readout from measurement channel
    scope.write(f':WAV:SOUR {ch}')
    scope.write(':WAV:MODE RAW')
    scope.write(':WAV:FORM BYTE')

    print(f"Configured: CH{channel}, {voltage_range}V range, "
          f"{time_scale*1000}ms/div, {num_points} pts, {srate} Sa/s, "
          f"trigger: {trig_ch} @ {trigger_level}V")

    return num_points

def capture_trace(scope, num_points, preamble):
    """
    Trigger a single acquisition and return waveform as numpy array.
    """
    t_start = time.perf_counter()
    
    # Wait for scope to finish acquiring
    while True:
        status = scope.query(':TRIG:STAT?').strip()
        if status in ('STOP', 'TD'):
            break
        time.sleep(0.001)
    
    x_increment = float(preamble[4])  # time between samples
    x_origin    = float(preamble[5])  # time of first sample
    y_increment = float(preamble[7])  # volts per ADC step
    y_origin    = float(preamble[8])  # voltage origin
    y_reference = float(preamble[9])  # ADC reference level
    
    raw_data = []

    # If num_points <= CHUNK_SIZE, skip the loop entirely. This allows saving 2 SCPI commands per trace.
    if num_points <= CHUNK_SIZE:
        raw_data.append(scope.query_binary_values(':WAV:DATA?', datatype='B', container=np.array))
    else:
        raw_data = []
        for start in range(1, num_points + 1, CHUNK_SIZE):
            stop = min(start + CHUNK_SIZE - 1, num_points)
            scope.write(f':WAV:STAR {start}')
            scope.write(f':WAV:STOP {stop}')
            raw_data.append(scope.query_binary_values(':WAV:DATA?', datatype='B', container=np.array))
    raw = np.concatenate(raw_data).astype(np.float32)
    
    # Convert ADC counts to volts. Not required for SCA.
    voltage = (raw - y_reference) * y_increment + y_origin
    
    # Build time axis
    t_end = time.perf_counter()
    elapsed = t_end - t_start
    
    time_axis = x_origin + np.arange(len(voltage)) * x_increment
    
    return time_axis, voltage, elapsed

def benchmark(scope, channel=1, n_traces=10):
    """
    Capture n_traces sequentially and measure throughput.
    Returns list of traces and timing stats.
    """
    print(f"\nBenchmarking {n_traces} sequential captures...")
    traces = []
    times = []
    
    # Get waveform preamble (scaling info)
    preamble = scope.query(':WAV:PRE?').strip().split(',')

    for i in range(n_traces):
        _, voltage, elapsed = capture_trace(scope, num_points, preamble)
        traces.append(voltage)
        times.append(elapsed)
        print(f"  Trace {i+1:3d}/{n_traces}: {elapsed:.3f}s  ({len(voltage):,} points)")
    
    times = np.array(times)
    total = times.sum()
    
    throughput = n_traces / total  # traces/sec

    print(f"\n── Benchmark Results ──────────────────")
    print(f"  Traces captured : {n_traces}")
    print(f"  Points per trace: {len(traces[0]):,}")
    print(f"  Min time/trace  : {times.min():.3f}s")
    print(f"  Max time/trace  : {times.max():.3f}s")
    print(f"  Mean time/trace : {times.mean():.3f}s")
    print(f"  Total time      : {total:.1f}s")
    print(f"  Throughput      : {throughput:.1f} traces/sec")
    print(f"\n  Extrapolated:")
    print(f"    1,000 traces  : {1000/throughput/60:.1f} min")
    print(f"   10,000 traces  : {10000/throughput/60:.1f} min")
    print(f"  100,000 traces  : {100000/throughput/3600:.1f} hours")
    print(f"────────────────────────────────────────")

    return np.array(traces), times

def save_traces(traces, filename='traces.npy'):
    """Save traces as numpy array for use with scared/lascar."""
    np.save(filename, traces)
    print(f"Saved {traces.shape[0]} traces to {filename}")
    print(f"Shape: {traces.shape} | dtype: {traces.dtype}")
    print(f"File size: {traces.nbytes / 1024 / 1024:.1f} MB")

def plot_trace(time_axis, voltage, title='Power Trace'):
    plt.figure(figsize=(12, 4))
    plt.plot(time_axis * 1e6, voltage, linewidth=0.5)  # time in microseconds
    plt.xlabel('Time (µs)')
    plt.ylabel('Voltage (V)')
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('trace_plot.png', dpi=150)
    plt.show()
    print("Plot saved to trace_plot.png")

if __name__ == '__main__':
    
    # Connect
    scope = connect()
    
    # Configure for power analysis
    num_points = configure(
        scope,
        channel=1,
        trigger_channel=2,
        trigger_level=1.5,
        voltage_range=0.5,
        time_scale=10e-6,
        mem_depth=10000
        #mem_depth= 'AUTO'
    )

    print("\n── Single Trace Test ───────────────────")
    preamble = scope.query(':WAV:PRE?').strip().split(',')
    time_axis, voltage, elapsed = capture_trace(scope, num_points, preamble)
    print(f"  Captured {len(voltage):,} points in {elapsed:.3f}s")
    print(f"  Voltage range: {voltage.min():.4f}V to {voltage.max():.4f}V")
    
    # Plot the single trace
    plot_trace(time_axis, voltage, title='DHO814 - Single Power Trace')
    
    # Throughput benchmark — 10 traces to start
    traces, times = benchmark(scope, channel=1, n_traces=10)
    
    # Save for SCA analysis
    save_traces(traces, 'dho814_traces.npy')
    
    scope.close()
    print("\nDone.")
