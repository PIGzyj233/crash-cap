#include "capture_protocol.h"

#include <windows.h>

#include <intrin.h>

#include <cstdlib>
#include <csignal>
#include <exception>
#include <stdexcept>
#include <string>
#include <thread>

namespace {

std::wstring g_context_path;
std::wstring g_ready_event_name;
std::wstring g_release_event_name;
HANDLE g_ready_event = nullptr;
HANDLE g_release_event = nullptr;

bool take_value(int argc, wchar_t** argv, const wchar_t* name,
                std::wstring* value) {
  for (int i = 1; i + 1 < argc; ++i) {
    if (std::wstring(argv[i]) == name) {
      *value = argv[i + 1];
      return true;
    }
  }
  return false;
}

bool write_snapshot(const crashcap::ContextSnapshot& snapshot) {
  HANDLE file = CreateFileW(g_context_path.c_str(), GENERIC_WRITE, 0,
                            nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL,
                            nullptr);
  if (file == INVALID_HANDLE_VALUE) {
    return false;
  }
  DWORD written = 0;
  const BOOL ok = WriteFile(file, &snapshot,
                            static_cast<DWORD>(sizeof(snapshot)), &written,
                            nullptr);
  CloseHandle(file);
  return ok && written == sizeof(snapshot);
}

LONG WINAPI on_unhandled_exception(EXCEPTION_POINTERS* pointers) {
  crashcap::ContextSnapshot snapshot;
  snapshot.process_id = GetCurrentProcessId();
  snapshot.thread_id = GetCurrentThreadId();
  if (pointers != nullptr) {
    if (pointers->ExceptionRecord != nullptr) {
      snapshot.exception_record = *pointers->ExceptionRecord;
    }
    if (pointers->ContextRecord != nullptr) {
      snapshot.context = *pointers->ContextRecord;
    }
  }
  (void)write_snapshot(snapshot);
  if (g_ready_event != nullptr) {
    SetEvent(g_ready_event);
  }
  if (g_release_event != nullptr) {
    WaitForSingleObject(g_release_event, 30000);
  }
  return EXCEPTION_EXECUTE_HANDLER;
}

void wait_without_exception() {
  SetEvent(g_ready_event);
  WaitForSingleObject(g_release_event, 30000);
}

[[noreturn]] void terminate_with_fixture_code() {
  // Keep std::terminate in the call chain while making the result stable across
  // CRT revisions. The code is fixture-owned and documented in expected.json.
  EXCEPTION_RECORD record{};
  record.ExceptionCode = 0xE0000001;
  record.ExceptionFlags = EXCEPTION_NONCONTINUABLE;
  record.ExceptionAddress = _ReturnAddress();
  CONTEXT context{};
  RtlCaptureContext(&context);
  EXCEPTION_POINTERS pointers{&record, &context};
  on_unhandled_exception(&pointers);
  TerminateProcess(GetCurrentProcess(), 0xE0000001);
  std::abort();
}

void on_abort_signal(int) {
  EXCEPTION_RECORD record{};
  record.ExceptionCode = 0x40000015;
  record.ExceptionFlags = EXCEPTION_NONCONTINUABLE;
  record.ExceptionAddress = _ReturnAddress();
  CONTEXT context{};
  RtlCaptureContext(&context);
  EXCEPTION_POINTERS pointers{&record, &context};
  on_unhandled_exception(&pointers);
  TerminateProcess(GetCurrentProcess(), 0x40000015);
}

}  // namespace

namespace crashcap {

__declspec(noinline) void trigger_null_read() {
  volatile const int* address = nullptr;
  volatile int value = *address;
  (void)value;
}

__declspec(noinline) void trigger_null_write() {
  volatile int* address = nullptr;
  *address = 0xC0FFEE;
}

__declspec(noinline) void trigger_illegal_execute() {
  using Function = void (*)();
  const auto function = reinterpret_cast<Function>(static_cast<uintptr_t>(1));
  function();
}

__declspec(noinline) void trigger_cpp_uncaught() {
  throw std::runtime_error("crash-cap synthetic uncaught exception");
}

__declspec(noinline) void trigger_std_terminate() {
  std::set_terminate(terminate_with_fixture_code);
  std::terminate();
}

__declspec(noinline) void trigger_abort() {
  std::signal(SIGABRT, on_abort_signal);
  _set_abort_behavior(0, _WRITE_ABORT_MSG | _CALL_REPORTFAULT);
  std::abort();
}

__declspec(noinline) void recurse_stack_overflow(unsigned depth) {
  volatile unsigned char padding[16 * 1024];
  padding[depth & 0x3FFF] = static_cast<unsigned char>(depth);
  recurse_stack_overflow(depth + 1);
}

__declspec(noinline) void trigger_stack_overflow() {
  recurse_stack_overflow(1);
}

__declspec(noinline) void trigger_multithread() {
  trigger_null_write();
}

inline void release_inline_leaf() {
  volatile const int* address = nullptr;
  volatile int value = *address;
  (void)value;
}

inline void release_inline_middle() { release_inline_leaf(); }

inline void release_inline_outer() { release_inline_middle(); }

void trigger_release_inline() { release_inline_outer(); }

__declspec(noinline) void deep_business_leaf() { trigger_null_read(); }

__declspec(noinline) void deep_business_middle() { deep_business_leaf(); }

__declspec(noinline) void deep_business_outer() { deep_business_middle(); }

__declspec(noinline) void trigger_deep_business_stack() {
  deep_business_outer();
}

__declspec(noinline) void trigger_async_thread_pool() { trigger_null_read(); }

DWORD WINAPI multithread_worker(LPVOID) {
  trigger_multithread();
  return 0;
}

void CALLBACK threadpool_callback(PTP_CALLBACK_INSTANCE, PVOID, PTP_WORK) {
  trigger_async_thread_pool();
}

}  // namespace crashcap

int wmain(int argc, wchar_t** argv) {
  SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX |
               SEM_NOOPENFILEERRORBOX);
  std::wstring scenario;
  if (!take_value(argc, argv, L"--scenario", &scenario) ||
      !take_value(argc, argv, L"--context", &g_context_path) ||
      !take_value(argc, argv, L"--ready-event", &g_ready_event_name) ||
      !take_value(argc, argv, L"--release-event", &g_release_event_name)) {
    return 2;
  }

  g_ready_event = OpenEventW(EVENT_MODIFY_STATE, FALSE,
                             g_ready_event_name.c_str());
  g_release_event = OpenEventW(SYNCHRONIZE, FALSE,
                               g_release_event_name.c_str());
  if (g_ready_event == nullptr || g_release_event == nullptr) {
    return 3;
  }

  SetUnhandledExceptionFilter(on_unhandled_exception);
  if (scenario == L"unknown_no_exception" || scenario == L"explicit_hang") {
    wait_without_exception();
  } else if (scenario == L"null_read") {
    crashcap::trigger_null_read();
  } else if (scenario == L"null_write") {
    crashcap::trigger_null_write();
  } else if (scenario == L"illegal_execute") {
    crashcap::trigger_illegal_execute();
  } else if (scenario == L"cpp_uncaught") {
    crashcap::trigger_cpp_uncaught();
  } else if (scenario == L"std_terminate") {
    crashcap::trigger_std_terminate();
  } else if (scenario == L"abort") {
    crashcap::trigger_abort();
  } else if (scenario == L"stack_overflow") {
    crashcap::trigger_stack_overflow();
  } else if (scenario == L"multithread") {
    HANDLE worker = CreateThread(nullptr, 0, crashcap::multithread_worker,
                                 nullptr, 0, nullptr);
    if (worker != nullptr) {
      WaitForSingleObject(worker, INFINITE);
      CloseHandle(worker);
    }
  } else if (scenario == L"release_inline") {
    crashcap::trigger_release_inline();
  } else if (scenario == L"async_thread_pool") {
    PTP_WORK work = CreateThreadpoolWork(crashcap::threadpool_callback,
                                         nullptr, nullptr);
    if (work != nullptr) {
      SubmitThreadpoolWork(work);
      WaitForThreadpoolWorkCallbacks(work, FALSE);
      CloseThreadpoolWork(work);
    }
  } else if (scenario == L"deep_business_stack") {
    crashcap::trigger_deep_business_stack();
  } else {
    return 4;
  }

  CloseHandle(g_ready_event);
  CloseHandle(g_release_event);
  return 0;
}
