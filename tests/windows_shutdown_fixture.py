"""A disposable root whose job closes its children when that root exits."""
import ctypes as C
import json
import os
import subprocess
import sys
import time


class Limits(C.Structure):
    _fields_ = [('process_time', C.c_int64), ('job_time', C.c_int64),
                ('flags', C.c_uint32), ('minimum', C.c_size_t), ('maximum', C.c_size_t),
                ('active', C.c_uint32), ('affinity', C.c_size_t),
                ('priority', C.c_uint32), ('scheduling', C.c_uint32)]


class Extended(C.Structure):
    _fields_ = [('basic', Limits), ('io', C.c_uint64 * 6),
                ('process_memory', C.c_size_t), ('job_memory', C.c_size_t),
                ('peak_process', C.c_size_t), ('peak_job', C.c_size_t)]


def main():
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = (C.c_void_p, C.c_wchar_p), C.c_void_p
    kernel.SetInformationJobObject.argtypes = (C.c_void_p, C.c_int, C.c_void_p, C.c_uint32)
    kernel.AssignProcessToJobObject.argtypes = (C.c_void_p, C.c_void_p)
    kernel.CloseHandle.argtypes = (C.c_void_p,)
    job, children = kernel.CreateJobObjectW(None, None), []
    try:
        if not job:
            raise C.WinError(C.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
        if not kernel.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)):
            raise C.WinError(C.get_last_error())
        for _ in range(4):
            child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(45)'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000)
            children.append(child)
            if not kernel.AssignProcessToJobObject(job, int(child._handle)):
                raise C.WinError(C.get_last_error())
        print(json.dumps([os.getpid()] + [child.pid for child in children]), flush=True)
        time.sleep(45)
    finally:
        if job:
            kernel.CloseHandle(job)
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)


if __name__ == '__main__':
    main()
