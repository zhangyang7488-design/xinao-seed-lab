"""Minimal Windows Job Object process carrier for crash-recoverable ownership.

The ordinary :mod:`subprocess` Windows implementation does not expose
``PROC_THREAD_ATTRIBUTE_JOB_LIST``.  This module deliberately implements only
the process surface needed by the research-of-research runner:

* create a new, uniquely named Job Object;
* place the root process in that Job atomically in ``CreateProcessW``;
* give the root process an inherited keepalive Job handle so the name survives
  the spawning runner's death;
* inherit only the explicitly selected standard-I/O and keepalive handles; and
* observe, wait for, or terminate the whole Job rather than a bare PID.

It does not set ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` and never turns a PID
returned by a query into termination authority.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, BinaryIO

ERROR_FILE_NOT_FOUND = 2
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_ALREADY_EXISTS = 183
ERROR_MORE_DATA = 234

PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x0002000D

EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x00000100

JOB_OBJECT_ASSIGN_PROCESS = 0x0001
JOB_OBJECT_QUERY = 0x0004
JOB_OBJECT_TERMINATE = 0x0008
JOB_OBJECT_BASIC_PROCESS_ID_LIST = 3

DUPLICATE_SAME_ACCESS = 0x00000002
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF


class WindowsJobError(RuntimeError):
    """A typed, fail-closed Windows Job carrier failure."""

    def __init__(self, reason_code: str, message: str, *, winerror: int | None = None):
        super().__init__(message)
        self.reason_code = reason_code
        self.winerror = winerror


class JobState(str, Enum):
    """Mechanically observable state of a named Job Object."""

    PRESENT_NONEMPTY = "PRESENT_NONEMPTY"
    PRESENT_EMPTY = "PRESENT_EMPTY"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class JobSnapshot:
    """One instantaneous, non-authoritative Job Object observation."""

    job_name: str
    state: JobState
    process_ids: tuple[int, ...] = ()
    winerror: int | None = None
    error_message: str | None = None


if sys.platform == "win32":
    from ctypes import wintypes

    SIZE_T = ctypes.c_size_t
    DWORD_PTR = ctypes.c_size_t

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [
            ("StartupInfo", _STARTUPINFOW),
            ("lpAttributeList", ctypes.c_void_p),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]


def _require_windows() -> None:
    if sys.platform != "win32":
        raise WindowsJobError(
            "PLATFORM_UNSUPPORTED", "Windows Job Objects are available only on Windows"
        )


def _validate_job_name(job_name: str) -> str:
    if not isinstance(job_name, str) or not job_name.startswith("Global\\"):
        raise WindowsJobError("JOB_NAME_INVALID", "job_name must use the Global\\ namespace")
    suffix = job_name.removeprefix("Global\\")
    if not suffix or "\\" in suffix or "\x00" in suffix:
        raise WindowsJobError("JOB_NAME_INVALID", "job_name has an invalid Global\\ suffix")
    return job_name


class _Kernel32:
    def __init__(self) -> None:
        _require_windows()
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        self.dll = dll

        dll.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        dll.CreateJobObjectW.restype = wintypes.HANDLE
        dll.OpenJobObjectW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        dll.OpenJobObjectW.restype = wintypes.HANDLE
        dll.DuplicateHandle.argtypes = (
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        dll.DuplicateHandle.restype = wintypes.BOOL
        dll.GetCurrentProcess.argtypes = ()
        dll.GetCurrentProcess.restype = wintypes.HANDLE
        dll.CloseHandle.argtypes = (wintypes.HANDLE,)
        dll.CloseHandle.restype = wintypes.BOOL
        dll.CreatePipe.argtypes = (
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        dll.CreatePipe.restype = wintypes.BOOL

        dll.InitializeProcThreadAttributeList.argtypes = (
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(SIZE_T),
        )
        dll.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        dll.UpdateProcThreadAttribute.argtypes = (
            ctypes.c_void_p,
            wintypes.DWORD,
            DWORD_PTR,
            ctypes.c_void_p,
            SIZE_T,
            ctypes.c_void_p,
            ctypes.POINTER(SIZE_T),
        )
        dll.UpdateProcThreadAttribute.restype = wintypes.BOOL
        dll.DeleteProcThreadAttributeList.argtypes = (ctypes.c_void_p,)
        dll.DeleteProcThreadAttributeList.restype = None

        dll.CreateProcessW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.POINTER(_PROCESS_INFORMATION),
        )
        dll.CreateProcessW.restype = wintypes.BOOL
        dll.QueryInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        dll.QueryInformationJobObject.restype = wintypes.BOOL
        dll.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        dll.TerminateJobObject.restype = wintypes.BOOL
        dll.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        dll.WaitForSingleObject.restype = wintypes.DWORD
        dll.GetExitCodeProcess.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        )
        dll.GetExitCodeProcess.restype = wintypes.BOOL

    def close(self, handle: int | None) -> None:
        if handle:
            self.dll.CloseHandle(wintypes.HANDLE(handle))

    def duplicate_inheritable(self, handle: int, *, desired_access: int | None = None) -> int:
        duplicated = wintypes.HANDLE()
        current = self.dll.GetCurrentProcess()
        access = 0 if desired_access is None else int(desired_access)
        options = DUPLICATE_SAME_ACCESS if desired_access is None else 0
        if not self.dll.DuplicateHandle(
            current,
            wintypes.HANDLE(handle),
            current,
            ctypes.byref(duplicated),
            access,
            True,
            options,
        ):
            _raise_last_error("HANDLE_DUPLICATE_FAILED", "DuplicateHandle failed")
        return int(duplicated.value)


_KERNEL32: _Kernel32 | None = None


def _kernel32() -> _Kernel32:
    global _KERNEL32
    if _KERNEL32 is None:
        _KERNEL32 = _Kernel32()
    return _KERNEL32


def _raise_last_error(reason_code: str, message: str) -> None:
    code = ctypes.get_last_error()
    detail = ctypes.FormatError(code).strip() if code else "unknown Windows error"
    raise WindowsJobError(reason_code, f"{message}: [{code}] {detail}", winerror=code)


def _format_windows_error(code: int) -> str:
    try:
        return ctypes.FormatError(code).strip()
    except Exception:
        return f"Windows error {code}"


def _handle_value(handle: Any) -> int:
    value = getattr(handle, "value", handle)
    if value is None:
        return 0
    return int(value)


def _file_handle(stream: Any, *, label: str) -> int:
    import msvcrt

    try:
        fd = int(stream) if isinstance(stream, int) else int(stream.fileno())
        handle = int(msvcrt.get_osfhandle(fd))
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise WindowsJobError("STDIO_INVALID", f"{label} is not a Windows file handle") from exc
    if handle == -1:
        raise WindowsJobError("STDIO_INVALID", f"{label} has an invalid Windows handle")
    return handle


@dataclass
class _PreparedStream:
    child_handle: int
    parent_stream: BinaryIO | None


def _pipe_stream(*, child_reads: bool) -> _PreparedStream:
    """Return an inheritable child duplicate and a non-inheritable parent stream."""

    import msvcrt

    kernel = _kernel32()
    read_handle = wintypes.HANDLE()
    write_handle = wintypes.HANDLE()
    if not kernel.dll.CreatePipe(ctypes.byref(read_handle), ctypes.byref(write_handle), None, 0):
        _raise_last_error("PIPE_CREATE_FAILED", "CreatePipe failed")
    read_value = _handle_value(read_handle)
    write_value = _handle_value(write_handle)
    child_original = read_value if child_reads else write_value
    parent_handle = write_value if child_reads else read_value
    child_duplicate = 0
    try:
        child_duplicate = kernel.duplicate_inheritable(child_original)
        kernel.close(child_original)
        child_original = 0
        flags = (os.O_WRONLY if child_reads else os.O_RDONLY) | os.O_BINARY
        fd = msvcrt.open_osfhandle(parent_handle, flags)
        parent_handle = 0
        mode = "wb" if child_reads else "rb"
        parent_stream = os.fdopen(fd, mode, buffering=0)
        return _PreparedStream(child_duplicate, parent_stream)
    except BaseException:
        kernel.close(child_duplicate)
        kernel.close(child_original)
        kernel.close(parent_handle)
        raise


def _prepare_stream(stream: Any, *, label: str, child_reads: bool) -> _PreparedStream:
    if stream == subprocess.PIPE:
        return _pipe_stream(child_reads=child_reads)
    if stream is None or stream in (subprocess.DEVNULL, subprocess.STDOUT):
        raise WindowsJobError(
            "STDIO_UNSUPPORTED",
            f"{label} must be subprocess.PIPE or an explicit open binary file",
        )
    original = _file_handle(stream, label=label)
    return _PreparedStream(_kernel32().duplicate_inheritable(original), None)


def _environment_block(env: Mapping[str, str] | None) -> ctypes.Array[ctypes.c_wchar] | None:
    if env is None:
        return None
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_key, raw_value in env.items():
        key = str(raw_key)
        value = str(raw_value)
        folded = key.casefold()
        if not key or "=" in key or "\x00" in key or "\x00" in value:
            raise WindowsJobError(
                "ENVIRONMENT_INVALID", "environment contains an invalid key/value"
            )
        if folded in seen:
            raise WindowsJobError(
                "ENVIRONMENT_INVALID", "environment has case-insensitive duplicate keys"
            )
        seen.add(folded)
        rows.append((key, value))
    rows.sort(key=lambda item: item[0].casefold())
    raw = "\x00".join(f"{key}={value}" for key, value in rows) + "\x00\x00"
    return ctypes.create_unicode_buffer(raw)


def _create_attribute_list(
    job_handle: int, inherited_handles: Sequence[int]
) -> tuple[ctypes.Array[ctypes.c_char], Any, Any]:
    kernel = _kernel32()
    size = SIZE_T()
    ctypes.set_last_error(0)
    first = kernel.dll.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
    error = ctypes.get_last_error()
    if first or error != ERROR_INSUFFICIENT_BUFFER or not size.value:
        raise WindowsJobError(
            "ATTRIBUTE_LIST_SIZE_FAILED",
            f"InitializeProcThreadAttributeList sizing failed: [{error}] "
            f"{_format_windows_error(error)}",
            winerror=error,
        )
    buffer = ctypes.create_string_buffer(size.value)
    pointer = ctypes.cast(buffer, ctypes.c_void_p)
    if not kernel.dll.InitializeProcThreadAttributeList(pointer, 2, 0, ctypes.byref(size)):
        _raise_last_error(
            "ATTRIBUTE_LIST_INITIALIZE_FAILED", "InitializeProcThreadAttributeList failed"
        )

    job_array = (wintypes.HANDLE * 1)(wintypes.HANDLE(job_handle))
    handle_array = (wintypes.HANDLE * len(inherited_handles))(
        *(wintypes.HANDLE(value) for value in inherited_handles)
    )
    try:
        if not kernel.dll.UpdateProcThreadAttribute(
            pointer,
            0,
            PROC_THREAD_ATTRIBUTE_JOB_LIST,
            ctypes.cast(job_array, ctypes.c_void_p),
            ctypes.sizeof(job_array),
            None,
            None,
        ):
            _raise_last_error("JOB_ATTRIBUTE_FAILED", "JOB_LIST attribute update failed")
        if not kernel.dll.UpdateProcThreadAttribute(
            pointer,
            0,
            PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            ctypes.cast(handle_array, ctypes.c_void_p),
            ctypes.sizeof(handle_array),
            None,
            None,
        ):
            _raise_last_error("HANDLE_ATTRIBUTE_FAILED", "HANDLE_LIST attribute update failed")
    except BaseException:
        kernel.dll.DeleteProcThreadAttributeList(pointer)
        raise
    # Arrays must remain live until CreateProcessW returns.
    return buffer, job_array, handle_array


def _query_job_handle(job_handle: int, job_name: str) -> JobSnapshot:
    kernel = _kernel32()
    capacity = 16
    pointer_size = ctypes.sizeof(ctypes.c_size_t)
    header_size = ctypes.sizeof(wintypes.DWORD) * 2
    for _ in range(18):
        raw = ctypes.create_string_buffer(header_size + capacity * pointer_size)
        returned = wintypes.DWORD()
        ctypes.set_last_error(0)
        success = kernel.dll.QueryInformationJobObject(
            wintypes.HANDLE(job_handle),
            JOB_OBJECT_BASIC_PROCESS_ID_LIST,
            ctypes.cast(raw, ctypes.c_void_p),
            ctypes.sizeof(raw),
            ctypes.byref(returned),
        )
        error = ctypes.get_last_error()
        header = ctypes.cast(raw, ctypes.POINTER(wintypes.DWORD))
        assigned = int(header[0])
        in_list = int(header[1])
        if success and in_list >= assigned:
            pid_array = (ctypes.c_size_t * in_list).from_buffer(raw, header_size)
            pids = tuple(int(pid_array[index]) for index in range(in_list))
            state = JobState.PRESENT_NONEMPTY if pids else JobState.PRESENT_EMPTY
            return JobSnapshot(job_name=job_name, state=state, process_ids=pids)
        if error == ERROR_MORE_DATA or assigned > in_list or assigned > capacity:
            capacity = max(capacity * 2, assigned + 8)
            continue
        return JobSnapshot(
            job_name=job_name,
            state=JobState.UNKNOWN,
            winerror=error,
            error_message=_format_windows_error(error),
        )
    return JobSnapshot(
        job_name=job_name,
        state=JobState.UNKNOWN,
        error_message="Job process list exceeded bounded query capacity",
    )


def query_named_job(job_name: str) -> JobSnapshot:
    """Open and query a named Job, mapping all non-absence failures to UNKNOWN."""

    _require_windows()
    job_name = _validate_job_name(job_name)
    kernel = _kernel32()
    ctypes.set_last_error(0)
    opened = kernel.dll.OpenJobObjectW(JOB_OBJECT_QUERY, False, job_name)
    if not opened:
        error = ctypes.get_last_error()
        if error == ERROR_FILE_NOT_FOUND:
            return JobSnapshot(job_name=job_name, state=JobState.ABSENT, winerror=error)
        return JobSnapshot(
            job_name=job_name,
            state=JobState.UNKNOWN,
            winerror=error,
            error_message=_format_windows_error(error),
        )
    handle = _handle_value(opened)
    try:
        return _query_job_handle(handle, job_name)
    finally:
        kernel.close(handle)


def terminate_named_job(job_name: str, *, exit_code: int = 1) -> JobSnapshot:
    """Terminate a named Job using the Job handle, never member PIDs.

    ABSENT and UNKNOWN are returned without an effect.  A present snapshot is
    returned after issuing ``TerminateJobObject``; termination completion is
    intentionally observed by a subsequent query.
    """

    _require_windows()
    job_name = _validate_job_name(job_name)
    if not 0 <= int(exit_code) <= 0xFFFFFFFF:
        raise WindowsJobError("EXIT_CODE_INVALID", "exit_code must fit an unsigned DWORD")
    kernel = _kernel32()
    ctypes.set_last_error(0)
    opened = kernel.dll.OpenJobObjectW(JOB_OBJECT_QUERY | JOB_OBJECT_TERMINATE, False, job_name)
    if not opened:
        error = ctypes.get_last_error()
        if error == ERROR_FILE_NOT_FOUND:
            return JobSnapshot(job_name=job_name, state=JobState.ABSENT, winerror=error)
        return JobSnapshot(
            job_name=job_name,
            state=JobState.UNKNOWN,
            winerror=error,
            error_message=_format_windows_error(error),
        )
    handle = _handle_value(opened)
    try:
        before = _query_job_handle(handle, job_name)
        if before.state == JobState.UNKNOWN:
            return before
        if before.state == JobState.PRESENT_NONEMPTY and not kernel.dll.TerminateJobObject(
            wintypes.HANDLE(handle), int(exit_code)
        ):
            error = ctypes.get_last_error()
            return JobSnapshot(
                job_name=job_name,
                state=JobState.UNKNOWN,
                process_ids=before.process_ids,
                winerror=error,
                error_message=_format_windows_error(error),
            )
        return before
    finally:
        kernel.close(handle)


class WindowsJobProcess:
    """Small Popen-compatible view whose liveness is the entire Job Object."""

    def __init__(
        self,
        *,
        args: Sequence[str],
        job_name: str,
        process_handle: int,
        job_handle: int,
        pid: int,
        stdin: BinaryIO | None,
        stdout: BinaryIO | None,
        stderr: BinaryIO | None,
    ) -> None:
        self.args = list(args)
        self.job_name = job_name
        self.pid = int(pid)
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.returncode: int | None = None
        self._process_handle = int(process_handle)
        self._job_handle = int(job_handle)

    def job_snapshot(self) -> JobSnapshot:
        if not self._job_handle:
            return query_named_job(self.job_name)
        return _query_job_handle(self._job_handle, self.job_name)

    def _root_returncode(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        if not self._process_handle:
            return None
        kernel = _kernel32()
        wait_result = int(kernel.dll.WaitForSingleObject(wintypes.HANDLE(self._process_handle), 0))
        if wait_result == WAIT_TIMEOUT:
            return None
        if wait_result == WAIT_FAILED:
            _raise_last_error("PROCESS_WAIT_FAILED", "WaitForSingleObject failed")
        if wait_result != WAIT_OBJECT_0:
            raise WindowsJobError(
                "PROCESS_WAIT_UNKNOWN",
                f"WaitForSingleObject returned unexpected status {wait_result}",
            )
        exit_code = wintypes.DWORD()
        if not kernel.dll.GetExitCodeProcess(
            wintypes.HANDLE(self._process_handle), ctypes.byref(exit_code)
        ):
            _raise_last_error("PROCESS_EXIT_QUERY_FAILED", "GetExitCodeProcess failed")
        self.returncode = int(exit_code.value)
        return self.returncode

    def poll(self) -> int | None:
        snapshot = self.job_snapshot()
        if snapshot.state in (JobState.PRESENT_NONEMPTY, JobState.UNKNOWN):
            return None
        return self._root_returncode()

    def wait(self, timeout: float | None = None) -> int:
        if timeout is not None and timeout < 0:
            timeout = 0
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            result = self.poll()
            if result is not None:
                return result
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.args, timeout)
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            time.sleep(min(0.05, remaining) if remaining is not None else 0.05)

    def terminate_tree(self, *, exit_code: int = 1) -> None:
        if not self._job_handle:
            raise WindowsJobError("JOB_HANDLE_CLOSED", "Job owner handle is already closed")
        if not 0 <= int(exit_code) <= 0xFFFFFFFF:
            raise WindowsJobError("EXIT_CODE_INVALID", "exit_code must fit an unsigned DWORD")
        kernel = _kernel32()
        if not kernel.dll.TerminateJobObject(wintypes.HANDLE(self._job_handle), int(exit_code)):
            _raise_last_error("JOB_TERMINATE_FAILED", "TerminateJobObject failed")

    def close(self) -> None:
        for stream_name in ("stdin", "stdout", "stderr"):
            stream = getattr(self, stream_name)
            if stream is not None and not stream.closed:
                stream.close()
        kernel = _kernel32()
        kernel.close(self._process_handle)
        kernel.close(self._job_handle)
        self._process_handle = 0
        self._job_handle = 0

    def __enter__(self) -> WindowsJobProcess:
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def spawn_windows_job_process(
    args: Sequence[str | os.PathLike[str]],
    *,
    job_name: str,
    cwd: str | os.PathLike[str],
    stdin: Any = subprocess.PIPE,
    stdout: Any,
    stderr: Any,
    env: Mapping[str, str] | None = None,
    creationflags: int = CREATE_NO_WINDOW,
) -> WindowsJobProcess:
    """Create a process atomically inside a new, uniquely named Job Object.

    ``args[0]`` must be an existing absolute executable.  ``stdin``, ``stdout``
    and ``stderr`` must each be an explicit binary file or ``subprocess.PIPE``;
    ``stderr=subprocess.STDOUT`` is also supported.  No handles other than the
    selected streams and the inherited Job-name anchor can enter the child.
    """

    _require_windows()
    job_name = _validate_job_name(job_name)
    if not args:
        raise WindowsJobError("COMMAND_INVALID", "args must not be empty")
    command = [os.fspath(value) for value in args]
    if any("\x00" in value for value in command):
        raise WindowsJobError("COMMAND_INVALID", "command contains a NUL character")
    executable = Path(command[0])
    if not executable.is_absolute() or not executable.is_file():
        raise WindowsJobError(
            "EXECUTABLE_INVALID", "args[0] must be an existing absolute executable"
        )
    workdir = Path(cwd).resolve(strict=True)
    if not workdir.is_dir():
        raise WindowsJobError("WORKDIR_INVALID", "cwd must be an existing directory")
    if creationflags & (EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT):
        raise WindowsJobError(
            "CREATION_FLAGS_INVALID",
            "caller must not supply internally owned extended/unicode flags",
        )

    kernel = _kernel32()
    ctypes.set_last_error(0)
    created_job = kernel.dll.CreateJobObjectW(None, job_name)
    if not created_job:
        _raise_last_error("JOB_CREATE_FAILED", "CreateJobObjectW failed")
    job_handle = _handle_value(created_job)
    create_error = ctypes.get_last_error()
    if create_error == ERROR_ALREADY_EXISTS:
        kernel.close(job_handle)
        raise WindowsJobError(
            "JOB_ALREADY_EXISTS",
            "the deterministic Job name already exists; refusing to adopt it",
            winerror=create_error,
        )

    prepared: list[_PreparedStream] = []
    child_handles: list[int] = []
    keepalive_handle = 0
    attribute_buffer: ctypes.Array[ctypes.c_char] | None = None
    process_info = _PROCESS_INFORMATION()
    process_created = False
    try:
        stdin_prepared = _prepare_stream(stdin, label="stdin", child_reads=True)
        prepared.append(stdin_prepared)
        stdout_prepared = _prepare_stream(stdout, label="stdout", child_reads=False)
        prepared.append(stdout_prepared)
        if stderr == subprocess.STDOUT:
            stderr_prepared = _PreparedStream(stdout_prepared.child_handle, None)
        else:
            stderr_prepared = _prepare_stream(stderr, label="stderr", child_reads=False)
            prepared.append(stderr_prepared)

        # The carrier needs an object reference, not Job control authority.
        # SYNCHRONIZE is sufficient to keep the named kernel object alive and
        # withholds ASSIGN/QUERY/TERMINATE from this inherited anchor.
        keepalive_handle = kernel.duplicate_inheritable(job_handle, desired_access=SYNCHRONIZE)
        child_handles = list(
            dict.fromkeys(
                [
                    stdin_prepared.child_handle,
                    stdout_prepared.child_handle,
                    stderr_prepared.child_handle,
                    keepalive_handle,
                ]
            )
        )
        attribute_buffer, job_array, handle_array = _create_attribute_list(
            job_handle, child_handles
        )
        attribute_pointer = ctypes.cast(attribute_buffer, ctypes.c_void_p)

        startup = _STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput = wintypes.HANDLE(stdin_prepared.child_handle)
        startup.StartupInfo.hStdOutput = wintypes.HANDLE(stdout_prepared.child_handle)
        startup.StartupInfo.hStdError = wintypes.HANDLE(stderr_prepared.child_handle)
        startup.lpAttributeList = attribute_pointer

        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        environment = _environment_block(env)
        environment_pointer = (
            ctypes.cast(environment, ctypes.c_void_p) if environment is not None else None
        )
        flags = int(creationflags) | EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT
        if not kernel.dll.CreateProcessW(
            str(executable),
            command_line,
            None,
            None,
            True,
            flags,
            environment_pointer,
            str(workdir),
            ctypes.byref(startup),
            ctypes.byref(process_info),
        ):
            _raise_last_error("PROCESS_CREATE_FAILED", "CreateProcessW failed")
        process_created = True
        kernel.close(_handle_value(process_info.hThread))
        process_info.hThread = wintypes.HANDLE()

        # Child duplicates are no longer needed in the runner.  The carrier now
        # owns its inherited keepalive copy and exact stdio handles.
        for handle in child_handles:
            kernel.close(handle)
        child_handles.clear()
        keepalive_handle = 0
        kernel.dll.DeleteProcThreadAttributeList(attribute_pointer)
        attribute_buffer = None

        return WindowsJobProcess(
            args=command,
            job_name=job_name,
            process_handle=_handle_value(process_info.hProcess),
            job_handle=job_handle,
            pid=int(process_info.dwProcessId),
            stdin=stdin_prepared.parent_stream,
            stdout=stdout_prepared.parent_stream,
            stderr=stderr_prepared.parent_stream,
        )
    except BaseException:
        if process_created:
            kernel.dll.TerminateJobObject(wintypes.HANDLE(job_handle), 1)
        kernel.close(_handle_value(process_info.hThread))
        kernel.close(_handle_value(process_info.hProcess))
        for handle in child_handles:
            kernel.close(handle)
        if keepalive_handle and keepalive_handle not in child_handles:
            kernel.close(keepalive_handle)
        if attribute_buffer is not None:
            kernel.dll.DeleteProcThreadAttributeList(ctypes.cast(attribute_buffer, ctypes.c_void_p))
        for item in prepared:
            if item.parent_stream is not None and not item.parent_stream.closed:
                item.parent_stream.close()
        kernel.close(job_handle)
        raise


__all__ = [
    "CREATE_NO_WINDOW",
    "JobSnapshot",
    "JobState",
    "WindowsJobError",
    "WindowsJobProcess",
    "query_named_job",
    "spawn_windows_job_process",
    "terminate_named_job",
]
