"""
Shared ONNX Runtime configuration for all models.

Centralizes session options to prevent thread contention.
"""

import os

import onnxruntime as ort


def onnx_threads():
    """BEN_ONNX_THREADS: threads one model may use inside a single run. Default 2."""
    try:
        return max(1, int(os.getenv('BEN_ONNX_THREADS') or 2))
    except Exception:
        return 2

# Global session options - shared by all ONNX models
def get_session_options():
    """Get optimized session options for ONNX Runtime."""
    sess_options = ort.SessionOptions()

    # Memory optimization
    sess_options.enable_mem_pattern = True
    sess_options.enable_cpu_mem_arena = True

    # Thread settings. This was fixed at 1; it is BEN_ONNX_THREADS now, default 2, which
    # is the service's two CPUs (2026-10-12). Only one model runs at a time - a request
    # holds the bid lock or the card lock while it thinks - so the threads of the other
    # sessions are idle, and they are told NOT to spin while idle: ONNX Runtime's workers
    # otherwise keep a core busy for a moment after every run, and with seventeen sessions
    # on two CPUs that is time taken from the double-dummy solver.
    threads = onnx_threads()
    sess_options.intra_op_num_threads = threads
    sess_options.inter_op_num_threads = 1
    if threads > 1:
        try:
            sess_options.add_session_config_entry('session.intra_op.allow_spinning', '0')
        except Exception:
            pass

    # Execution mode - sequential is often faster for small batches
    sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

    # Graph optimization - use extended for balance of speed vs memory
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED

    return sess_options


def create_session(model_path):
    """Create an ONNX inference session with optimized settings."""
    return ort.InferenceSession(model_path, get_session_options())
