#include "capture_protocol.h"

#include <windows.h>

#include <cstdio>
#include <string>

namespace {

std::wstring g_context_path;
std::wstring g_ready_event_name;
std::wstring g_release_event_name;
HANDLE g_ready_event = nullptr;
HANDLE g_release_event = nullptr;

bool write_snapshot(const crashcap::ContextSnapshot& snapshot) {
  HANDLE file = CreateFileW(g_context_path.c_str(), GENERIC_WRITE, 0, nullptr,
                            CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
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

  // The collector waits for this event before invoking MiniDumpWriteDump.
  // Keep the target alive until the collector has a consistent exception
  // snapshot and dump, then let the original exception terminate the target.
  (void)write_snapshot(snapshot);
  if (g_ready_event != nullptr) {
    SetEvent(g_ready_event);
  }
  if (g_release_event != nullptr) {
    WaitForSingleObject(g_release_event, 30000);
  }
  return EXCEPTION_EXECUTE_HANDLER;
}

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

}  // namespace

namespace crashcap {

// Keep this frame stable and visible in the PDB. The volatile read prevents
// the compiler from deleting the faulting operation.
__declspec(noinline) void trigger_null_read() {
  volatile const int* address = nullptr;
  volatile int value = *address;
  (void)value;
}

}  // namespace crashcap

int wmain(int argc, wchar_t** argv) {
  SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX |
               SEM_NOOPENFILEERRORBOX);

  if (!take_value(argc, argv, L"--context", &g_context_path) ||
      !take_value(argc, argv, L"--ready-event", &g_ready_event_name) ||
      !take_value(argc, argv, L"--release-event", &g_release_event_name)) {
    std::fwprintf(stderr,
                  L"usage: null_read_target.exe --context <file> "
                  L"--ready-event <name> --release-event <name>\n");
    return 2;
  }

  g_ready_event = OpenEventW(EVENT_MODIFY_STATE, FALSE,
                             g_ready_event_name.c_str());
  g_release_event = OpenEventW(SYNCHRONIZE, FALSE,
                               g_release_event_name.c_str());
  if (g_ready_event == nullptr || g_release_event == nullptr) {
    std::fwprintf(stderr, L"OpenEventW failed: %lu\n", GetLastError());
    return 3;
  }

  SetUnhandledExceptionFilter(on_unhandled_exception);
  crashcap::trigger_null_read();

  CloseHandle(g_ready_event);
  CloseHandle(g_release_event);
  return 4;
}
