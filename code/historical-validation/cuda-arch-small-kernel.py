#!/usr/bin/env python3
"""One 1-KiB CUDA allocation, one 256-thread launch, exact result check."""
import ctypes as C
import datetime
import os
from pathlib import Path
import re
import sys

PTX = b'''.version 7.0
.target sm_80
.address_size 64
.visible .entry add_one(.param .u64 buffer) {
    .reg .b32 %r1;
    .reg .b64 %rd<3>;
    .reg .f32 %f1;
    ld.param.u64 %rd0, [buffer];
    mov.u32 %r1, %tid.x;
    mul.wide.u32 %rd1, %r1, 4;
    add.u64 %rd2, %rd0, %rd1;
    ld.global.f32 %f1, [%rd2];
    add.f32 %f1, %f1, 0f3f800000;
    st.global.f32 [%rd2], %f1;
    ret;
}
'''

def validate(values):
    expected = [float(i+1) for i in range(256)]
    if list(values) != expected:
        raise RuntimeError('CUDA readback mismatch')

def main():
    if len(sys.argv) != 3 or not re.fullmatch(r'[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]', sys.argv[1]):
        raise SystemExit('Run only through the guarded CUDA smoke runner')
    directory = Path(sys.argv[2])
    if directory != Path('/root/egpu-arch-proprietary-615-cuda-continuation') or not directory.is_dir():
        raise SystemExit('Missing guarded trial directory')
    with (directory/'cuda-stages.log').open('a', buffering=1) as log:
        def note(text):
            message = datetime.datetime.now(datetime.timezone.utc).isoformat()+' '+text
            print(message, flush=True)
            log.write(message+'\n'); log.flush(); os.fsync(log.fileno())
        note('before CDLL libcuda615')
        lib = C.CDLL('/usr/lib/libcuda.so.615.71.09')
        signatures = {
            'cuInit': [C.c_uint],
            'cuDeviceGetByPCIBusId': [C.POINTER(C.c_int), C.c_char_p],
            'cuDeviceGetName': [C.c_void_p, C.c_int, C.c_int],
            'cuCtxCreate_v2': [C.POINTER(C.c_void_p), C.c_uint, C.c_int],
            'cuMemAlloc_v2': [C.POINTER(C.c_uint64), C.c_size_t],
            'cuMemcpyHtoD_v2': [C.c_uint64, C.c_void_p, C.c_size_t],
            'cuModuleLoadData': [C.POINTER(C.c_void_p), C.c_void_p],
            'cuModuleGetFunction': [C.POINTER(C.c_void_p), C.c_void_p, C.c_char_p],
            'cuLaunchKernel': [C.c_void_p, C.c_uint, C.c_uint, C.c_uint, C.c_uint, C.c_uint, C.c_uint, C.c_uint, C.c_void_p, C.POINTER(C.c_void_p), C.c_void_p],
            'cuCtxSynchronize': [],
            'cuMemcpyDtoH_v2': [C.c_void_p, C.c_uint64, C.c_size_t],
            'cuMemFree_v2': [C.c_uint64],
            'cuModuleUnload': [C.c_void_p],
            'cuCtxDestroy_v2': [C.c_void_p],
        }
        for name, args in signatures.items():
            getattr(lib, name).argtypes = args
            getattr(lib, name).restype = C.c_int
        def call(name, *args):
            note('before '+name)
            code = getattr(lib, name)(*args)
            note(name+' result='+str(code))
            if code != 0:
                raise RuntimeError(name+' failed, CUDA error '+str(code))
        call('cuInit', 0)
        device = C.c_int()
        call('cuDeviceGetByPCIBusId', C.byref(device), sys.argv[1].encode())
        name = C.create_string_buffer(256)
        call('cuDeviceGetName', name, len(name), device)
        note('GPU '+name.value.decode())
        context, module, function = C.c_void_p(), C.c_void_p(), C.c_void_p()
        call('cuCtxCreate_v2', C.byref(context), 0, device)
        pointer = C.c_uint64()
        host = (C.c_float*256)(*range(256))
        call('cuMemAlloc_v2', C.byref(pointer), C.sizeof(host))
        call('cuMemcpyHtoD_v2', pointer, host, C.sizeof(host))
        ptx = C.create_string_buffer(PTX)
        call('cuModuleLoadData', C.byref(module), ptx)
        call('cuModuleGetFunction', C.byref(function), module, b'add_one')
        args = (C.c_void_p*1)(C.cast(C.byref(pointer), C.c_void_p))
        call('cuLaunchKernel', function, 1, 1, 1, 256, 1, 1, 0, None, args, None)
        call('cuCtxSynchronize')
        call('cuMemcpyDtoH_v2', host, pointer, C.sizeof(host))
        validate(host)
        note('PASS: all256 CUDA results correct')
        # Normal successful cleanup only; no additional GPU calls after an error.
        call('cuMemFree_v2', pointer)
        call('cuModuleUnload', module)
        call('cuCtxDestroy_v2', context)

if __name__ == '__main__':
    main()
